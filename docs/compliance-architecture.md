# Compliance Architecture - Sovereign Defence Intelligence Platform

End-to-end view of the integrated compliance pipeline that powers the
`ComplianceView` UI in the German operator console. Combines a static catalogue
of 31 controls in Oracle 26ai with four live OCI posture checks, fused into a
per-framework score per tenant.

## 1. Control catalogue (Oracle 26ai)

| Framework | Controls | OLS labels (count) |
|---|---|---|
| NIS2 | 12 | R x 8, C x 4 |
| DORA | 8 | R x 6, C x 2 |
| GDPR | 6 | R x 4, C x 2 |
| VS-NfD | 5 | R x 1, C x 4 |
| **Total** | **31** | — |

Source of truth: `db/seed/01_compliance_controls.sql` — re-runnable, deletes
T001 rows and re-inserts. Schema: `db/schema/02_core_tables.sql`
(`compliance_controls`) protected by Oracle Label Security
(`db/schema/01_tenants_and_security.sql`, `DICE_POLICY`). Every per-tenant
SELECT is brokered via `DBMS_SESSION.SET_IDENTIFIER` so OLS evaluates the
correct row labels server-side.

Each row carries: `control_id` (RAW(16) GUID cast to VARCHAR2(36)),
`framework`, `code` (e.g. `NIS2-01`), `title`, `description` (article cite),
`tenant_id`, `ols_label` (30=R, 50=C).

## 2. Live OCI posture checks

`services/compliance/app/routers/live_checks.py` (mounted under
`/api/compliance/live/`) exposes four read-only probes:

| Endpoint | Source | Cost | Returns |
|---|---|---|---|
| `GET /live/cloud-guard` | OCI Cloud Guard ListProblems (lifecycle=ACTIVE, subtree=true) | 1-2 SDK calls | `open_problems`, `high_risk` |
| `GET /live/adb-encryption` | OCI Database ListAutonomousDatabases | 1 SDK call | `adb_count`, `encrypted_count`, `compliant` |
| `GET /live/bucket-public-access` | Object Storage ListBuckets + GetBucket per item | 1 + N | `bucket_count`, `public_count`, `compliant` |
| `GET /live/ols-status` | DB query `dba_sa_table_policies` (fallback `user_sa_*`) | 1 SQL | `policy_name`, `applied_to_tables`, `active` |

The first three use `oci.auth.signers.InstancePrincipalsSecurityTokenSigner`.
The fourth is a pure DB query (always available).

## 3. Per-framework score formula

For each of the four frameworks, the aggregate score is computed by
`GET /api/compliance/score`:

```
score = (implemented / total) * 100 - live_penalty
live_penalty = min(open_cloud_guard_problems * 5, 25)
```

Where:

- `total` = count of controls in `compliance_controls` for the tenant in
  that framework (12 / 8 / 6 / 5 for NIS2 / DORA / GDPR / VSNFD).
- `implemented` = count of controls whose most-recent
  `compliance_findings.status` is in `('mitigated','accepted',
  'false_positive','closed')`. Controls without findings count as
  not-implemented.
- `live_penalty` is derived from `/live/cloud-guard.open_problems`.
  Capped at 25 so a flood of MINOR problems cannot drive the score
  negative.

Score floor is 0 (clamped); ceiling is 100.

## 4. Refresh cadence

| Metric | Refresh interval | Rationale |
|---|---|---|
| `/api/compliance/score` | 30 s | Fast metric — drives the score tiles. |
| `/api/compliance/live/cloud-guard` | 30 s | Cheap SDK call; user-visible. |
| `/api/compliance/live/ols-status` | 30 s | Pure DB query; no SDK cost. |
| `/api/compliance/live/adb-encryption` | 5 min | Slow SDK call; rarely changes. |
| `/api/compliance/live/bucket-public-access` | 5 min | Slow SDK call; rarely changes. |
| `/api/compliance/controls/{framework}` | On filter change | List view is user-driven, not polled. |

The frontend uses TanStack Query `staleTime` + `refetchInterval` to drive the
two cadences (see `frontend/src/views/ComplianceView.tsx`).

## 5. Degradation path (no IMDS on virtual nodes)

OKE virtual nodes do **not** expose the instance metadata service (IMDS), so
`InstancePrincipalsSecurityTokenSigner()` cannot mint a token. Each of the
three SDK-backed probes wraps construction + call in a try/except. On any
failure the response is the **degraded payload**:

```json
{
  "open_problems": -1,
  "high_risk": -1,
  "as_of": "2026-04-27T08:30:00+00:00",
  "error": "instance_principal_unavailable"
}
```

The frontend treats `error: "instance_principal_unavailable"` as a sentinel:
it renders the metric as `—` (em-dash), keeps the previous score tile, and
shows a yellow banner. The score formula falls back to
`live_penalty = 0` so the catalogue-only score still renders.

`/live/ols-status` never degrades because it is pure-DB.

## 6. Authoritative endpoint table

| Method | Path | Refresh | Source |
|---|---|---|---|
| GET | `/api/compliance/controls/{framework}` | on demand | DB: `compliance_controls` |
| GET | `/api/compliance/score` | 30 s | DB: `compliance_controls` x `compliance_findings` |
| GET | `/api/compliance/dora/open` | 30 s | DB: `dora_incidents WHERE rto IS NULL` |
| GET | `/api/compliance/collab-shares` | on demand | DB: `collab_shares` |
| GET | `/api/compliance/live/cloud-guard` | 30 s | OCI SDK: Cloud Guard ListProblems |
| GET | `/api/compliance/live/adb-encryption` | 5 min | OCI SDK: Database ListAutonomousDatabases |
| GET | `/api/compliance/live/bucket-public-access` | 5 min | OCI SDK: ObjectStorage ListBuckets + GetBucket |
| GET | `/api/compliance/live/ols-status` | 30 s | DB: `dba_sa_table_policies` (fallback `user_sa_*`) |

All endpoints honour the `X-Tenant-Id` header (default `T001`) and propagate
the tenant via `DBMS_SESSION.SET_IDENTIFIER` on every connection acquired
from the pool.

## 7. Data flow

```
+---------+         +----------+        +----------------------+
| Browser |         | Ingress  |        | compliance pod       |
| React   |  HTTPS  | (OCI LB  |  HTTP  | (FastAPI :8005)      |
| Compli- | ------> |  TLS 1.3)| -----> | routers:             |
| anceVw  |         |          |        |   compliance.py      |
+---------+         +----------+        |   live_checks.py     |
                                        +----------+-----------+
                                                   |
                              +--------------------+--------------------+
                              |                                         |
                       +------v------+                          +-------v-------+
                       | DB query    |                          | OCI SDK call  |
                       | oracledb -> |                          | InstPrincipal |
                       | ATP sovdef26|                          | (CG / DB / OS)|
                       +-------------+                          +---------------+
                              |                                         |
                       +------v------+                          +-------v-------+
                       | OLS         |                          | Cloud Guard,  |
                       | DICE_POLICY |                          | ADB, Buckets  |
                       +-------------+                          +---------------+
```

Frontend → ingress → pod → DB *or* OCI SDK. The two outbound paths are
independent: a DB outage does not block live checks; an OCI SDK outage does
not block catalogue reads (the score formula falls back to `live_penalty=0`).

## 8. Cross-references

- DB schema: `db/schema/02_core_tables.sql`,
  `db/schema/07_audit_compliance.sql`, `db/seed/01_compliance_controls.sql`
- Backend: `services/compliance/app/main.py`,
  `services/compliance/app/routers/compliance.py`,
  `services/compliance/app/routers/live_checks.py`
- Frontend: `frontend/src/views/ComplianceView.tsx`,
  `frontend/src/services/api.ts`, `frontend/src/types/index.ts`
- IAM: `docs/cloud-guard-iam.md`
- Posture: `docs/security-zone-overview.md`,
  `docs/security-controls-matrix.md`
- Posture activation: `scripts/activate-cloud-guard.sh`,
  `scripts/create-security-zone.sh`

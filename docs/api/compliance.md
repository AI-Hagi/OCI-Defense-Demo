# Compliance API

Source: `services/compliance/app/routers/{compliance,live_checks}.py`.
Use case 6 ("Compliance Automation — NIS2/DORA/GDPR/VS-NfD") per
`CLAUDE_DEV9.md`.

## DB-backed scorecard

### `GET /api/compliance/score`

Aggregate score per framework based on `compliance_findings.status`.

Response `200 OK`:

```json
[
  { "framework": "NIS2",  "implemented": 9,  "total": 12, "score_pct": 75.0 },
  { "framework": "DORA",  "implemented": 5,  "total": 8,  "score_pct": 62.5 },
  { "framework": "GDPR",  "implemented": 5,  "total": 6,  "score_pct": 83.33 },
  { "framework": "VSNFD", "implemented": 4,  "total": 5,  "score_pct": 80.0 }
]
```

Frameworks are seeded by `db/seed/01_compliance_controls.sql` (31
controls — NIS2:12 / DORA:8 / GDPR:6 / VS-NfD:5).

### `GET /api/compliance/controls/{framework}`

List controls for a single framework, ordered by `code`. `framework`
must be one of `NIS2 | DORA | GDPR | VSNFD`.

Response `200 OK`:

```json
[
  {
    "control_id": "...",
    "code": "NIS2-01",
    "title": "Risikomanagement-Konzept (Art. 21 Abs. 2 lit. a)",
    "description": "Etablierung und Pflege eines dokumentierten ...",
    "tenant_id": "T001"
  }
]
```

The `framework` field is omitted from the row payload because the
path already scopes the request — frontend `ComplianceView`
re-tags rows from the path.

### `GET /api/compliance/dora/open`

Return the subset of DORA controls whose latest finding is **not**
in `(mitigated, closed)`.

### `GET /api/compliance/collab-shares`

Cross-tenant artefact shares visible to the calling tenant
(filtered by OLS).

---

## Live OCI tiles

Each tile probes IMDS first (`live_checks._imds_reachable`, 1s
socket connect to `169.254.169.254:80`). On OKE virtual nodes IMDS
is **not** exposed, so each tile returns `200 OK` with a degraded
payload in <1s instead of hanging the SDK signer for ~60s.

### `GET /api/compliance/live/cloud-guard`

```json
{
  "open_problems": 4, "high_risk": 1,
  "as_of": "2026-04-27T08:00:00+00:00"
}
```

Degraded:

```json
{
  "open_problems": -1, "high_risk": -1,
  "as_of": "2026-04-27T08:00:00+00:00",
  "error": "instance_principal_unavailable"
}
```

### `GET /api/compliance/live/adb-encryption`

```json
{
  "adb_count": 3, "encrypted_count": 3, "compliant": true,
  "as_of": "..."
}
```

### `GET /api/compliance/live/bucket-public-access`

```json
{
  "bucket_count": 12, "public_count": 0, "compliant": true,
  "as_of": "..."
}
```

### `GET /api/compliance/live/ols-status`

Pure DB query — no IMDS gate.

```json
{
  "policy_name": "DICE_POLICY",
  "applied_to_tables": 7, "active": true,
  "as_of": "..."
}
```

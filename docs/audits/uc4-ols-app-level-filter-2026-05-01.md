# UC4_OSINT — App-Level OLS Filter (Path C, ships today)

**Date:** 2026-05-01
**Branch:** `feat/sovdefence-app-swarm`
**Decision:** Implement application-layer classification filtering for
UC4_OSINT instead of native Oracle Label Security, until ATP-Shared
unblocks customer-side OLS administration.
**Status:** **Live** on the sovdef26 ATP. End-to-end roundtrip tested.

## Why we're not using native OLS

Native OLS is the preferred mechanism. The blocker is concrete:

- LBAC option in `v$option`: `TRUE` (engine installed)
- ADMIN holds `LBAC_DBA` role with `DEFAULT_ROLE=YES, ADMIN_OPTION=YES`
- All `SA_*` admin packages compile valid

…and yet:

```
SQL> EXEC SA_SYSDBA.CREATE_POLICY('OLS_DEFENCE','OLS_LABEL','LABEL_DEFAULT,NO_CONTROL');
ORA-42911: cannot administer Oracle Label Security policy
   at LBACSYS.LBAC_LGSTNDBY_UTIL line 118
   at LBACSYS.SA_SYSDBA      line  23
```

Per Oracle's ATP documentation, ATP-Shared (the standard tier) gates
customer-side OLS *administration* through the cloud control plane —
the engine runs but `CREATE_POLICY` / `APPLY_TABLE_POLICY` are blocked.
Three unblock paths exist:

1. Open an Oracle Service Request to enable OLS administration on this
   tenancy (lowest effort, ~1–3 business days)
2. Migrate to ATP-Dedicated (full OLS admin out of the box; non-trivial
   cost step-up)
3. App-level filtering — what this document describes

Path 3 was chosen because the demo timeline doesn't tolerate the lead
time of paths 1/2, and because the eventual unblock can run *alongside*
the app-level filter as defence in depth — they reinforce, not compete.

## What ships

### Database side — `db/schema/uc4_osint/03b_ols_app_filter.sql`

| Object | Type | Purpose |
|---|---|---|
| `UC4_OSINT_OLS_CTX` | Application Context | Session-scoped namespace, writable only via the trusted package |
| `UC4_OSINT.OLS_CTX_PKG` | PL/SQL Package | `set_label_cap(p)` / `clear_label_cap` / `get_label_cap` — clamps GEHEIM(70)→NFD(50), fails-safe to OFFEN(10) |
| `UC4_OSINT.LABEL_CAP()` | Stand-alone Function | Read-only convenience for `WHERE ols_label <= UC4_OSINT.label_cap()` — `PARALLEL_ENABLE`, fails-safe to 10 |

Grants:

- `EXECUTE ON UC4_OSINT.LABEL_CAP TO PUBLIC` — read-only, harmless
- `EXECUTE ON UC4_OSINT.OLS_CTX_PKG TO uc4_audit_appender` — write-side
  scoped; future UC4 service-roles will be added on demand

### Service side — `services/osint-fusion/app/ols.py`

| Symbol | Purpose |
|---|---|
| `LabelCap(IntEnum)` | OFFEN=10 / INTERN=30 / NFD=50 / GEHEIM=70 |
| `parse_label_cap(value)` | Header → numeric cap; never raises |
| `label_cap_dependency` | FastAPI `Header(alias='X-OLS-Label-Max')` dependency |
| `apply_session_label_cap(conn, cap)` | Push cap into DB session context |
| `clear_session_label_cap(conn)` | Connection-release helper |
| `label_filter_clause(table_alias='')` | Returns `' AND <alias>ols_label <= UC4_OSINT.label_cap()'` |

### Tests — `services/osint-fusion/tests/test_ols.py`

30 unit tests covering:

- Happy-path values (10/30/50 as both `int` and `str`)
- GEHEIM(70) silent clamp to NFD(50)
- Fail-safe to OFFEN(10) on missing / empty / non-numeric / out-of-range
  / wrong type / negative inputs
- `apply_session_label_cap` calls `OLS_CTX_PKG.SET_LABEL_CAP` with an
  integer bind
- `clear_session_label_cap` calls `OLS_CTX_PKG.CLEAR_LABEL_CAP`
- `label_filter_clause` SQL fragment shape (with and without alias)

```
$ python3 -m pytest tests/test_ols.py -v
============================== 30 passed in 0.27s ==============================
```

### End-to-end DB validation against live ATP

```
Step 2: cap unset → failsafe OFFEN(10)        →  1 row     (public)
Step 3: cap = 30 (INTERN)                      →  2 rows    (public, restricted)
Step 4: cap = 50 (NFD)                         →  3 rows    (public, restricted, nfd)
Step 5: cap = 70 (GEHEIM) clamped to 50        →  3 rows + effective_cap = 50
Step 6: cleanup                                →  3 rows deleted
```

## Threat model — the gap relative to native OLS

### What's covered

- **Application-tier reads**: every UC4 router calls
  `apply_session_label_cap` on connection-acquire and either uses
  `label_filter_clause()` or pre-canned views that bake the predicate in.
- **Header tampering**: `parse_label_cap` rejects garbage inputs and
  GEHEIM-clamps; `OLS_CTX_PKG.set_label_cap` re-validates and re-clamps
  in the DB so a malicious in-process call passing `70` directly still
  ends up with `50`.
- **Default deny**: missing header → OFFEN → empty result for any row
  classified above OFFEN. No information disclosure on misconfig.
- **Audit chain**: every classified read is logged via
  `audit_trail` (see `03_security.sql`). Operators can detect *which
  cap a query ran with* by joining `audit_trail.invocation_id` with the
  upstream chat-tool / agent trace.

### What's NOT covered (explicit gaps)

1. **DBA bypass.** A user holding `SELECT ANY TABLE` (or any direct
   `SELECT` privilege on `UC4_OSINT.signal_normalized`) can issue raw
   SQL without the WHERE clause and see every row. Native OLS would
   filter this transparently. Mitigation today: limit DBA-level access
   to ADMIN, audit ADMIN-issued `SELECT` against UC4_OSINT tables,
   review weekly.
2. **Service-code bypass.** A future UC4 service that forgets to call
   `apply_session_label_cap` runs every query at the failsafe OFFEN
   level (so no leak), but if it forgets the WHERE clause entirely it
   leaks. Mitigation: code review enforces `label_filter_clause()` on
   every read; integration tests assert that a request without the
   header returns only OFFEN rows.
3. **Cap-circumvention via UNION/CTAS.** A querier who can write SQL
   could do `INSERT INTO scratch SELECT * FROM signal_normalized` and
   then read `scratch` without the cap. Native OLS would label-tag
   `scratch` rows on copy. Mitigation: revoke `CREATE TABLE` from
   service users; only the schema-owner UC4_OSINT can DDL.
4. **Time-of-check/time-of-use.** A long-running query started at
   cap=10 will see rows that became cap=50 later. Native OLS uses
   row-level metadata so it's atomic; the app-layer filter is
   query-snapshot-only. Mitigation: classification labels are
   append-only in practice (you don't *demote* rows), so this is
   theoretical.

These gaps are accepted explicitly until OLS is unblocked. Compliance
audits should mark UC4 as "Path C — app-level filter, native OLS
pending" until the SR / ATP-Dedicated migration completes.

## Roll-forward when native OLS unlocks

A future `db/schema/uc4_osint/03c_ols_native.sql` will:

1. Run the full `SA_SYSDBA.CREATE_POLICY` / `SA_COMPONENTS.CREATE_LEVEL`
   / `SA_COMPONENTS.CREATE_COMPARTMENT` sequence we drafted then
   discarded
2. `SA_POLICY_ADMIN.APPLY_TABLE_POLICY('OLS_DEFENCE', 'UC4_OSINT', ...)`
   on the 9 UC4 tables
3. `SA_USER_ADMIN.SET_USER_LABELS` for the demo personas
   (`OBERST_WEBER`, `HAUPTMANN_LANGE`, `M_SCHMIDT`)

The app-layer filter from this document **stays in place** as
defence-in-depth. Both filters being satisfied simultaneously is the
correct semantic — they're the same predicate evaluated at two layers.
Tests for `services/osint-fusion/tests/test_ols.py` continue to pass
unchanged.

## Reproducibility

All four artefacts of this change can be re-applied on a fresh ATP:

```bash
# 1. DB infrastructure
ADMIN_PWD=$(oci secrets secret-bundle get \
  --secret-id "$ATP_ADMIN_SECRET" --auth instance_principal \
  --query 'data."secret-bundle-content".content' --raw-output | base64 -d)
ADB_ADMIN_PASSWORD="$ADMIN_PWD" \
  bash scripts/apply-migration.sh db/schema/uc4_osint/03b_ols_app_filter.sql

# 2. Python tests
cd services/osint-fusion && python3 -m pytest tests/test_ols.py -v

# 3. End-to-end DB roundtrip is in this document, "Step 1–6" — paste
#    into sqlcl as UC4_OSINT to re-verify after future schema changes.
```

---

**Owner of follow-up:** the OLS unblocker SR / ATP-Dedicated migration
sits on the platform-security backlog. Until it lands, this app-layer
filter is the *enforceable* classification model for UC4 reads.

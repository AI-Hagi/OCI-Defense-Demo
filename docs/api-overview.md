# Sovereign Defence Intelligence Platform — API Overview

Gemeinsame Regeln, Header-Konventionen und Fehlermodell fuer alle 5 FastAPI-Services. Jeder Service publiziert zusaetzlich seine eigene OpenAPI-Spezifikation unter `/openapi.json`; dieses Dokument fasst die gemeinsamen Invarianten zusammen.

## Architektur

```
  +--------------------------------------------------------------+
  |                     Frontend (React, OKE)                    |
  |    GeoIntView   DocIntelView   OsintView   SupplyChainView   |
  |    ComplianceView                        (6 Views total)     |
  +------+------+-----------+-----------+-----------+------------+
         |      |           |           |           |
         v      v           v           v           v
   +---------+ +----------+ +--------+ +--------+ +-----------+
   | GEOINT  | | Doc Intel | | OSINT  | | Supply | | Compliance|
   | :8001   | | :8002     | | :8003  | | :8004  | | :8005     |
   +----+----+ +-----+-----+ +---+----+ +---+----+ +-----+-----+
        |            |            |          |            |
        +------------+------------+----------+------------+
                                |
                                v
                 +------------------------------+
                 | Oracle 26ai ADB (sovdef26_tp)|
                 | Spatial | Vector | Graph     |
                 | Blockchain | Label Security  |
                 +------------------------------+
```

All services run in OKE (EU-Frankfurt / EU-Amsterdam). Database access uses the Oracle wallet mounted at `TNS_ADMIN` with the `sovdef26_tp` TNS alias. ORDS exposes selected Duality Views and procedures via REST (see `db/schema/08_ords_endpoints.sql`).

## Frontend -> Service matrix

| Frontend view        | Primary service      | Secondary services                  | Key endpoints                                                                       |
|----------------------|----------------------|-------------------------------------|--------------------------------------------------------------------------------------|
| `GeointView`         | `geoint`             | `osint-fusion` (enrichment)         | `GET /api/geoint/scenes`, `POST /api/geoint/scenes/{id}/detect`                     |
| `DocIntelView`       | `doc-intelligence`   | `compliance` (policy docs)          | `POST /api/documents/search`, `POST /api/documents/rag`                              |
| `OsintView`          | `osint-fusion`       | `geoint`, `supply-chain`            | `GET /api/osint/entities`, `POST /api/osint/threats/correlate`                       |
| `SupplyChainView`    | `supply-chain`       | `compliance` (NIS2 supply reporting)| `GET /api/sc/risk/{product_id}`, `GET /api/sc/risk/chokepoints`                      |
| `ComplianceView`     | `compliance`         | all four others                     | `GET /api/compliance/controls`, `POST /api/compliance/reports`                       |
| `CollaborationView`  | `compliance`         | `doc-intelligence`, `osint-fusion`  | Aggregates multi-tenant assessments and cross-tenant document shares via OLS         |

## Common HTTP headers

| Header           | Required | Purpose                                                                |
|------------------|----------|-------------------------------------------------------------------------|
| `X-Tenant-Id`    | **yes**  | Mandant-ID (e.g. `T001`). Binds Oracle Label Security session label.    |
| `X-Request-ID`   | no       | Opaque UUID forwarded to DB and log context. Generated server-side if absent. |
| `Accept`         | no       | `application/json` default.                                             |
| `Content-Type`   | POST/PUT | `application/json` except explicit multipart upload endpoints.          |

### Tenant-binding behaviour

- The first operation in every request is `DBMS_SESSION.SET_CONTEXT` / `SA_SESSION.SET_LABEL` using `X-Tenant-Id`.
- Requests without `X-Tenant-Id` are rejected with `HTTP 400` (`error.code = "TENANT_HEADER_MISSING"`).
- Unknown tenant IDs are rejected with `HTTP 403` (`error.code = "TENANT_NOT_FOUND"`).
- Tenant-to-label mapping is held in `ADMIN.TENANT_OLS_MAP` and loaded into a short-TTL in-process cache.

### OLS caveat on ADB-S

Oracle Autonomous Database Serverless does **not** currently support label-column enforcement at SQL layer for cross-schema queries. The platform therefore enforces labels at the **row** level via policies applied per schema. Cross-tenant joins must go through ORDS endpoints (priv.intel / priv.compliance) which materialise filtered views — see `db/schema/08_ords_endpoints.sql`.

## Unified error model

All services return the same JSON body on 4xx/5xx:

```json
{
  "error": {
    "code": "TENANT_HEADER_MISSING",
    "message": "X-Tenant-Id header is required on every request.",
    "request_id": "8f2e1c2a-39b0-4d3c-b3a5-6b2b7b4a12e0"
  }
}
```

### Canonical error codes

| HTTP | code                    | When                                                     |
|------|--------------------------|----------------------------------------------------------|
| 400  | `TENANT_HEADER_MISSING`  | `X-Tenant-Id` absent or empty                            |
| 400  | `VALIDATION_ERROR`       | Pydantic validation failed (`details` holds field list)  |
| 401  | `UNAUTHORIZED`           | No/invalid auth (post-MVP, once OAuth2 is on)            |
| 403  | `TENANT_NOT_FOUND`       | Tenant-ID unknown                                        |
| 403  | `LABEL_FORBIDDEN`        | OLS denied access to the requested resource              |
| 404  | `NOT_FOUND`              | Resource does not exist within the tenant scope          |
| 409  | `CONFLICT`               | State conflict (e.g. duplicate key, concurrent write)    |
| 429  | `RATE_LIMITED`           | Rate limit exceeded                                      |
| 500  | `INTERNAL_ERROR`         | Unhandled server error; `request_id` used for log lookup |
| 503  | `UPSTREAM_UNAVAILABLE`   | Oracle 26ai / Object Storage / Gen-AI temporarily down   |

## Authentication roadmap

**MVP (today):** header-based tenant trust. `X-Tenant-Id` is trusted because the ingress in front of the services authenticates the caller (OKE Ingress + mTLS in prod, none in dev). Do **not** expose these services publicly without that ingress.

**Next step:** OAuth2 client credentials brokered by ORDS. The client obtains an access token from `/ords/priv/intel/oauth/token` (role `intel_user`) or `/ords/priv/compliance/oauth/token` (role `compliance_user`); the token is introspected by a FastAPI dependency that also resolves the tenant binding. See `db/schema/08_ords_endpoints.sql` for the ORDS OAuth2 client and role definitions.

## Rate limits

Per tenant, per service:

| Endpoint class                         | Budget                  |
|----------------------------------------|--------------------------|
| Read (`GET`)                           | 600 req/min             |
| Write (`POST`/`PUT`/`PATCH`/`DELETE`)  | 120 req/min             |
| Vector / graph search                  | 60 req/min              |
| RAG generation                         | 20 req/min              |

Exceeded budgets return `HTTP 429` with `Retry-After` seconds. Rate limit counters are held in-process for dev and migrate to Oracle 26ai TxEventQ for prod.

## Pagination conventions

- Query params `limit` (default 50, max 200) and `cursor` (opaque base64).
- Responses include `next_cursor` (nullable) and `total_estimate` (integer).
- All vector and graph queries **must** cap results with `FETCH APPROX FIRST :k ROWS ONLY` (Oracle 26ai approximate fetch clause) to keep the DiskANN/PGQL planner efficient.
- `k` defaults to 10 and is capped at 100 at the service layer.

## Deterministic timestamps

All timestamps are `TIMESTAMP WITH TIME ZONE` in UTC, serialised as RFC 3339 (`2026-04-23T14:30:12.123Z`). Clients must not assume local time.

## Versioning

- Service version is exposed in `app.version` (currently `0.1.0`) and surfaced in OpenAPI `info.version`.
- Breaking changes bump minor until 1.0.0, then major thereafter.
- Clients should pin the server version in monitoring and fail soft on unknown fields.

## OpenAPI aggregation

The script `scripts/dump-openapi.sh` hits each running service's `/openapi.json` and writes the spec to `docs/openapi/<service>.json` for diffing and SDK generation.

```bash
chmod +x scripts/dump-openapi.sh
./scripts/dump-openapi.sh
```

## References

- ORDS REST endpoints: `db/schema/08_ords_endpoints.sql`
- Per-service README: `services/<name>/README.md`
- OpenAPI customiser: `services/<name>/app/openapi.py`
- Frontend view catalogue: `frontend/src/views/`

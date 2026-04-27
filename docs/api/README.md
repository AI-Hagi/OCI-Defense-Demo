# API reference

One file per backend service. Each lists the endpoints exposed
through the OCI Native Ingress LB at `http://152.70.18.236`.

| Service | Prefix | File |
|---|---|---|
| GEOINT | `/api/geoint` | [geoint.md](./geoint.md) |
| Document Intelligence (RAG) | `/api/documents` | [documents.md](./documents.md) |
| OSINT Fusion | `/api/osint` | [osint.md](./osint.md) |
| Supply Chain | `/api/sc` | [supply-chain.md](./supply-chain.md) |
| Compliance | `/api/compliance` | [compliance.md](./compliance.md) |

Common header contract (every endpoint):

| Header | Default | Effect |
|---|---|---|
| `X-Tenant-Id` | `T001` | Bound to `DBMS_SESSION.SET_IDENTIFIER` so OLS row filtering applies. Valid demo IDs: `T001`, `T002`, `T003`. |
| `Content-Type` | per route | `application/json` for all reads; `multipart/form-data` for `/api/geoint/scenes/upload`. |

Internal `/health` endpoints are pod-local and used by the kubelet
liveness/readiness probes — they are *not* reachable through the LB.

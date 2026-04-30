# Supply Chain Service

FastAPI-Microservice fuer den Lieferketten-Knowledge-Graph: Lieferanten, Komponenten, BoMs und Risiko-Scoring ueber Oracle 26ai Property Graph. Teil der Sovereign Defence Intelligence Platform (Use Case 5). Base path: `/api/sc`, Port `8004`.

## Endpoints

| Method | Path                                    | Description                                | Auth        | Tenant-scoped |
|--------|-----------------------------------------|--------------------------------------------|-------------|---------------|
| GET    | `/api/sc/suppliers`                     | List suppliers (filter by jurisdiction)    | X-Tenant-Id | yes           |
| POST   | `/api/sc/suppliers`                     | Register a supplier                        | X-Tenant-Id | yes           |
| GET    | `/api/sc/suppliers/{supplier_id}`       | Supplier detail + sanctions flag           | X-Tenant-Id | yes           |
| GET    | `/api/sc/components`                    | List components                            | X-Tenant-Id | yes           |
| GET    | `/api/sc/components/{component_id}/bom` | Full bill-of-material tree                 | X-Tenant-Id | yes           |
| POST   | `/api/sc/graph/query`                   | Execute parameterised PGQL query           | X-Tenant-Id | yes           |
| GET    | `/api/sc/risk/{product_id}`             | Risk score for a product (multi-hop)       | X-Tenant-Id | yes           |
| GET    | `/api/sc/risk/chokepoints`              | Detect single-source chokepoints           | X-Tenant-Id | yes           |
| GET    | `/api/sc/health`                        | Liveness probe                             | none        | no            |
| GET    | `/api/sc/health/ready`                  | Readiness probe                            | none        | no            |

## Environment

| Variable                 | Default          | Purpose                              |
|--------------------------|------------------|--------------------------------------|
| `ORACLE_USER`            | —                | DB user (e.g. `admin`)               |
| `ORACLE_PASSWORD`        | —                | DB password                          |
| `ORACLE_CONNECT_STRING`  | `sovdef26_tp`    | TNS alias in wallet                  |
| `TNS_ADMIN`              | `/home/ubuntu/wallet` | Wallet directory                |
| `WALLET_PASSWORD`        | —                | Wallet password                      |

## Local development

```bash
export TNS_ADMIN=/home/ubuntu/wallet
export ORACLE_USER=admin
export ORACLE_PASSWORD='...'
export ORACLE_CONNECT_STRING=sovdef26_tp
export WALLET_PASSWORD='...'
uvicorn app.main:app --reload --port 8004
```

## Curl examples

List suppliers in a sanctioned jurisdiction:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     'http://localhost:8004/api/sc/suppliers?jurisdiction=RU&limit=50'
```

Full BoM tree for a component:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     'http://localhost:8004/api/sc/components/CMP-4711/bom?depth=4'
```

Risk score for a product:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     'http://localhost:8004/api/sc/risk/PRD-LEOPARD-A8'
```

## Docs

- Swagger UI: <http://localhost:8004/docs>
- ReDoc:      <http://localhost:8004/redoc>
- Raw spec:   <http://localhost:8004/openapi.json>

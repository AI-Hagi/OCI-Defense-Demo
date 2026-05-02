# OSINT & Threat Fusion Service

FastAPI-Microservice fuer OSINT-Aggregation und Graph-basierte Threat Fusion auf Oracle 26ai. Sammelt Quellen, extrahiert Entitaeten, fuehrt PGQL-Traversals aus und fusioniert Signale mit GEOINT und Supply Chain. Teil der Sovereign Defence Intelligence Platform (Use Case 4). Base path: `/api/osint`, Port `8003`.

## Endpoints

| Method | Path                                    | Description                                 | Auth        | Tenant-scoped |
|--------|-----------------------------------------|---------------------------------------------|-------------|---------------|
| GET    | `/api/osint/sources`                    | List registered OSINT sources               | X-Tenant-Id | yes           |
| POST   | `/api/osint/sources`                    | Register a new source                       | X-Tenant-Id | yes           |
| GET    | `/api/osint/entities`                   | Query entities (type, text, time window)    | X-Tenant-Id | yes           |
| GET    | `/api/osint/entities/{entity_id}`       | Entity detail with mentions                 | X-Tenant-Id | yes           |
| POST   | `/api/osint/graph/query`                | Execute parameterised PGQL query            | X-Tenant-Id | yes           |
| GET    | `/api/osint/graph/neighbours`           | K-hop neighbourhood of an entity            | X-Tenant-Id | yes           |
| GET    | `/api/osint/threats`                    | Fused threat indicators                     | X-Tenant-Id | yes           |
| POST   | `/api/osint/threats/correlate`          | Correlate entity with GEOINT / supply chain | X-Tenant-Id | yes           |
| GET    | `/api/osint/health`                     | Liveness probe                              | none        | no            |
| GET    | `/api/osint/health/ready`               | Readiness probe                             | none        | no            |

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
uvicorn app.main:app --reload --port 8003
```

## Curl examples

List entities matching a term:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     'http://localhost:8003/api/osint/entities?q=Kaliningrad&type=LOCATION&limit=25'
```

K-hop neighbourhood lookup:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     'http://localhost:8003/api/osint/graph/neighbours?entity_id=ENT-0917&hops=2'
```

Correlate an OSINT entity with GEOINT detections:
```bash
curl -sS -X POST \
     -H 'X-Tenant-Id: T001' \
     -H 'Content-Type: application/json' \
     -d '{"entity_id":"ENT-0917","window_days":7}' \
     http://localhost:8003/api/osint/threats/correlate
```

## Docs

- Swagger UI: <http://localhost:8003/docs>
- ReDoc:      <http://localhost:8003/redoc>
- Raw spec:   <http://localhost:8003/openapi.json>

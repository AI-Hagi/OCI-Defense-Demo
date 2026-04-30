# GEOINT Service

FastAPI-Microservice fuer satellitengestuetzte Aufklaerung: verwaltet Szenen, fuehrt YOLOv8-Detektion aus und indiziert Objekte als Vektor-Embeddings in Oracle 26ai. Teil der Sovereign Defence Intelligence Platform (Use Case 1). Base path: `/api/geoint`, Port `8001`.

## Endpoints

| Method | Path                                    | Description                                      | Auth        | Tenant-scoped |
|--------|-----------------------------------------|--------------------------------------------------|-------------|---------------|
| GET    | `/api/geoint/scenes`                    | List uploaded scenes (paginated)                 | X-Tenant-Id | yes           |
| POST   | `/api/geoint/scenes`                    | Register new scene (metadata + Object-Store URL) | X-Tenant-Id | yes           |
| GET    | `/api/geoint/scenes/{scene_id}`         | Scene detail incl. footprint polygon             | X-Tenant-Id | yes           |
| POST   | `/api/geoint/scenes/{scene_id}/detect`  | Trigger YOLOv8 inference, persist detections     | X-Tenant-Id | yes           |
| GET    | `/api/geoint/detections`                | Query detections by bbox/class/confidence        | X-Tenant-Id | yes           |
| POST   | `/api/geoint/detections/similar`        | Vector-similarity search (COSINE, DiskANN)       | X-Tenant-Id | yes           |
| GET    | `/api/geoint/health`                    | Liveness probe                                   | none        | no            |
| GET    | `/api/geoint/health/ready`              | Readiness probe (DB + object store)              | none        | no            |

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
uvicorn app.main:app --reload --port 8001
```

## Curl examples

List scenes:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     http://localhost:8001/api/geoint/scenes?limit=10
```

Trigger detection on a scene:
```bash
curl -sS -X POST \
     -H 'X-Tenant-Id: T001' \
     -H 'Content-Type: application/json' \
     -d '{"model":"yolov8n","conf":0.35}' \
     http://localhost:8001/api/geoint/scenes/SCENE-0042/detect
```

Vector similarity search:
```bash
curl -sS -X POST \
     -H 'X-Tenant-Id: T001' \
     -H 'Content-Type: application/json' \
     -d '{"detection_id":"DET-0001","k":5}' \
     http://localhost:8001/api/geoint/detections/similar
```

## Docs

- Swagger UI: <http://localhost:8001/docs>
- ReDoc:      <http://localhost:8001/redoc>
- Raw spec:   <http://localhost:8001/openapi.json>

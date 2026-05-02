# Compliance Service

FastAPI-Microservice fuer Compliance-Automatisierung: Kontroll-Katalog, Nachweise (Blockchain-Tables), Audit-Runs und Berichte fuer NIS2, DORA, GDPR und VS-NfD. Teil der Sovereign Defence Intelligence Platform (Use Case 6). Base path: `/api/compliance`, Port `8005`.

## Endpoints

| Method | Path                                           | Description                          | Auth        | Tenant-scoped |
|--------|------------------------------------------------|--------------------------------------|-------------|---------------|
| GET    | `/api/compliance/controls`                     | List controls (filter by framework)  | X-Tenant-Id | yes           |
| GET    | `/api/compliance/controls/{control_id}`        | Control detail                       | X-Tenant-Id | yes           |
| GET    | `/api/compliance/evidence`                     | List evidence items                  | X-Tenant-Id | yes           |
| POST   | `/api/compliance/evidence`                     | Attach evidence to a control         | X-Tenant-Id | yes           |
| POST   | `/api/compliance/assessments`                  | Start assessment run                 | X-Tenant-Id | yes           |
| GET    | `/api/compliance/assessments/{assessment_id}`  | Assessment status + results          | X-Tenant-Id | yes           |
| POST   | `/api/compliance/reports`                      | Generate regulatory report (PDF/JSON)| X-Tenant-Id | yes           |
| GET    | `/api/compliance/reports/{report_id}`          | Retrieve generated report            | X-Tenant-Id | yes           |
| GET    | `/api/compliance/health`                       | Liveness probe                       | none        | no            |
| GET    | `/api/compliance/health/ready`                 | Readiness probe                      | none        | no            |

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
uvicorn app.main:app --reload --port 8005
```

## Curl examples

List all NIS2 controls:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     'http://localhost:8005/api/compliance/controls?framework=NIS2&limit=100'
```

Start a new assessment:
```bash
curl -sS -X POST \
     -H 'X-Tenant-Id: T001' \
     -H 'Content-Type: application/json' \
     -d '{"framework":"DORA","scope":"ICT-Register","owner":"ciso@t001"}' \
     http://localhost:8005/api/compliance/assessments
```

Generate an NIS2 incident report:
```bash
curl -sS -X POST \
     -H 'X-Tenant-Id: T001' \
     -H 'Content-Type: application/json' \
     -d '{"template":"NIS2-Incident","incident_id":"INC-2026-0042","format":"pdf"}' \
     http://localhost:8005/api/compliance/reports
```

## Docs

- Swagger UI: <http://localhost:8005/docs>
- ReDoc:      <http://localhost:8005/redoc>
- Raw spec:   <http://localhost:8005/openapi.json>

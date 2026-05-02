# Document Intelligence Service

FastAPI-Microservice fuer RAG ueber klassifizierte Dokumente: Chunking, Embedding, hybride Suche und generative Antworten mit Quellenangabe — durchgehend OLS-gesichert. Teil der Sovereign Defence Intelligence Platform (Use Case 2). Base path: `/api/documents`, Port `8002`.

## Endpoints

| Method | Path                                       | Description                                | Auth        | Tenant-scoped |
|--------|--------------------------------------------|--------------------------------------------|-------------|---------------|
| GET    | `/api/documents`                           | List documents (paginated, label-filtered) | X-Tenant-Id | yes           |
| POST   | `/api/documents`                           | Register document (metadata + classification) | X-Tenant-Id | yes        |
| GET    | `/api/documents/{doc_id}`                  | Document detail                            | X-Tenant-Id | yes           |
| POST   | `/api/documents/{doc_id}/chunk`            | Trigger chunking + embedding pipeline      | X-Tenant-Id | yes           |
| GET    | `/api/documents/{doc_id}/chunks`           | List chunks of a document                  | X-Tenant-Id | yes           |
| POST   | `/api/documents/search`                    | Hybrid search (vector + keyword)           | X-Tenant-Id | yes           |
| POST   | `/api/documents/rag`                       | RAG answer with cited chunks               | X-Tenant-Id | yes           |
| GET    | `/api/documents/health`                    | Liveness probe                             | none        | no            |
| GET    | `/api/documents/health/ready`              | Readiness probe                            | none        | no            |

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
uvicorn app.main:app --reload --port 8002
```

## Curl examples

List documents:
```bash
curl -sS -H 'X-Tenant-Id: T001' \
     'http://localhost:8002/api/documents?limit=20&classification=VS-NfD'
```

Hybrid search:
```bash
curl -sS -X POST \
     -H 'X-Tenant-Id: T001' \
     -H 'Content-Type: application/json' \
     -d '{"q":"Lieferkette Halbleiter Sanktionen","k":8}' \
     http://localhost:8002/api/documents/search
```

RAG answer with citations:
```bash
curl -sS -X POST \
     -H 'X-Tenant-Id: T001' \
     -H 'Content-Type: application/json' \
     -d '{"question":"Welche NIS2-Meldepflichten gelten fuer Ruestungsbetriebe?","top_k":6}' \
     http://localhost:8002/api/documents/rag
```

## Docs

- Swagger UI: <http://localhost:8002/docs>
- ReDoc:      <http://localhost:8002/redoc>
- Raw spec:   <http://localhost:8002/openapi.json>

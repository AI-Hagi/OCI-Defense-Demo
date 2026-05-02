# AIS Multiplexer (Sovereign Proxy Pattern B)

FastAPI WebSocket fan-out service for maritime AIS data.

- **Upstream:** `wss://stream.aisstream.io/v0/stream` (free tier, API key from OCI Vault)
- **Downstream:** `/ws/maritime` — browser clients receive normalised JSON frames
- **Bbox:** Baltic default (53N..56N, 8E..22E), per-connection override via query params
- **Audit:** batched insert into `audit_events` every 50 frames or 10 s (whichever first)

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/healthz` | Liveness + DB-pool reachability — 200 ok / 503 degraded |
| GET | `/metrics` | Prometheus-style counters (`frames_received`, `frames_forwarded`, `audit_writes`, `upstream_reconnects`) |
| WS  | `/ws/maritime?bbox_s=&bbox_w=&bbox_n=&bbox_e=` | Subscribe to AIS frames, optional bbox override |

## Frame format (downstream)

```json
{
  "type": "ais_frame",
  "mmsi": 211281000,
  "lat": 54.123,
  "lon": 14.456,
  "heading_deg": 87.0,
  "speed_kn": 12.4,
  "vessel_name": "EXAMPLE",
  "classification": 100,
  "ts": "2026-04-28T14:00:00.000000+00:00"
}
```

`classification` follows the platform's Label Security scheme: 100 OPEN, 200 RESTRICTED,
300 CONFIDENTIAL, 400 SECRET. Public AIS is always 100.

## Running locally (with mock Vault)

```bash
cd services/ais-multiplexer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Set MOCK_VAULT_KEY in .env to a dummy value to bypass OCI Vault.
# Without it, the service will refuse to start (Vault read is mandatory in prod).
export $(grep -v '^#' .env | xargs)
export MOCK_VAULT_KEY=dummy-key-for-local-dev

uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Connect a browser test client:

```bash
# Default Baltic bbox
wscat -c ws://localhost:8001/ws/maritime

# Custom bbox (English Channel)
wscat -c "ws://localhost:8001/ws/maritime?bbox_s=49.5&bbox_w=-2.5&bbox_n=51.5&bbox_e=2.0"
```

## Production secrets

- AIS Stream API key: stored in OCI Vault, referenced by `VAULT_AIS_STREAM_KEY_OCID`.
- ATP wallet: mounted as Kubernetes Secret volume at `/app/wallet`.
- ATP credentials: injected via Kubernetes Secret env-vars (External Secrets Operator).
- Vault auth: Workload Identity (OKE pods) or Instance Principal (dev VM).

The service refuses to start if `VAULT_AIS_STREAM_KEY_OCID` is missing **and** `MOCK_VAULT_KEY`
is not set. There is no in-image fallback API key.

## Audit contract

Each batch flushes one row to `audit_events`:

| Column | Value |
|--------|-------|
| `actor_service` | `ais-multiplexer` |
| `action` | `ais_frame_batch` |
| `resource_type` | `vessel` |
| `resource_id` | `NULL` (batched — individual MMSIs are in `payload.mmsi_sample`) |
| `tenant_id` | from request header or `T001` default |
| `ols_label` | `100` (OPEN) |
| `payload` | `{"frame_count": N, "bbox": [...], "first_ts": "...", "last_ts": "..."}` |

`prev_hash` and `row_hash` are set by `trg_audit_events_hash` — the service does **not**
write them. See `db/schema/07_audit_compliance.sql`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

`db.py` and `vault.py` expose constructor-injected hooks for test doubles —
no real OCI / 26ai connection is required for unit tests.

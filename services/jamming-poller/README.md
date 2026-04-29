# GPS Jamming Poller — UC4 Sovereign Proxy Pattern A

Daily REST-poll of [gpsjam.org](https://gpsjam.org) → H3-hex polygon transform → classification → cache in Oracle 26ai. Browsers never reach gpsjam.org directly; the cached GeoJSON is served from `osint_cache` via `/api/osint/jamming/current`.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/healthz` | Liveness + DB pool reachable. 200 / 503. |
| `GET`  | `/metrics` | Prometheus-style counters. |
| `GET`  | `/api/osint/jamming/current` | GeoJSON FeatureCollection from cache. Optional `?bbox_s=&bbox_w=&bbox_n=&bbox_e=` filter. |

## Classification

| Ratio (low-NACp / total aircraft) | Class |
|-----------------------------------|-------|
| < 2 %   | green  |
| 2-10 %  | amber  |
| > 10 %  | red    |

Cells with fewer than 3 aircraft total are dropped as "noisy" before classification.

## Refresh schedule

APScheduler runs every `REFRESH_HOURS` (default 6 h). At each tick:

1. `httpx.get(GPSJAM_URL_TEMPLATE.format(date=today_utc))`
2. CSV → H3 cell records → polygon GeoJSON via `h3.cell_to_boundary` → classify → drop noisy cells
3. Persist as a single JSON blob into `osint_cache(layer='jamming', fetched_at, payload, classification, source)`
4. Write one `audit_events` row: `actor_service='jamming-poller'`, `action='layer_fetch'`, `resource_type='gpsjam.org/csv'`.

If the upstream CSV is 404 (gpsjam.org maintainer hasn't published yet) or 5xx, the existing cache row stays valid and the next tick retries.

## Local dev

```bash
cd services/jamming-poller
pip install -r requirements-dev.txt
ORACLE_USER=DICE_APP ORACLE_PASSWORD=... ORACLE_CONNECT_STRING=sovdef26_tp \
TNS_ADMIN=/path/to/wallet WALLET_PASSWORD=... \
uvicorn app.main:app --host 0.0.0.0 --port 8007 --reload
```

`pytest` runs offline: HTTP, oracledb, and APScheduler are all stubbed in `tests/conftest.py`.

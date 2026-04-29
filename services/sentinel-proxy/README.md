# Sentinel-2 Proxy — UC4 Sovereign Proxy Pattern C

Translates browser tile requests into [Sentinel Hub WMS](https://sh.dataspace.copernicus.eu/ogc/wms) GetMap calls signed with an OAuth2 Bearer token from the [Copernicus Dataspace](https://dataspace.copernicus.eu) identity provider. Browsers never see the OAuth credentials and never reach `sh.dataspace.copernicus.eu` directly.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/healthz` | Liveness + DB pool reachable + token cache populated. 200 / 503. |
| `GET`  | `/metrics` | Prometheus-style counters. |
| `GET`  | `/api/osint/sentinel/layers` | JSON list of layers from cached GetCapabilities (refreshed daily). |
| `GET`  | `/api/osint/sentinel/tiles/{layer}/{z}/{x}/{y}.png` | XYZ tile served by translating to WMS GetMap. |

## OAuth2 token cache

The service performs the **client-credentials** flow at startup and refreshes every `TOKEN_REFRESH_MINUTES` (default 25 min — Copernicus tokens live 30 min, so 25 leaves a 5 min safety buffer). The token is held in process memory; a refresh failure does not crash the service but increments `sentinel_token_refresh_failures` and the next tick retries.

The OAuth credentials (`SENTINEL_CLIENT_ID`, `SENTINEL_CLIENT_SECRET`) and the `SENTINEL_INSTANCE_ID` (Configuration UUID) are projected from OCI Vault into a Kubernetes Secret by the External Secrets Operator. The service reads them as plain env vars — no SDK call inside the pod.

## Tile-to-BBOX math

Tiles are XYZ in Web Mercator (EPSG:3857) — same convention as OpenStreetMap and Google Maps. The proxy converts `(z, x, y)` to a Web-Mercator-meter bbox and feeds it into the WMS GetMap call as `BBOX=xmin,ymin,xmax,ymax&CRS=EPSG:3857`. See `app/tile_math.py` for the closed-form formula.

## Audit batching

Tile traffic at zoom 12+ pan/zoom can easily exceed 100 requests/second. Writing one `audit_events` row per tile would flood the hash-chained log. The service batches: one row per `AUDIT_FLUSH_TILES` (default 50) tiles or per `AUDIT_FLUSH_SECONDS` (default 30) seconds. Each row carries `actor_service='sentinel-proxy'`, `action='tile_fetch'`, `resource_type='sentinel/tile'`, `payload={"tile_count":N,"layers":[...],"first_z":...,"last_z":...}`, `ols_label=100`.

## Local dev

```bash
cd services/sentinel-proxy
pip install -r requirements-dev.txt
SENTINEL_CLIENT_ID=... SENTINEL_CLIENT_SECRET=... SENTINEL_INSTANCE_ID=... \
ORACLE_USER=DICE_APP ORACLE_PASSWORD=... ORACLE_CONNECT_STRING=sovdef26_tp \
TNS_ADMIN=/path/to/wallet WALLET_PASSWORD=... \
uvicorn app.main:app --host 0.0.0.0 --port 8008 --reload
```

`pytest` runs offline: httpx, oracledb, and the OAuth provider are all mocked.

## Tech-debt

- **No on-disk tile cache.** Demo relies on browser HTTP caching via `Cache-Control: public, max-age=3600`. If Sentinel-Hub quota becomes an issue, add an OCI Object Storage cache step (read-from-bucket → if-miss-call-WMS → write-to-bucket).
- **No bbox-spillover protection.** The proxy currently passes any `(z, x, y)` through; an attacker could request high-zoom tiles for arbitrary regions and burn quota. Add bbox sanity checks against `SENTINEL_BBOX_DEFAULT` if quota matters.

# GPS Jamming Poller — UC4 Sovereign Proxy Pattern A

Polls the **adsb.lol** community feeder API on a fixed interval, aggregates aircraft positions by H3 cell at resolution 4, classifies each cell green/amber/red by the share of aircraft reporting low [NACp](https://en.wikipedia.org/wiki/Navigation_Accuracy_Category) (positional integrity), and persists the resulting GeoJSON FeatureCollection in `osint_cache(layer='jamming')`. Browsers never hit adsb.lol directly; the cached payload is served via `/api/osint/jamming/current`.

> **Why adsb.lol, not gpsjam.org?** gpsjam.org is a SvelteKit web app that doesn't publish a stable CSV download — the jamming map is rendered client-side from non-public data tiles. adsb.lol is a community-maintained ADS-B aggregator (free, no API key, EU-hosted) that exposes the raw aircraft state including the `nac_p` field. This service computes the same NACp-share classification gpsjam.org shows, but does so in-house against the raw data.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/healthz` | Liveness + DB pool reachable. 200 / 503. |
| `GET`  | `/metrics` | Prometheus-style counters. |
| `GET`  | `/api/osint/jamming/current` | GeoJSON FeatureCollection from cache. Optional `?bbox_s=&bbox_w=&bbox_n=&bbox_e=` filter. 503 if cache is older than `CACHE_TTL_HOURS`. |

## NACp Classification

NACp is encoded 0–11 on the ADS-B scale; values below 8 imply position uncertainty worse than ~30 m and are flagged as "low" (a well-documented signature of GPS interference). Cells with fewer than `MINIMUM_AIRCRAFT_COUNT` aircraft are dropped as noisy.

| Ratio (low-NACp / total aircraft) | Class |
|-----------------------------------|-------|
| < `CLASSIFY_AMBER_THRESHOLD` (default 2 %)   | green  |
| ≥ amber, ≤ `CLASSIFY_RED_THRESHOLD` (default 10 %) | amber  |
| > red threshold | red    |

Aircraft reporting `nac_p == null` are counted as "low" — an aircraft that cannot vouch for its own positional accuracy is not a clean position.

## Refresh schedule

APScheduler runs every `REFRESH_MINUTES` (default 30 min). At each tick:

1. `httpx.get($ADSB_API_BASE/v2/lat/$LAT/lon/$LON/dist/$RADIUS_NM)` — adsb.lol caps `dist` at 250 nm. Default centre is `(54.5, 15.0)` which covers the full Baltic + most of central Europe at radius 250 nm.
2. `body['ac']` → H3 binning → low-NACp ratio → drop noisy → classify
3. Persist as a single JSON blob in `osint_cache(layer='jamming', fetched_at, payload, classification, source)`
4. One `audit_events` row: `actor_service='jamming-poller'`, `action='layer_fetch'`, `resource_type='adsb.lol/aircraft'`, `ols_label=100`.

If the upstream is 4xx/5xx or the body has no `ac` array, the existing cache row stays valid and the next tick retries. The endpoint serves the latest row only if it is younger than `CACHE_TTL_HOURS` — older cache rows are treated as stale and the endpoint returns 503 cold-cache shape.

## Local dev

```bash
cd services/jamming-poller
pip install -r requirements-dev.txt
ORACLE_USER=DICE_APP ORACLE_PASSWORD=... ORACLE_CONNECT_STRING=sovdef26_tp \
TNS_ADMIN=/path/to/wallet WALLET_PASSWORD=... \
uvicorn app.main:app --host 0.0.0.0 --port 8007 --reload
```

`pytest` runs offline: httpx, oracledb, and APScheduler are all stubbed in `tests/conftest.py`. The aggregator is exercised with a synthetic aircraft list (no network needed).

## Future: paid ADS-B Exchange upgrade

The upstream is fully encapsulated behind `ADSB_API_BASE` + the `/v2/lat/.../lon/.../dist/...` URL shape. The paid ADS-B Exchange RapidAPI has the same response schema (the free adsb.lol mirror is a community fork). To switch:

1. Subscribe at https://rapidapi.com/adsbx/api/adsbexchange-com1
2. Store the API key in OCI Vault (compartment `oci-defence-demo`).
3. Add an `ExternalSecret` projecting the key as an env var (analog to `ais-stream-key-secret` for the Maritime layer).
4. Patch `app/poller.py` to add a `X-RapidAPI-Key` header from settings.
5. Set `ADSB_API_BASE=https://aircraftjson.adsbexchange.com` (or whatever RapidAPI gives you).

The aggregator, cache, audit and endpoint stay unchanged.

# Flights Proxy — UC4 Sovereign Proxy Pattern A (multi-sub-layer)

Polls [adsb.lol](https://adsb.lol) every `REFRESH_MINUTES` (default 2), classifies each aircraft as `civil` / `mil` via the hybrid classifier (curated > Mictronics community DB > civil-default), and stores two GeoJSON FeatureCollections in `osint_cache`:

- `osint_cache(layer='flights-civil')`
- `osint_cache(layer='flights-mil')`

The browser fetches `/api/osint/flights/civil/current` or `/api/osint/flights/mil/current`. The classifier is in-process; lookups against `mil_aircraft_unified` are cached for `CLASSIFIER_CACHE_TTL_MINUTES` (default 30) so a 200-aircraft refresh only hits the DB once or twice per tick.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/healthz` | Liveness + DB pool reachable. 200 / 503. |
| `GET`  | `/metrics` | Prometheus counters: fetches, classifications, cache hits. |
| `GET`  | `/api/osint/flights/civil/current` | GeoJSON FeatureCollection. Optional bbox filter. |
| `GET`  | `/api/osint/flights/mil/current`   | GeoJSON FeatureCollection. Optional bbox filter. |

## Hybrid classifier

```
classify(hex24):
  1. mil_aircraft_curated[hex24]    → 'mil' with mil_source='curated'
  2. mil_aircraft_mictronics[hex24] → 'mil' with mil_source='mictronics'
  3. else                            → 'civil' (mil_source = null)
```

The DB-side `mil_aircraft_unified` view enforces the precedence — Mictronics rows are filtered out when a curated entry exists for the same hex24. The Python classifier just does one query per (cold) hex24, then in-memory caches the answer for `CLASSIFIER_CACHE_TTL_MINUTES`.

## Mil database refresh

`mil_aircraft_curated` is hand-edited via SQL or a future admin tool — sovereign source.

`mil_aircraft_mictronics` is bulk-loaded from <https://github.com/Mictronics/readsb/blob/dev/webapp/src/db/aircrafts.json> by `scripts/load-mictronics-aircraft.sh`. Run weekly (or manually after a major Mictronics update). The loader truncates and re-inserts so it's safe to re-run.

## Local dev

```bash
cd services/flights-proxy
pip install -r requirements-dev.txt
ORACLE_USER=DICE_APP ORACLE_PASSWORD=... ORACLE_CONNECT_STRING=sovdef26_tp \
TNS_ADMIN=/path/to/wallet WALLET_PASSWORD=... \
uvicorn app.main:app --host 0.0.0.0 --port 8009 --reload
```

`pytest` runs offline: httpx, oracledb, and APScheduler are stubbed in `tests/conftest.py`.

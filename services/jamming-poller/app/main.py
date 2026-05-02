"""
FastAPI entrypoint for the GPS Jamming Poller (Sovereign Proxy Pattern A).
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Query, Response, status

from .audit import AuditWriter
from .cache_repo import CacheRepo
from .db import get_db_pool
from .poller import JammingPoller
from .settings import Settings, get_settings

# --- structlog → JSON ------------------------------------------------------

logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger("jamming-poller")


# --- Lifespan: kick off the poller scheduler -------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    cache = CacheRepo()
    audit = AuditWriter(tenant_id=settings.x_tenant_default)
    poller = JammingPoller(settings=settings, cache=cache, audit=audit)

    app.state.settings = settings
    app.state.cache = cache
    app.state.audit = audit
    app.state.poller = poller

    await poller.start()
    logger.info(
        "service.started",
        port=settings.poller_port,
        region=settings.oci_region,
        refresh_minutes=settings.refresh_minutes,
        upstream_base=settings.adsb_api_base,
    )
    try:
        yield
    finally:
        logger.info("service.stopping")
        await poller.stop()
        logger.info("service.stopped")


app = FastAPI(
    title="Sovereign Defence — GPS Jamming Poller",
    version="0.1.0",
    lifespan=lifespan,
)


# --- /healthz: 200 if DB reachable, 503 otherwise --------------------------


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    pool = get_db_pool()
    db_ok = await pool.healthcheck()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "service": "jamming-poller", "db": "unreachable"}
    return {"status": "ok", "service": "jamming-poller", "db": "ok"}


# --- /metrics: prom-style text exposition ---------------------------------


@app.get("/metrics")
async def metrics() -> Response:
    poller: Optional[JammingPoller] = getattr(app.state, "poller", None)
    cache: Optional[CacheRepo] = getattr(app.state, "cache", None)

    fetches_total = poller.fetches_total if poller else 0
    fetches_ok = poller.fetches_ok if poller else 0
    fetches_failed = poller.fetches_failed if poller else 0
    cache_hits = cache.hits if cache else 0
    cache_misses = cache.misses if cache else 0
    last_fetch_ts = poller.last_fetch_ts_iso if poller else ""

    body = (
        "# HELP jamming_fetches_total Total upstream CSV fetch attempts\n"
        "# TYPE jamming_fetches_total counter\n"
        f"jamming_fetches_total {fetches_total}\n"
        "# HELP jamming_fetches_ok Successful upstream CSV fetches\n"
        "# TYPE jamming_fetches_ok counter\n"
        f"jamming_fetches_ok {fetches_ok}\n"
        "# HELP jamming_fetches_failed Failed upstream CSV fetches (4xx/5xx/network)\n"
        "# TYPE jamming_fetches_failed counter\n"
        f"jamming_fetches_failed {fetches_failed}\n"
        "# HELP jamming_cache_hits Cache lookups that returned a row\n"
        "# TYPE jamming_cache_hits counter\n"
        f"jamming_cache_hits {cache_hits}\n"
        "# HELP jamming_cache_misses Cache lookups that returned no row\n"
        "# TYPE jamming_cache_misses counter\n"
        f"jamming_cache_misses {cache_misses}\n"
        f"# HELP jamming_last_fetch_ts ISO-8601 timestamp of the last successful fetch\n"
        f"# TYPE jamming_last_fetch_ts gauge\n"
        f'jamming_last_fetch_ts_info{{ts="{last_fetch_ts}"}} 1\n'
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


# --- /api/osint/jamming/current --------------------------------------------


def _validate_bbox(
    bbox_s: Optional[float],
    bbox_w: Optional[float],
    bbox_n: Optional[float],
    bbox_e: Optional[float],
) -> Optional[tuple[float, float, float, float]]:
    """Returns (s,w,n,e) if all four set + valid, None if all unset, raises if partial."""
    parts = [bbox_s, bbox_w, bbox_n, bbox_e]
    if all(p is None for p in parts):
        return None
    if any(p is None for p in parts):
        raise ValueError("bbox: all of bbox_s/bbox_w/bbox_n/bbox_e must be set together")
    s, w, n, e = parts  # type: ignore[misc]
    if not (-90.0 <= s <= 90.0 and -90.0 <= n <= 90.0 and s < n):
        raise ValueError("bbox lat invalid: require -90 <= s < n <= 90")
    if not (-180.0 <= w <= 180.0 and -180.0 <= e <= 180.0):
        raise ValueError("bbox lon invalid: require -180 <= w,e <= 180")
    return (s, w, n, e)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Viewport-driven on-demand fetch (path A — frontend follows the Cesium
# camera). Same pattern as flights-proxy: query params lat/lon/dist trigger
# an immediate adsb.lol fetch + H3 aggregation for that 250 nm circle, with
# a short-TTL in-memory cache so concurrent panners share the upstream call.
# When lat/lon/dist are absent the endpoint falls back to the documented
# scheduled-Baltic cache row.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import time as _time  # noqa: E402

import httpx  # noqa: E402

from .nacp_aggregator import aggregate_aircraft_to_hex  # noqa: E402

_ADSB_MAX_DIST_NM = 250


def _quantise_viewport(lat: float, lon: float, dist: int) -> tuple[float, float, int]:
    return (round(lat, 1), round(lon, 1), max(5, (dist // 5) * 5))


def _validate_viewport(
    lat: Optional[float], lon: Optional[float], dist: Optional[int],
) -> Optional[tuple[float, float, int]]:
    parts = (lat, lon, dist)
    if all(p is None for p in parts):
        return None
    if any(p is None for p in parts):
        raise ValueError("viewport: lat, lon and dist must be set together")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("viewport: lat must be in [-90, 90]")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("viewport: lon must be in [-180, 180]")
    if dist < 1:
        raise ValueError("viewport: dist must be >= 1 nm")
    return (lat, lon, min(dist, _ADSB_MAX_DIST_NM))


_viewport_cache: dict[tuple, tuple[float, dict]] = {}
_viewport_lock = asyncio.Lock()


async def _fetch_viewport_payload(lat: float, lon: float, dist: int) -> dict:
    settings: Settings = app.state.settings
    url = f"{settings.adsb_api_base.rstrip('/')}/v2/lat/{lat}/lon/{lon}/dist/{dist}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.warning("viewport.network_error", url=url, error=str(exc))
        raise
    if resp.status_code != 200:
        raise RuntimeError(f"upstream {resp.status_code}")
    body = resp.json()
    aircraft = body.get("ac") or body.get("aircraft") or []
    if not isinstance(aircraft, list):
        aircraft = []
    payload = aggregate_aircraft_to_hex(aircraft, settings)
    payload["viewport"] = {"lat": lat, "lon": lon, "dist_nm": dist}

    # Audit row per external upstream call (CLAUDE.md compliance rule).
    # The scheduled-tick path writes to audit_events via poller.fetch_once;
    # the viewport branch must too so UC6 Compliance Automation sees every
    # camera-driven fetch.
    audit = app.state.audit
    try:
        await audit.record_fetch(
            action="layer_fetch_viewport",
            resource_type="adsb.lol/aircraft",
            resource_id=f"{lat}/{lon}/{dist}",
            ols_label=100,
            payload={
                "url": url,
                "viewport": {"lat": lat, "lon": lon, "dist_nm": dist},
                "aircraft_in": len(aircraft),
                "feature_count": len(payload.get("features", [])),
            },
        )
    except Exception:
        logger.exception("viewport.audit_failed")
    return payload


async def _viewport_payload_cached(lat: float, lon: float, dist: int) -> dict:
    settings: Settings = app.state.settings
    ttl = settings.viewport_cache_ttl_seconds
    key = _quantise_viewport(lat, lon, dist)
    now = _time.monotonic()
    async with _viewport_lock:
        entry = _viewport_cache.get(key)
        if entry is not None:
            stamp, fc = entry
            if now - stamp < ttl:
                return fc
    fc = await _fetch_viewport_payload(lat, lon, dist)
    async with _viewport_lock:
        _viewport_cache[key] = (_time.monotonic(), fc)
        if len(_viewport_cache) > 64:
            for k in list(_viewport_cache.keys())[: len(_viewport_cache) - 64]:
                _viewport_cache.pop(k, None)
    return fc


@app.get("/api/osint/jamming/current")
async def jamming_current(
    response: Response,
    lat: Optional[float] = Query(default=None),
    lon: Optional[float] = Query(default=None),
    dist: Optional[int] = Query(default=None),
    bbox_s: Optional[float] = Query(default=None),
    bbox_w: Optional[float] = Query(default=None),
    bbox_n: Optional[float] = Query(default=None),
    bbox_e: Optional[float] = Query(default=None),
) -> dict:
    # Viewport-driven path takes precedence; ignores bbox params if both set.
    try:
        viewport = _validate_viewport(lat, lon, dist)
    except ValueError as exc:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"error": str(exc)}
    if viewport is not None:
        v_lat, v_lon, v_dist = viewport
        try:
            return await _viewport_payload_cached(v_lat, v_lon, v_dist)
        except Exception as exc:
            logger.warning("viewport.fetch_failed", error=str(exc))
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "type": "FeatureCollection",
                "features": [],
                "error": "viewport_upstream_unavailable",
                "viewport": {"lat": v_lat, "lon": v_lon, "dist_nm": v_dist},
            }

    try:
        bbox = _validate_bbox(bbox_s, bbox_w, bbox_n, bbox_e)
    except ValueError as exc:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"error": str(exc)}

    cache: CacheRepo = app.state.cache
    settings: Settings = app.state.settings
    payload = await cache.read_latest("jamming", max_age_hours=settings.cache_ttl_hours)
    if payload is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "type": "FeatureCollection",
            "features": [],
            "error": "no_cache_yet",
            "message": (
                "jamming-poller has not completed a successful fetch within "
                f"the last {settings.cache_ttl_hours} h"
            ),
        }

    if bbox is None:
        return payload

    # Server-side bbox filter — keep only features whose centroid is inside.
    s, w, n, e = bbox
    features = payload.get("features", [])
    kept = []
    for feat in features:
        props = feat.get("properties", {})
        lat_c = props.get("centroid_lat")
        lon_c = props.get("centroid_lon")
        if lat_c is None or lon_c is None:
            continue
        if s <= lat_c <= n and w <= lon_c <= e:
            kept.append(feat)
    return {
        "type": "FeatureCollection",
        "features": kept,
        "fetched_at": payload.get("fetched_at"),
        "source": payload.get("source"),
        "filtered_bbox": [s, w, n, e],
    }

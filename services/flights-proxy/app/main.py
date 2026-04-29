"""FastAPI entrypoint for the Flights Proxy."""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import structlog
from fastapi import FastAPI, Path, Query, Response, status

from .audit import AuditWriter
from .cache_repo import CacheRepo
from .classifier import Classifier
from .db import get_db_pool
from .poller import FlightsPoller, _aircraft_to_feature, _adsb_mil_bit
from .settings import Settings, get_settings

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
logger = structlog.get_logger("flights-proxy")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    cache = CacheRepo()
    audit = AuditWriter(tenant_id=settings.x_tenant_default)
    classifier = Classifier(settings)
    poller = FlightsPoller(settings, cache, audit, classifier)

    app.state.settings = settings
    app.state.cache = cache
    app.state.audit = audit
    app.state.classifier = classifier
    app.state.poller = poller
    # Viewport-driven cache for on-demand viewport requests. Keyed by
    # (lat_q, lon_q, dist) — quantised to 0.1° / nearest 5 nm so adjacent
    # camera jiggles share a cache row. Value is (epoch_seconds, civil_payload,
    # mil_payload). TTL is `viewport_cache_ttl_seconds`. In-process only —
    # not persisted in osint_cache to avoid bloat from per-bbox snapshots.
    app.state.viewport_cache: dict[tuple, tuple[float, dict, dict]] = {}
    app.state.viewport_cache_lock = asyncio.Lock()

    await poller.start()
    logger.info(
        "service.started",
        port=settings.proxy_port,
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
    title="Sovereign Defence — Flights Proxy",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    pool = get_db_pool()
    db_ok = await pool.healthcheck()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "service": "flights-proxy", "db": "unreachable"}
    return {"status": "ok", "service": "flights-proxy", "db": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    poller: Optional[FlightsPoller] = getattr(app.state, "poller", None)
    cache: Optional[CacheRepo] = getattr(app.state, "cache", None)
    classifier: Optional[Classifier] = getattr(app.state, "classifier", None)

    fetches_total = poller.fetches_total if poller else 0
    fetches_ok = poller.fetches_ok if poller else 0
    fetches_failed = poller.fetches_failed if poller else 0
    last_civil = poller.last_civil_count if poller else 0
    last_mil = poller.last_mil_count if poller else 0
    cache_hits = cache.hits if cache else 0
    cache_misses = cache.misses if cache else 0
    classifier_lookups = classifier.lookups_total if classifier else 0
    classifier_cache_hits = classifier.cache_hits if classifier else 0

    body = (
        "# HELP flights_fetches_total Total upstream adsb.lol fetch attempts\n"
        "# TYPE flights_fetches_total counter\n"
        f"flights_fetches_total {fetches_total}\n"
        "# HELP flights_fetches_ok Successful fetch+classify+cache cycles\n"
        "# TYPE flights_fetches_ok counter\n"
        f"flights_fetches_ok {fetches_ok}\n"
        "# HELP flights_fetches_failed Failed cycles (network/4xx/5xx/empty)\n"
        "# TYPE flights_fetches_failed counter\n"
        f"flights_fetches_failed {fetches_failed}\n"
        "# HELP flights_last_civil_count Aircraft classified civil in the most recent tick\n"
        "# TYPE flights_last_civil_count gauge\n"
        f"flights_last_civil_count {last_civil}\n"
        "# HELP flights_last_mil_count Aircraft classified mil in the most recent tick\n"
        "# TYPE flights_last_mil_count gauge\n"
        f"flights_last_mil_count {last_mil}\n"
        "# HELP flights_cache_hits osint_cache reads with a fresh row\n"
        "# TYPE flights_cache_hits counter\n"
        f"flights_cache_hits {cache_hits}\n"
        "# HELP flights_cache_misses osint_cache reads with no row / stale row\n"
        "# TYPE flights_cache_misses counter\n"
        f"flights_cache_misses {cache_misses}\n"
        "# HELP flights_classifier_lookups Total classifier classify() calls\n"
        "# TYPE flights_classifier_lookups counter\n"
        f"flights_classifier_lookups {classifier_lookups}\n"
        "# HELP flights_classifier_cache_hits Classifier in-process cache hits\n"
        "# TYPE flights_classifier_cache_hits counter\n"
        f"flights_classifier_cache_hits {classifier_cache_hits}\n"
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


def _validate_bbox(
    bbox_s: Optional[float], bbox_w: Optional[float],
    bbox_n: Optional[float], bbox_e: Optional[float],
) -> Optional[tuple[float, float, float, float]]:
    parts = [bbox_s, bbox_w, bbox_n, bbox_e]
    if all(p is None for p in parts):
        return None
    if any(p is None for p in parts):
        raise ValueError("bbox: all of bbox_s/bbox_w/bbox_n/bbox_e must be set together")
    s, w, n, e = parts  # type: ignore[misc]
    if not (-90.0 <= s <= 90.0 and -90.0 <= n <= 90.0 and s < n):
        raise ValueError("bbox lat invalid")
    if not (-180.0 <= w <= 180.0 and -180.0 <= e <= 180.0):
        raise ValueError("bbox lon invalid")
    return (s, w, n, e)  # type: ignore[return-value]


async def _serve_layer(
    response: Response, layer: str,
    bbox_s: Optional[float], bbox_w: Optional[float],
    bbox_n: Optional[float], bbox_e: Optional[float],
) -> dict:
    try:
        bbox = _validate_bbox(bbox_s, bbox_w, bbox_n, bbox_e)
    except ValueError as exc:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"error": str(exc)}

    cache: CacheRepo = app.state.cache
    settings: Settings = app.state.settings
    payload = await cache.read_latest(layer, max_age_minutes=settings.cache_ttl_minutes)
    if payload is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "type": "FeatureCollection",
            "features": [],
            "error": "no_cache_yet",
            "message": (
                f"flights-proxy has not completed a successful fetch within "
                f"the last {settings.cache_ttl_minutes} min for layer={layer}"
            ),
        }
    if bbox is None:
        return payload
    s, w, n, e = bbox
    kept = []
    for feat in payload.get("features", []):
        coords = feat.get("geometry", {}).get("coordinates") or [None, None]
        lon, lat = (coords + [None, None])[:2]
        if lat is None or lon is None:
            continue
        if s <= lat <= n and w <= lon <= e:
            kept.append(feat)
    return {
        "type": "FeatureCollection",
        "features": kept,
        "fetched_at": payload.get("fetched_at"),
        "source": payload.get("source"),
        "filtered_bbox": [s, w, n, e],
    }


# ---------------------------------------------------------------------------
# Viewport-driven on-demand fetch (path A — frontend follows the Cesium
# camera and asks for whichever 250 nm circle it's currently over).
#
# adsb.lol's free-tier cap is 250 nm radius; we expose `dist` clamped to
# that. Cache is short-TTL (`viewport_cache_ttl_seconds`) and in-memory
# only — we don't persist per-bbox snapshots in osint_cache to avoid
# unbounded bloat. The scheduled Baltic poller still writes the
# documented `flights-civil`/`flights-mil` cache rows; viewport requests
# do not interact with that path.
# ---------------------------------------------------------------------------

_ADSB_MAX_DIST_NM = 250
_ADSB_DEFAULT_DIST_NM = 250


def _quantise_viewport(lat: float, lon: float, dist: int) -> tuple[float, float, int]:
    # Snap to 0.1° / 5 nm so a camera that jiggles by tens of metres still
    # hits the same cache key. Coarse enough to keep the dict small;
    # fine enough that user-perceptible camera moves bust the cache.
    return (round(lat, 1), round(lon, 1), max(5, (dist // 5) * 5))


async def _fetch_viewport_payloads(
    lat: float, lon: float, dist: int,
) -> tuple[dict, dict]:
    """Fetch+classify a single viewport. Returns (civil_fc, mil_fc)."""
    settings: Settings = app.state.settings
    classifier: Classifier = app.state.classifier
    url = (
        f"{settings.adsb_api_base.rstrip('/')}/v2/lat/"
        f"{lat}/lon/{lon}/dist/{dist}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.warning("viewport.network_error", url=url, error=str(exc))
        raise

    if resp.status_code != 200:
        logger.warning("viewport.upstream_status", url=url, status_code=resp.status_code)
        raise RuntimeError(f"upstream {resp.status_code}")

    body = resp.json()
    aircraft = body.get("ac") or body.get("aircraft") or []
    if not isinstance(aircraft, list):
        aircraft = []

    from datetime import datetime, timezone
    fetched_at = datetime.now(timezone.utc).isoformat()

    civil_features: list[dict] = []
    mil_features: list[dict] = []
    for ac in aircraft:
        verdict = await classifier.classify(ac.get("hex") or "")
        mil_source = verdict.source
        mil_label = verdict.label
        is_mil = verdict.category == "mil"
        if not is_mil and _adsb_mil_bit(ac):
            is_mil = True
            mil_source = "dbflags"
            mil_label = (ac.get("flight") or "").strip() or None
        feat = _aircraft_to_feature(ac, mil_source, mil_label)
        if feat is None:
            continue
        if is_mil:
            mil_features.append(feat)
        else:
            civil_features.append(feat)

    civil_fc = {
        "type": "FeatureCollection",
        "features": civil_features,
        "fetched_at": fetched_at,
        "source": "adsb.lol via ADS-B Exchange community feeders",
        "viewport": {"lat": lat, "lon": lon, "dist_nm": dist},
        "stats": {
            "aircraft_in": len(aircraft),
            "civil_count": len(civil_features),
            "mil_count": len(mil_features),
        },
    }
    mil_fc = dict(civil_fc)
    mil_fc["features"] = mil_features
    mil_fc["source"] = "adsb.lol via ADS-B Exchange + curated/Mictronics + dbFlags"
    return civil_fc, mil_fc


async def _viewport_payloads_cached(
    lat: float, lon: float, dist: int,
) -> tuple[dict, dict]:
    settings: Settings = app.state.settings
    ttl = settings.viewport_cache_ttl_seconds
    key = _quantise_viewport(lat, lon, dist)
    now = time.monotonic()
    cache: dict = app.state.viewport_cache
    lock: asyncio.Lock = app.state.viewport_cache_lock

    async with lock:
        entry = cache.get(key)
        if entry is not None:
            stamp, civil_fc, mil_fc = entry
            if now - stamp < ttl:
                return civil_fc, mil_fc

    civil_fc, mil_fc = await _fetch_viewport_payloads(lat, lon, dist)
    async with lock:
        cache[key] = (time.monotonic(), civil_fc, mil_fc)
        # Light pruning: keep at most 64 entries to avoid unbounded growth.
        if len(cache) > 64:
            for k in list(cache.keys())[: len(cache) - 64]:
                cache.pop(k, None)
    return civil_fc, mil_fc


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
    dist_clamped = min(dist, _ADSB_MAX_DIST_NM)
    return (lat, lon, dist_clamped)


async def _serve_with_viewport(
    response: Response, layer: str,
    lat: Optional[float], lon: Optional[float], dist: Optional[int],
    bbox_s: Optional[float], bbox_w: Optional[float],
    bbox_n: Optional[float], bbox_e: Optional[float],
) -> dict:
    try:
        viewport = _validate_viewport(lat, lon, dist)
    except ValueError as exc:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"error": str(exc)}

    if viewport is not None:
        v_lat, v_lon, v_dist = viewport
        try:
            civil_fc, mil_fc = await _viewport_payloads_cached(v_lat, v_lon, v_dist)
        except Exception as exc:
            logger.warning("viewport.fetch_failed", error=str(exc))
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "type": "FeatureCollection",
                "features": [],
                "error": "viewport_upstream_unavailable",
                "viewport": {"lat": v_lat, "lon": v_lon, "dist_nm": v_dist},
            }
        return civil_fc if layer == "flights-civil" else mil_fc

    return await _serve_layer(response, layer, bbox_s, bbox_w, bbox_n, bbox_e)


@app.get("/api/osint/flights/civil/current")
async def flights_civil(
    response: Response,
    lat: Optional[float] = Query(default=None),
    lon: Optional[float] = Query(default=None),
    dist: Optional[int] = Query(default=None),
    bbox_s: Optional[float] = Query(default=None),
    bbox_w: Optional[float] = Query(default=None),
    bbox_n: Optional[float] = Query(default=None),
    bbox_e: Optional[float] = Query(default=None),
) -> dict:
    return await _serve_with_viewport(
        response, "flights-civil", lat, lon, dist,
        bbox_s, bbox_w, bbox_n, bbox_e,
    )


@app.get("/api/osint/flights/mil/current")
async def flights_mil(
    response: Response,
    lat: Optional[float] = Query(default=None),
    lon: Optional[float] = Query(default=None),
    dist: Optional[int] = Query(default=None),
    bbox_s: Optional[float] = Query(default=None),
    bbox_w: Optional[float] = Query(default=None),
    bbox_n: Optional[float] = Query(default=None),
    bbox_e: Optional[float] = Query(default=None),
) -> dict:
    return await _serve_with_viewport(
        response, "flights-mil", lat, lon, dist,
        bbox_s, bbox_w, bbox_n, bbox_e,
    )

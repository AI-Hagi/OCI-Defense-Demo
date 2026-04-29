"""FastAPI entrypoint for the Flights Proxy."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Path, Query, Response, status

from .audit import AuditWriter
from .cache_repo import CacheRepo
from .classifier import Classifier
from .db import get_db_pool
from .poller import FlightsPoller
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


@app.get("/api/osint/flights/civil/current")
async def flights_civil(
    response: Response,
    bbox_s: Optional[float] = Query(default=None),
    bbox_w: Optional[float] = Query(default=None),
    bbox_n: Optional[float] = Query(default=None),
    bbox_e: Optional[float] = Query(default=None),
) -> dict:
    return await _serve_layer(response, "flights-civil", bbox_s, bbox_w, bbox_n, bbox_e)


@app.get("/api/osint/flights/mil/current")
async def flights_mil(
    response: Response,
    bbox_s: Optional[float] = Query(default=None),
    bbox_w: Optional[float] = Query(default=None),
    bbox_n: Optional[float] = Query(default=None),
    bbox_e: Optional[float] = Query(default=None),
) -> dict:
    return await _serve_layer(response, "flights-mil", bbox_s, bbox_w, bbox_n, bbox_e)

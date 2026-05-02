"""FastAPI entrypoint for the Ports Proxy."""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Header, HTTPException, Response, status

from .audit import AuditWriter
from .cache_repo import CacheRepo
from .classifier import PortClassifier
from .db import get_db_pool
from .loader import PortsLoader
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
logger = structlog.get_logger("ports-proxy")


async def _bootstrap_if_needed(
    cache: CacheRepo, loader: PortsLoader, settings: Settings,
) -> None:
    """
    On service start: kick off the loader only when we have nothing
    fresh in osint_cache. The loader runs in the background so /healthz
    can return 200 immediately — Pattern A but explicitly without an
    APScheduler.
    """
    ttl_hours = settings.ports_cache_ttl_days * 24
    payload = await cache.read_latest("ports", max_age_hours=ttl_hours)
    if payload is not None:
        feat_n = len(payload.get("features", []))
        logger.info(
            "bootstrap.cache_fresh",
            ttl_days=settings.ports_cache_ttl_days,
            feature_count=feat_n,
        )
        return
    logger.info("bootstrap.cache_cold_run_loader")
    try:
        await loader.run()
    except Exception:
        logger.exception("bootstrap.loader_crashed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    cache = CacheRepo()
    audit = AuditWriter(tenant_id=settings.x_tenant_default)
    classifier = PortClassifier(settings)
    loader = PortsLoader(settings, cache, audit, classifier)

    app.state.settings = settings
    app.state.cache = cache
    app.state.audit = audit
    app.state.classifier = classifier
    app.state.loader = loader

    # Run bootstrap concurrently so the HTTP server is immediately
    # ready to answer /healthz; OSM Overpass can take 30 s+ for a
    # first global pull.
    asyncio.create_task(_bootstrap_if_needed(cache, loader, settings))
    logger.info(
        "service.started",
        port=settings.proxy_port,
        region=settings.oci_region,
        cache_ttl_days=settings.ports_cache_ttl_days,
        upstream=settings.overpass_api_url,
        bbox=list(settings.bbox_tuple()),
    )
    try:
        yield
    finally:
        logger.info("service.stopped")


app = FastAPI(
    title="Sovereign Defence — Ports Proxy",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    pool = get_db_pool()
    db_ok = await pool.healthcheck()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "service": "ports-proxy", "db": "unreachable"}
    return {"status": "ok", "service": "ports-proxy", "db": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    cache: Optional[CacheRepo] = getattr(app.state, "cache", None)
    classifier: Optional[PortClassifier] = getattr(app.state, "classifier", None)
    loader: Optional[PortsLoader] = getattr(app.state, "loader", None)

    cache_hits = cache.hits if cache else 0
    cache_misses = cache.misses if cache else 0
    classifier_lookups = classifier.lookups_total if classifier else 0
    curated_matches = classifier.curated_matches if classifier else 0
    osm_fallbacks = classifier.osm_fallbacks if classifier else 0
    last_element_count = loader.last_element_count if loader else 0
    last_run_ok = 1 if (loader and loader.last_run_ok) else 0

    body = (
        "# HELP ports_cache_hits osint_cache reads with a fresh row\n"
        "# TYPE ports_cache_hits counter\n"
        f"ports_cache_hits {cache_hits}\n"
        "# HELP ports_cache_misses osint_cache reads with no row / stale row\n"
        "# TYPE ports_cache_misses counter\n"
        f"ports_cache_misses {cache_misses}\n"
        "# HELP ports_classifier_lookups Total classifier classify() calls\n"
        "# TYPE ports_classifier_lookups counter\n"
        f"ports_classifier_lookups {classifier_lookups}\n"
        "# HELP ports_curated_matches Classifications resolved by curated nearest-neighbor\n"
        "# TYPE ports_curated_matches counter\n"
        f"ports_curated_matches {curated_matches}\n"
        "# HELP ports_osm_fallbacks Classifications resolved by OSM-tag heuristic\n"
        "# TYPE ports_osm_fallbacks counter\n"
        f"ports_osm_fallbacks {osm_fallbacks}\n"
        "# HELP ports_last_feature_count Most recent loader feature count\n"
        "# TYPE ports_last_feature_count gauge\n"
        f"ports_last_feature_count {last_element_count}\n"
        "# HELP ports_last_run_ok 1 if last loader pass succeeded, 0 otherwise\n"
        "# TYPE ports_last_run_ok gauge\n"
        f"ports_last_run_ok {last_run_ok}\n"
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


@app.get("/api/osint/ports/current")
async def ports_current(response: Response) -> dict:
    cache: CacheRepo = app.state.cache
    settings: Settings = app.state.settings
    payload = await cache.read_latest(
        "ports", max_age_hours=settings.ports_cache_ttl_days * 24,
    )
    if payload is None:
        # Cold cache. Return an empty FeatureCollection with a hint —
        # frontend already ignores 503 responses.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "type": "FeatureCollection",
            "features": [],
            "error": "no_cache_yet",
            "message": (
                "ports-proxy has not completed a successful loader run. "
                "POST /api/osint/ports/refresh with X-Internal-Token to "
                "trigger one explicitly."
            ),
        }
    return payload


@app.post("/api/osint/ports/refresh")
async def ports_refresh(
    response: Response,
    x_internal_token: Optional[str] = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    """
    Operator-triggered refresh. Re-runs the loader, overwriting the
    cache. Gated by `PORTS_INTERNAL_TOKEN` — without it, callers get
    503 (i.e. refresh is disabled by default, set the env to enable).
    """
    settings: Settings = app.state.settings
    expected = settings.ports_internal_token
    if not expected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"error": "refresh_disabled", "hint": "PORTS_INTERNAL_TOKEN not set"}
    if x_internal_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    loader: PortsLoader = app.state.loader
    return await loader.run()

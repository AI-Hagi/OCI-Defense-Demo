"""FastAPI entrypoint for the TLE Proxy."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Path, Response, status

from .audit import AuditWriter
from .cache_repo import CacheRepo
from .db import get_db_pool
from .poller import TlePoller
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
logger = structlog.get_logger("tle-proxy")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    cache = CacheRepo()
    audit = AuditWriter(tenant_id=settings.x_tenant_default)
    poller = TlePoller(settings, cache, audit)

    app.state.settings = settings
    app.state.cache = cache
    app.state.audit = audit
    app.state.poller = poller

    await poller.start()
    logger.info(
        "service.started",
        port=settings.proxy_port,
        region=settings.oci_region,
        refresh_hours=settings.tle_refresh_hours,
        groups=settings.groups_list(),
        upstream_base=settings.celestrak_base_url,
    )
    try:
        yield
    finally:
        logger.info("service.stopping")
        await poller.stop()
        logger.info("service.stopped")


app = FastAPI(
    title="Sovereign Defence — TLE Proxy",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    pool = get_db_pool()
    db_ok = await pool.healthcheck()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "service": "tle-proxy", "db": "unreachable"}
    return {"status": "ok", "service": "tle-proxy", "db": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    poller: Optional[TlePoller] = getattr(app.state, "poller", None)
    cache: Optional[CacheRepo] = getattr(app.state, "cache", None)

    fetches_total = poller.fetches_total if poller else 0
    fetches_ok = poller.fetches_ok if poller else 0
    fetches_failed = poller.fetches_failed if poller else 0
    cache_hits = cache.hits if cache else 0
    cache_misses = cache.misses if cache else 0
    last_counts = poller.last_counts if poller else {}

    body_lines = [
        "# HELP tle_fetches_total Total CelesTrak fetch attempts (one per group per refresh)",
        "# TYPE tle_fetches_total counter",
        f"tle_fetches_total {fetches_total}",
        "# HELP tle_fetches_ok Successful fetch+parse+cache cycles",
        "# TYPE tle_fetches_ok counter",
        f"tle_fetches_ok {fetches_ok}",
        "# HELP tle_fetches_failed Failed cycles (network/4xx/5xx/empty/parse-zero)",
        "# TYPE tle_fetches_failed counter",
        f"tle_fetches_failed {fetches_failed}",
        "# HELP tle_cache_hits osint_cache reads with a fresh row",
        "# TYPE tle_cache_hits counter",
        f"tle_cache_hits {cache_hits}",
        "# HELP tle_cache_misses osint_cache reads with no row / stale row",
        "# TYPE tle_cache_misses counter",
        f"tle_cache_misses {cache_misses}",
    ]
    for group, count in last_counts.items():
        # Per-group last-tick TLE record count — operator-visible signal
        # that a group is actually populated.
        body_lines.append(
            f"# HELP tle_last_count_{group} Most recent TLE record count for the {group} catalog"
        )
        body_lines.append(f"# TYPE tle_last_count_{group} gauge")
        body_lines.append(f"tle_last_count_{group} {count}")
    body = "\n".join(body_lines) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4")


# ---------------------------------------------------------------------------
# Public read endpoints — one per CelesTrak group.
# ---------------------------------------------------------------------------

_VALID_GROUPS = {"stations", "resource", "active"}


async def _serve_group(response: Response, group: str) -> dict:
    if group not in _VALID_GROUPS:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": "unknown_group", "group": group, "valid": sorted(_VALID_GROUPS)}
    cache: CacheRepo = app.state.cache
    settings: Settings = app.state.settings
    layer = f"satellites-{group}"
    payload = await cache.read_latest(layer, max_age_hours=settings.cache_ttl_hours)
    if payload is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "type": "TleCollection",
            "group": group,
            "tle": [],
            "count": 0,
            "error": "no_cache_yet",
            "message": (
                f"tle-proxy has not completed a successful fetch within the "
                f"last {settings.cache_ttl_hours} h for group={group}"
            ),
        }
    return payload


@app.get("/api/osint/satellites/{group}/current")
async def satellites_group(
    response: Response,
    group: str = Path(..., pattern="^[a-z]+$"),
) -> dict:
    return await _serve_group(response, group)

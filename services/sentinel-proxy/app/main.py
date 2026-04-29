"""
FastAPI entrypoint for the Sentinel-2 Proxy (Sovereign Proxy Pattern C).
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Path, Response, status
from fastapi.responses import Response as FastResponse

from .audit import AuditBatcher
from .db import get_db_pool
from .settings import Settings, get_settings
from .tile_math import tile_to_bbox_3857
from .token_manager import TokenError, TokenManager
from .wms_client import WmsError, fetch_capabilities, fetch_tile, parse_layers_from_capabilities

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
logger = structlog.get_logger("sentinel-proxy")


# --- Lifespan: token + audit batcher --------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    if not settings.sentinel_client_id or not settings.sentinel_client_secret or not settings.sentinel_instance_id:
        raise RuntimeError(
            "Sentinel credentials missing — set SENTINEL_CLIENT_ID, "
            "SENTINEL_CLIENT_SECRET, SENTINEL_INSTANCE_ID (typically via "
            "the External Secrets Operator)."
        )

    tokens = TokenManager(settings)
    audit = AuditBatcher(settings, tenant_id=settings.x_tenant_default)
    capabilities_cache: dict = {"layers": [], "fetched_at": None}

    app.state.settings = settings
    app.state.tokens = tokens
    app.state.audit = audit
    app.state.capabilities = capabilities_cache
    app.state.http_client = httpx.AsyncClient(timeout=30.0)

    await tokens.start()
    await audit.start()
    logger.info(
        "service.started",
        port=settings.proxy_port,
        region=settings.oci_region,
        token_refresh_minutes=settings.token_refresh_minutes,
        default_layer=settings.sentinel_default_layer,
    )
    try:
        yield
    finally:
        logger.info("service.stopping")
        await tokens.stop()
        await audit.stop()
        await app.state.http_client.aclose()
        logger.info("service.stopped")


app = FastAPI(
    title="Sovereign Defence — Sentinel-2 Proxy",
    version="0.1.0",
    lifespan=lifespan,
)


# --- /healthz ---------------------------------------------------------------


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, object]:
    pool = get_db_pool()
    db_ok = await pool.healthcheck()
    tokens: TokenManager = app.state.tokens
    token_ok = tokens.has_token

    if not db_ok or not token_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "degraded",
            "service": "sentinel-proxy",
            "db": "ok" if db_ok else "unreachable",
            "token": "ok" if token_ok else "missing",
        }
    return {
        "status": "ok",
        "service": "sentinel-proxy",
        "db": "ok",
        "token": "ok",
        "token_age_seconds": tokens.token_age_seconds,
    }


# --- /metrics ---------------------------------------------------------------


@app.get("/metrics")
async def metrics() -> Response:
    tokens: Optional[TokenManager] = getattr(app.state, "tokens", None)
    audit: Optional[AuditBatcher] = getattr(app.state, "audit", None)

    refresh_count = tokens.refresh_count if tokens else 0
    refresh_failures = tokens.refresh_failures if tokens else 0
    audit_writes = audit.writes_total if audit else 0
    audit_failures = audit.write_failures_total if audit else 0

    body = (
        "# HELP sentinel_token_refreshes Successful OAuth token refreshes\n"
        "# TYPE sentinel_token_refreshes counter\n"
        f"sentinel_token_refreshes {refresh_count}\n"
        "# HELP sentinel_token_refresh_failures Failed OAuth token refreshes\n"
        "# TYPE sentinel_token_refresh_failures counter\n"
        f"sentinel_token_refresh_failures {refresh_failures}\n"
        "# HELP sentinel_audit_writes Successful audit_events batch inserts\n"
        "# TYPE sentinel_audit_writes counter\n"
        f"sentinel_audit_writes {audit_writes}\n"
        "# HELP sentinel_audit_write_failures Failed audit_events batch inserts\n"
        "# TYPE sentinel_audit_write_failures counter\n"
        f"sentinel_audit_write_failures {audit_failures}\n"
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


# --- /api/osint/sentinel/layers --------------------------------------------


@app.get("/api/osint/sentinel/layers")
async def sentinel_layers() -> dict:
    settings: Settings = app.state.settings
    cache: dict = app.state.capabilities
    fetched_at = cache.get("fetched_at")
    fresh = (
        fetched_at is not None
        and (datetime.now(timezone.utc) - fetched_at)
        < timedelta(hours=settings.capabilities_ttl_hours)
    )
    if not fresh:
        try:
            xml = await fetch_capabilities(settings, client=app.state.http_client)
            layers = parse_layers_from_capabilities(xml)
        except WmsError as exc:
            logger.warning("layers.capabilities_failed", status=exc.status)
            layers = cache.get("layers", [])
        cache["layers"] = layers
        cache["fetched_at"] = datetime.now(timezone.utc)

    return {
        "default_layer": settings.sentinel_default_layer,
        "layers": cache["layers"],
        "fetched_at": cache["fetched_at"].isoformat() if cache["fetched_at"] else None,
    }


# --- /api/osint/sentinel/tiles/{layer}/{z}/{x}/{y}.png ---------------------


@app.get("/api/osint/sentinel/tiles/{layer}/{z}/{x}/{y}.png")
async def sentinel_tile(
    layer: str = Path(..., min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_\-]+$"),
    z: int = Path(..., ge=0, le=22),
    x: int = Path(..., ge=0),
    y: int = Path(..., ge=0),
) -> Response:
    settings: Settings = app.state.settings
    tokens: TokenManager = app.state.tokens
    audit: AuditBatcher = app.state.audit

    try:
        bbox = tile_to_bbox_3857(z, x, y)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        token = tokens.get_token()
    except TokenError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        png = await fetch_tile(
            settings, token, layer, bbox, client=app.state.http_client
        )
    except WmsError as exc:
        # Don't 500 — return the upstream status the client should care
        # about (4xx → real error, 5xx → upstream temporarily down).
        logger.warning(
            "tile.upstream_error",
            layer=layer,
            z=z, x=x, y=y,
            status=exc.status,
            content_type=exc.content_type,
        )
        raise HTTPException(status_code=502, detail="upstream WMS error")

    await audit.add_tile(layer, z, x, y)

    return FastResponse(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )

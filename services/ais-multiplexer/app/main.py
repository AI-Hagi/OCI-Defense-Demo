"""
FastAPI entrypoint for the AIS Multiplexer (Sovereign Proxy Pattern B).

Endpoints:
  GET  /healthz           — liveness + DB-pool reachability (200 / 503)
  GET  /metrics           — Prometheus-style counters
  WS   /ws/maritime       — fan-out subscription, optional bbox query params
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Query, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

from .audit import AuditBatcher, AuditFrame
from .db import get_db_pool
from .multiplexer import Multiplexer
from .settings import Settings, get_settings
from .upstream import UpstreamConnection
from .vault import VaultError, get_secret

# --- structlog → JSON, no print() anywhere ---------------------------------

logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)
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
logger = structlog.get_logger("ais-multiplexer")


# --- Lifespan: build upstream / mux / audit on startup ---------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    bbox = settings.bbox_default_tuple()

    # 1. Resolve the AIS Stream API key. Three accepted sources, in order
    #    of preference inside vault.get_secret(): AIS_STREAM_API_KEY (raw
    #    value injected by ESO from a K8s Secret), MOCK_VAULT_KEY (offline
    #    dev), VAULT_AIS_STREAM_KEY_OCID (runtime SDK resolve via Workload
    #    Identity / Instance Principal). At least one must be set.
    if (
        not settings.ais_stream_api_key
        and not settings.vault_ais_stream_key_ocid
        and not settings.mock_vault_key
    ):
        raise RuntimeError(
            "No AIS Stream API key source configured — set one of "
            "AIS_STREAM_API_KEY (preferred, via ExternalSecret), "
            "VAULT_AIS_STREAM_KEY_OCID (Workload-Identity SDK path), or "
            "MOCK_VAULT_KEY (offline dev only)."
        )
    try:
        api_key = await get_secret(
            settings.vault_ais_stream_key_ocid or "", settings=settings
        )
    except VaultError as exc:
        raise RuntimeError(f"Vault read failed — service cannot start: {exc}") from exc
    if not api_key:
        raise RuntimeError("Vault returned empty AIS Stream API key")

    # 2. Wire upstream + multiplexer + audit batcher.
    multiplexer = Multiplexer()
    audit = AuditBatcher(bbox=bbox, tenant_id="T001")
    upstream = UpstreamConnection(api_key=api_key, bbox=bbox, settings=settings)

    app.state.settings = settings
    app.state.multiplexer = multiplexer
    app.state.audit = audit
    app.state.upstream = upstream
    app.state.upstream_task = None

    await audit.start()

    async def _pump() -> None:
        try:
            async for frame in upstream.iter_frames():
                await multiplexer.broadcast(frame)
                await audit.add(
                    AuditFrame(
                        mmsi=frame["mmsi"],
                        ts=frame["ts"],
                        lat=frame["lat"],
                        lon=frame["lon"],
                    )
                )
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            logger.exception("upstream.pump.crash")

    app.state.upstream_task = asyncio.create_task(_pump(), name="ais-upstream-pump")
    logger.info(
        "service.started",
        port=settings.multiplexer_port,
        bbox=list(bbox),
        region=settings.oci_region,
    )

    try:
        yield
    finally:
        logger.info("service.stopping")
        await upstream.stop()
        if app.state.upstream_task is not None:
            app.state.upstream_task.cancel()
            try:
                await app.state.upstream_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await multiplexer.shutdown()
        await audit.stop()
        logger.info("service.stopped")


app = FastAPI(
    title="Sovereign Defence — AIS Multiplexer",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- /healthz: 200 if DB reachable, 503 otherwise --------------------------


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    pool = get_db_pool()
    db_ok = await pool.healthcheck()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "service": "ais-multiplexer", "db": "unreachable"}
    return {"status": "ok", "service": "ais-multiplexer", "db": "ok"}


# --- /metrics: prom-style text exposition ---------------------------------


@app.get("/metrics")
async def metrics() -> Response:
    upstream: Optional[UpstreamConnection] = getattr(app.state, "upstream", None)
    mux: Optional[Multiplexer] = getattr(app.state, "multiplexer", None)
    audit: Optional[AuditBatcher] = getattr(app.state, "audit", None)

    frames_received = upstream.frames_received if upstream else 0
    upstream_reconnects = upstream.reconnects if upstream else 0
    frames_forwarded = mux.frames_forwarded if mux else 0
    slow_drops = mux.slow_client_drops if mux else 0
    client_count = mux.client_count if mux else 0
    audit_writes = audit.writes_total if audit else 0
    audit_failures = audit.write_failures_total if audit else 0

    body = (
        "# HELP ais_frames_received Total upstream AIS frames received\n"
        "# TYPE ais_frames_received counter\n"
        f"ais_frames_received {frames_received}\n"
        "# HELP ais_frames_forwarded Total frames sent to downstream clients\n"
        "# TYPE ais_frames_forwarded counter\n"
        f"ais_frames_forwarded {frames_forwarded}\n"
        "# HELP ais_audit_writes Successful audit_events inserts\n"
        "# TYPE ais_audit_writes counter\n"
        f"ais_audit_writes {audit_writes}\n"
        "# HELP ais_audit_write_failures Failed audit_events inserts after retries\n"
        "# TYPE ais_audit_write_failures counter\n"
        f"ais_audit_write_failures {audit_failures}\n"
        "# HELP ais_upstream_reconnects Reconnect attempts to aisstream.io\n"
        "# TYPE ais_upstream_reconnects counter\n"
        f"ais_upstream_reconnects {upstream_reconnects}\n"
        "# HELP ais_slow_client_drops Clients dropped for slow consumption\n"
        "# TYPE ais_slow_client_drops counter\n"
        f"ais_slow_client_drops {slow_drops}\n"
        "# HELP ais_clients Currently connected downstream clients\n"
        "# TYPE ais_clients gauge\n"
        f"ais_clients {client_count}\n"
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


# --- /ws/maritime: browser fan-out endpoint -------------------------------


def _resolve_bbox(
    settings: Settings,
    bbox_s: Optional[float],
    bbox_w: Optional[float],
    bbox_n: Optional[float],
    bbox_e: Optional[float],
) -> tuple[float, float, float, float]:
    default = settings.bbox_default_tuple()
    s = bbox_s if bbox_s is not None else default[0]
    w = bbox_w if bbox_w is not None else default[1]
    n = bbox_n if bbox_n is not None else default[2]
    e = bbox_e if bbox_e is not None else default[3]
    if not (-90.0 <= s < n <= 90.0):
        raise ValueError("bbox lat invalid: require -90 <= s < n <= 90")
    if not (-180.0 <= w <= 180.0 and -180.0 <= e <= 180.0):
        raise ValueError("bbox lon invalid: require -180..180")
    return (s, w, n, e)


@app.websocket("/ws/maritime")
async def ws_maritime(
    websocket: WebSocket,
    bbox_s: Optional[float] = Query(default=None),
    bbox_w: Optional[float] = Query(default=None),
    bbox_n: Optional[float] = Query(default=None),
    bbox_e: Optional[float] = Query(default=None),
) -> None:
    settings: Settings = get_settings()
    try:
        bbox = _resolve_bbox(settings, bbox_s, bbox_w, bbox_n, bbox_e)
    except ValueError as exc:
        await websocket.close(code=1008, reason=str(exc))
        return

    await websocket.accept()

    mux: Multiplexer = app.state.multiplexer
    client = await mux.add_client(websocket, bbox)
    try:
        # We don't expect inbound traffic; just keep the connection alive.
        # receive_text() will raise WebSocketDisconnect when client closes.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.info("ws.client_loop_error", error=str(exc))
    finally:
        await mux.remove_client(client)

"""
Batched audit_events writer for the Sentinel Proxy.

Tile pan/zoom can produce >100 requests per second — one audit row per
tile would flood the hash-chained log. We accumulate a small in-memory
buffer and flush either on `audit_flush_tiles` count OR on
`audit_flush_seconds` elapsed (whichever comes first).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional

import structlog

from .db import DBPool, get_db_pool
from .settings import Settings

logger = structlog.get_logger(__name__)


_INSERT_AUDIT_SQL = """
INSERT INTO audit_events (
    actor_service, action, resource_type, resource_id,
    tenant_id, ols_label, payload
) VALUES (
    :actor_service, :action, :resource_type, :resource_id,
    :tenant_id, :ols_label, :payload
)
"""


class AuditBatcher:
    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        pool: Optional[DBPool] = None,
    ) -> None:
        self._settings = settings
        self._pool = pool or get_db_pool()
        self._tenant_id = tenant_id
        self._buffer: List[dict] = []
        self._lock = asyncio.Lock()
        self._flusher_task: Optional[asyncio.Task] = None
        self.writes_total = 0
        self.write_failures_total = 0

    async def start(self) -> None:
        if self._flusher_task is None:
            self._flusher_task = asyncio.create_task(
                self._flusher_loop(), name="sentinel-audit-flush"
            )

    async def stop(self) -> None:
        if self._flusher_task is not None:
            self._flusher_task.cancel()
            try:
                await self._flusher_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._flusher_task = None
        # Final flush.
        await self._flush_now()

    async def add_tile(self, layer: str, z: int, x: int, y: int) -> None:
        size = 0
        async with self._lock:
            self._buffer.append({"layer": layer, "z": z, "x": x, "y": y})
            size = len(self._buffer)
        if size >= self._settings.audit_flush_tiles:
            await self._flush_now()

    async def _flusher_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._settings.audit_flush_seconds)
                await self._flush_now()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("audit.flusher_loop_error")

    async def _flush_now(self) -> None:
        async with self._lock:
            buf = self._buffer
            self._buffer = []
        if not buf:
            return
        layers = sorted({t["layer"] for t in buf})
        zs = [t["z"] for t in buf]
        payload = {
            "tile_count": len(buf),
            "layers": layers,
            "z_min": min(zs),
            "z_max": max(zs),
            "first_ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._pool.execute(
                _INSERT_AUDIT_SQL,
                {
                    "actor_service": "sentinel-proxy",
                    "action": "tile_fetch_batch",
                    "resource_type": "sentinel/tile",
                    "resource_id": None,
                    "tenant_id": self._tenant_id,
                    "ols_label": 100,
                    "payload": json.dumps(payload),
                },
            )
            self.writes_total += 1
            logger.info("audit.flush", tile_count=len(buf), layers=layers)
        except Exception:
            self.write_failures_total += 1
            logger.exception("audit.write_failed", tile_count=len(buf))
            # Don't requeue — losing a batch's audit metadata is preferable
            # to indefinite memory growth on persistent DB failure.

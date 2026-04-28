"""
Batched audit-row writer for the AIS Multiplexer.

Contract (verified against db/schema/07_audit_compliance.sql):

  INSERT INTO audit_events (
    actor_service, action, resource_type, resource_id,
    tenant_id, ols_label, payload
  ) VALUES (
    :actor_service, :action, :resource_type, :resource_id,
    :tenant_id, :ols_label, :payload
  )

* `prev_hash` and `row_hash` are populated by trigger `trg_audit_events_hash` —
  this code MUST NOT set them.
* `actor_service` = 'ais-multiplexer'
* `action`        = 'ais_frame_batch'
* `resource_type` = 'vessel'
* `resource_id`   = NULL (batched — sample MMSIs in payload)
* `ols_label`     = 100 (OPEN, public AIS)
* `payload`       = JSON {frame_count, bbox, first_ts, last_ts, mmsi_sample}

Flush triggers (whichever fires first):
  - audit_flush_frames frames buffered (default 50)
  - audit_flush_seconds elapsed since first frame in batch (default 10s)

DB errors are logged with retry — never silently swallowed.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from .db import DBPool, DBPoolUnavailable, get_db_pool
from .settings import Settings, get_settings

logger = structlog.get_logger(__name__)


_INSERT_SQL = """
INSERT INTO audit_events (
  actor_service, action, resource_type, resource_id,
  tenant_id, ols_label, payload
) VALUES (
  :actor_service, :action, :resource_type, :resource_id,
  :tenant_id, :ols_label, :payload
)
""".strip()


@dataclass
class AuditFrame:
    mmsi: int
    ts: str
    lat: float
    lon: float


@dataclass
class _Batch:
    frames: list[AuditFrame] = field(default_factory=list)
    started_at_monotonic: float = 0.0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    tenant_id: str = "T001"


class AuditBatcher:
    """Collects frames and flushes to audit_events on size/time threshold.

    Usage::

        batcher = AuditBatcher(bbox=(53,8,56,22), tenant_id="T001")
        await batcher.start()
        ...
        await batcher.add(AuditFrame(mmsi, ts, lat, lon))
        ...
        await batcher.stop()  # flushes remaining buffer
    """

    ACTOR_SERVICE = "ais-multiplexer"
    ACTION = "ais_frame_batch"
    RESOURCE_TYPE = "vessel"
    OLS_LABEL_OPEN = 100

    def __init__(
        self,
        bbox: tuple[float, float, float, float],
        tenant_id: str = "T001",
        settings: Optional[Settings] = None,
        db_pool: Optional[DBPool] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db = db_pool or get_db_pool()
        self._bbox = bbox
        self._tenant_id = tenant_id
        self._batch = _Batch(bbox=bbox, tenant_id=tenant_id)
        self._lock = asyncio.Lock()
        self._timer_task: Optional[asyncio.Task[None]] = None
        self._stopped = asyncio.Event()
        self._writes_total = 0
        self._write_failures_total = 0

    @property
    def writes_total(self) -> int:
        return self._writes_total

    @property
    def write_failures_total(self) -> int:
        return self._write_failures_total

    async def start(self) -> None:
        if self._timer_task is None or self._timer_task.done():
            self._stopped.clear()
            self._timer_task = asyncio.create_task(
                self._timer_loop(), name="audit-flush-timer"
            )

    async def stop(self) -> None:
        self._stopped.set()
        if self._timer_task is not None:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._timer_task = None
        await self.flush()

    async def add(self, frame: AuditFrame) -> None:
        flush_now = False
        async with self._lock:
            if not self._batch.frames:
                self._batch.started_at_monotonic = time.monotonic()
            self._batch.frames.append(frame)
            if len(self._batch.frames) >= self._settings.audit_flush_frames:
                flush_now = True
        if flush_now:
            await self.flush()

    async def _timer_loop(self) -> None:
        # Periodically check if the batch has aged past audit_flush_seconds.
        # We tick at quarter the flush window (min 1s) for snappy response
        # without busy-waiting.
        tick = max(1.0, self._settings.audit_flush_seconds / 4.0)
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(tick)
                age = 0.0
                should_flush = False
                async with self._lock:
                    if self._batch.frames:
                        age = time.monotonic() - self._batch.started_at_monotonic
                        if age >= self._settings.audit_flush_seconds:
                            should_flush = True
                if should_flush:
                    await self.flush()
        except asyncio.CancelledError:
            return

    async def flush(self) -> None:
        async with self._lock:
            if not self._batch.frames:
                return
            batch = self._batch
            self._batch = _Batch(bbox=self._bbox, tenant_id=self._tenant_id)

        payload = {
            "frame_count": len(batch.frames),
            "bbox": list(batch.bbox),
            "first_ts": batch.frames[0].ts,
            "last_ts": batch.frames[-1].ts,
            # Cap sample to bound payload size; 16 MMSIs is plenty for forensics.
            "mmsi_sample": [f.mmsi for f in batch.frames[:16]],
        }
        binds = {
            "actor_service": self.ACTOR_SERVICE,
            "action": self.ACTION,
            "resource_type": self.RESOURCE_TYPE,
            "resource_id": None,
            "tenant_id": batch.tenant_id,
            "ols_label": self.OLS_LABEL_OPEN,
            "payload": json.dumps(payload),
        }

        # Retry: 3 attempts with exponential backoff. Never silently swallow.
        delay = 0.5
        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                await self._db.execute(_INSERT_SQL, binds)
                self._writes_total += 1
                logger.info(
                    "audit.flush",
                    frame_count=payload["frame_count"],
                    tenant_id=batch.tenant_id,
                    attempt=attempt,
                )
                return
            except DBPoolUnavailable as exc:
                last_err = exc
                logger.error(
                    "audit.flush.pool_unavailable",
                    error=str(exc),
                    attempt=attempt,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.error(
                    "audit.flush.failed",
                    error=str(exc),
                    attempt=attempt,
                    frame_count=payload["frame_count"],
                )
            await asyncio.sleep(delay)
            delay *= 2.0

        self._write_failures_total += 1
        logger.error(
            "audit.flush.giving_up",
            frame_count=payload["frame_count"],
            error=str(last_err) if last_err else None,
        )

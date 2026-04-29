"""
osint_cache repository — read latest payload by layer name, write a new
payload row. Schema is db/schema/10_osint_cache.sql.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import structlog

from .db import DBPool, get_db_pool

logger = structlog.get_logger(__name__)


_INSERT_SQL = """
INSERT INTO osint_cache (layer, fetched_at, payload, classification, source)
VALUES (:layer, :fetched_at, :payload, :classification, :source)
"""

_SELECT_LATEST_SQL = """
SELECT payload, fetched_at, source
  FROM osint_cache
 WHERE layer = :layer
 ORDER BY fetched_at DESC
 FETCH FIRST 1 ROWS ONLY
"""


class CacheRepo:
    """Thin async wrapper around osint_cache. Counts hits/misses for /metrics."""

    def __init__(self, pool: Optional[DBPool] = None) -> None:
        self._pool = pool or get_db_pool()
        self.hits = 0
        self.misses = 0

    async def write_payload(
        self,
        layer: str,
        payload: dict,
        classification: str,
        source: str,
        fetched_at: Optional[datetime] = None,
    ) -> None:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        await self._pool.execute(
            _INSERT_SQL,
            {
                "layer": layer,
                "fetched_at": fetched_at,
                "payload": json.dumps(payload),
                "classification": classification,
                "source": source,
            },
        )
        logger.info(
            "cache.write",
            layer=layer,
            classification=classification,
            payload_features=len(payload.get("features", [])),
        )

    async def read_latest(self, layer: str) -> Optional[dict]:
        row = await self._pool.fetchone(_SELECT_LATEST_SQL, {"layer": layer})
        if not row:
            self.misses += 1
            return None
        self.hits += 1
        payload, fetched_at, source = row
        # Oracle JSON LOB → str → dict
        if hasattr(payload, "read"):
            payload = payload.read()
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        # Stamp the fetched_at + source so callers don't have to query separately.
        payload.setdefault("fetched_at", fetched_at.isoformat() if fetched_at else None)
        payload.setdefault("source", source)
        return payload

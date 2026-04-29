"""
osint_cache repository — read latest payload by layer name (with optional
TTL freshness check), write a new payload row. Schema is
db/schema/10_osint_cache.sql.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from .db import DBPool, get_db_pool

logger = structlog.get_logger(__name__)


_INSERT_SQL = """
INSERT INTO osint_cache (layer, fetched_at, payload, classification, source)
VALUES (:layer, :fetched_at, :payload, :classification, :source)
"""

# Picks the latest row per layer. The WHERE on age is applied in Python so
# the SQL stays portable across cache_ttl_hours overrides.
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
        self.stale_drops = 0

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

    async def read_latest(
        self,
        layer: str,
        max_age_hours: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Return the latest payload for ``layer``, or None if either:
          * no row exists yet (cold cache); OR
          * ``max_age_hours`` is set and the latest row is older than that.

        The age check guards against stale data being served as "current"
        when the upstream poller has been failing for a long time.
        """
        row = await self._pool.fetchone(_SELECT_LATEST_SQL, {"layer": layer})
        if not row:
            self.misses += 1
            return None
        payload, fetched_at, source = row

        if max_age_hours is not None and fetched_at is not None:
            # Normalise to aware UTC for comparison.
            ts = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - ts > timedelta(hours=max_age_hours):
                self.stale_drops += 1
                logger.warning(
                    "cache.stale_drop",
                    layer=layer,
                    fetched_at=ts.isoformat(),
                    max_age_hours=max_age_hours,
                )
                return None

        self.hits += 1
        # Oracle JSON LOB → str → dict
        if hasattr(payload, "read"):
            payload = payload.read()
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload.setdefault("fetched_at", fetched_at.isoformat() if fetched_at else None)
        payload.setdefault("source", source)
        return payload

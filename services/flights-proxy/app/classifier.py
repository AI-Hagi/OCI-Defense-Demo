"""
Hybrid mil/civil aircraft classifier.

Lookup precedence (matches the mil_aircraft_unified view in
db/schema/11_flights_curated.sql):

  1. hex24 in mil_aircraft_curated     → ('mil', source='curated', label=operator)
  2. hex24 in mil_aircraft_mictronics  → ('mil', source='mictronics', label=description|registration)
  3. otherwise                         → ('civil', source=None, label=None)

In-process caching: each (cold) hex24 hits the DB once. Subsequent lookups
within `classifier_cache_ttl_minutes` reuse the cached verdict so a 200-
aircraft tick only does ~200 DB lookups on first run, ~0 on the next.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from .db import DBPool, get_db_pool
from .settings import Settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Verdict:
    category: str  # 'civil' | 'mil'
    source: Optional[str]  # 'curated' | 'mictronics' | None
    label: Optional[str]


_LOOKUP_SQL = """
SELECT label, source
  FROM mil_aircraft_unified
 WHERE hex24 = :hex24
"""


class Classifier:
    def __init__(
        self,
        settings: Settings,
        pool: Optional[DBPool] = None,
    ) -> None:
        self._settings = settings
        self._pool = pool or get_db_pool()
        self._cache: dict[str, tuple[Verdict, datetime]] = {}
        self._lock = asyncio.Lock()
        self.lookups_total = 0
        self.cache_hits = 0
        self.db_misses = 0  # DB lookups that returned no row → civil

    @property
    def cached_size(self) -> int:
        return len(self._cache)

    async def classify(self, hex24: str) -> Verdict:
        if not hex24:
            return Verdict(category="civil", source=None, label=None)
        key = hex24.upper()[:6]
        self.lookups_total += 1

        # Cache hit (and not expired)?
        async with self._lock:
            cached = self._cache.get(key)
            if cached:
                verdict, stamped = cached
                ttl = timedelta(minutes=self._settings.classifier_cache_ttl_minutes)
                if datetime.now(timezone.utc) - stamped < ttl:
                    self.cache_hits += 1
                    return verdict
                # Expired — fall through to refresh.

        try:
            row = await self._pool.fetchone(_LOOKUP_SQL, {"hex24": key})
        except Exception:
            # DB unavailable — fail open: default to civil but DON'T cache
            # (so a transient failure doesn't poison the in-memory store).
            logger.exception("classifier.db_error", hex24=key)
            return Verdict(category="civil", source=None, label=None)

        if row:
            label, source = row
            verdict = Verdict(category="mil", source=source, label=label)
        else:
            self.db_misses += 1
            verdict = Verdict(category="civil", source=None, label=None)

        async with self._lock:
            self._cache[key] = (verdict, datetime.now(timezone.utc))
        return verdict

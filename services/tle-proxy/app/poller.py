"""
APScheduler-driven sequential pull of CelesTrak TLE catalogs.

For each group in `settings.groups_list()` (default stations / resource /
active), the poller:
  1. GETs `{base}/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle`
  2. Parses TLE blocks via parser.parse_tle
  3. Skips the cache write if the response yielded < 1 record (empty-
     response protection, lesson from jamming-poller)
  4. Writes a dedicated osint_cache row with layer='satellites-{group}'
  5. Writes one audit_events row per group (action='layer_fetch',
     resource_type='satellites/{group}')

CelesTrak rate-limits aggressive bursts, so groups are fetched
sequentially rather than concurrently.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .audit import AuditWriter
from .cache_repo import CacheRepo
from .parser import parse_tle, records_to_payload
from .settings import Settings

logger = structlog.get_logger(__name__)


class TlePoller:
    def __init__(
        self,
        settings: Settings,
        cache: CacheRepo,
        audit: AuditWriter,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._audit = audit
        self._scheduler: Optional[AsyncIOScheduler] = None
        self.fetches_total = 0
        self.fetches_ok = 0
        self.fetches_failed = 0
        self.last_fetch_ts_iso: str = ""
        self.last_counts: dict[str, int] = {}

    async def start(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.fetch_once,
            IntervalTrigger(hours=self._settings.tle_refresh_hours),
            id="tle-fetch",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
        # Immediate first fetch — don't wait `tle_refresh_hours`.
        asyncio.create_task(self._first_fetch())

    async def _first_fetch(self) -> None:
        try:
            await self.fetch_once()
        except Exception:
            logger.exception("poller.first_fetch_crash")

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def _build_url(self, group: str) -> str:
        base = self._settings.celestrak_base_url.rstrip("/")
        return f"{base}/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"

    async def fetch_once(self) -> None:
        """
        Pull all configured groups. Each group is independent — a failure
        on one does not poison the others. Counters are per-group-summed
        for /metrics simplicity.
        """
        for group in self._settings.groups_list():
            await self._fetch_group(group)

    async def _fetch_group(self, group: str) -> None:
        self.fetches_total += 1
        url = self._build_url(group)
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"Accept": "text/plain"})
        except httpx.HTTPError as exc:
            self.fetches_failed += 1
            logger.warning("poller.network_error", group=group, url=url, error=str(exc))
            return

        if resp.status_code != 200:
            self.fetches_failed += 1
            logger.warning("poller.upstream_status", group=group, status_code=resp.status_code)
            return

        text = resp.text or ""
        if len(text.splitlines()) < 3:
            # Empty-response protection (lesson from jamming-poller): never
            # overwrite a good cache row with a near-empty TLE blob.
            self.fetches_failed += 1
            logger.warning("poller.empty_response", group=group, bytes=len(text))
            return

        records = parse_tle(text)
        if not records:
            self.fetches_failed += 1
            logger.warning("poller.parsed_zero", group=group, raw_lines=len(text.splitlines()))
            return

        fetched_at = datetime.now(timezone.utc)
        payload = records_to_payload(group, records)
        layer = f"satellites-{group}"

        try:
            await self._cache.write_payload(
                layer=layer,
                payload=payload,
                classification="OPEN",
                source="celestrak.org",
                fetched_at=fetched_at,
            )
        except Exception:
            self.fetches_failed += 1
            logger.exception("poller.cache_write_failed", group=group)
            return

        try:
            # One audit row per group — keeps UC6 compliance correlation
            # clean (resource_id encodes group name).
            await self._audit.record_fetch(
                action="layer_fetch",
                resource_type=f"satellites/{group}",
                resource_id=fetched_at.strftime("%Y-%m-%dT%H:%MZ"),
                ols_label=100,
                payload={
                    "url": url,
                    "group": group,
                    "tle_count": len(records),
                },
            )
        except Exception:
            logger.exception("poller.audit_failed", group=group)

        self.fetches_ok += 1
        self.last_fetch_ts_iso = fetched_at.isoformat()
        self.last_counts[group] = len(records)
        logger.info(
            "poller.fetch_ok", group=group, url=url, tle_count=len(records),
        )

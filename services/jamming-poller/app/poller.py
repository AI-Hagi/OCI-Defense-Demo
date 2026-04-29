"""
APScheduler-driven daily fetch of gpsjam.org → osint_cache.

Entrypoint:
    poller = JammingPoller(settings=settings, cache=cache_repo, audit=audit_writer)
    await poller.start()    # schedules + kicks off an immediate first fetch
    ...
    await poller.stop()
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
from .csv_parser import parse_csv
from .settings import Settings

logger = structlog.get_logger(__name__)


class JammingPoller:
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

    async def start(self) -> None:
        self._scheduler = AsyncIOScheduler()
        # Periodic refresh.
        self._scheduler.add_job(
            self.fetch_once,
            IntervalTrigger(hours=self._settings.refresh_hours),
            id="jamming-fetch",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
        # Immediate first fetch (don't wait `refresh_hours`).
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

    async def fetch_once(self) -> None:
        """
        One end-to-end tick: HTTP GET → CSV → GeoJSON → cache write → audit row.

        Fail modes:
          * Network / 4xx / 5xx — increment fetches_failed, no cache update,
            no audit row, log error and return. Next tick will retry.
          * Empty CSV — same as failure (we don't overwrite a good cache row
            with empty content).
        """
        self.fetches_total += 1
        url = self._url_for_today()
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            self.fetches_failed += 1
            logger.warning("poller.network_error", url=url, error=str(exc))
            return

        if resp.status_code != 200:
            self.fetches_failed += 1
            logger.warning(
                "poller.upstream_status",
                url=url,
                status_code=resp.status_code,
            )
            return

        body = resp.text or ""
        if not body.strip() or "\n" not in body:
            self.fetches_failed += 1
            logger.warning("poller.empty_body", url=url)
            return

        fetched_at = datetime.now(timezone.utc)
        try:
            payload = parse_csv(body, self._settings, fetched_at=fetched_at)
        except Exception:
            self.fetches_failed += 1
            logger.exception("poller.parse_failed", url=url)
            return

        try:
            await self._cache.write_payload(
                layer="jamming",
                payload=payload,
                classification="OPEN",
                source="gpsjam.org via ADS-B Exchange",
                fetched_at=fetched_at,
            )
        except Exception:
            self.fetches_failed += 1
            logger.exception("poller.cache_write_failed")
            return

        try:
            await self._audit.record_fetch(
                action="layer_fetch",
                resource_type="gpsjam.org/csv",
                resource_id=fetched_at.strftime("%Y-%m-%d"),
                ols_label=100,
                payload={
                    "url": url,
                    "feature_count": len(payload.get("features", [])),
                    "stats": payload.get("stats", {}),
                },
            )
        except Exception:
            # Log but don't undo the cache write — partial success is better
            # than dropping data.
            logger.exception("poller.audit_failed")

        self.fetches_ok += 1
        self.last_fetch_ts_iso = fetched_at.isoformat()
        logger.info(
            "poller.fetch_ok",
            url=url,
            features=len(payload.get("features", [])),
        )

    def _url_for_today(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._settings.gpsjam_url_template.format(date=today)

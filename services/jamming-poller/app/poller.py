"""
APScheduler-driven periodic fetch of an ADS-B feeder API → osint_cache.

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

from .aircraft_window import AircraftWindow
from .audit import AuditWriter
from .cache_repo import CacheRepo
from .nacp_aggregator import aggregate_aircraft_to_hex
from .settings import Settings

logger = structlog.get_logger(__name__)


class JammingPoller:
    def __init__(
        self,
        settings: Settings,
        cache: CacheRepo,
        audit: AuditWriter,
        window: Optional[AircraftWindow] = None,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._audit = audit
        self._window = window or AircraftWindow(max_samples=settings.window_samples)
        self._scheduler: Optional[AsyncIOScheduler] = None
        self.fetches_total = 0
        self.fetches_ok = 0
        self.fetches_failed = 0
        self.last_fetch_ts_iso: str = ""

    @property
    def window_samples(self) -> int:
        return self._window.sample_count

    @property
    def window_max_samples(self) -> int:
        return self._window.max_samples

    async def start(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.fetch_once,
            IntervalTrigger(minutes=self._settings.refresh_minutes),
            id="jamming-fetch",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
        # Immediate first fetch (don't wait `refresh_minutes`).
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
        One end-to-end tick: HTTP GET → JSON → H3 aggregation → cache write
        → audit row.

        Fail modes:
          * Network / 4xx / 5xx — increment fetches_failed, no cache update,
            no audit row, log warning. Next tick will retry. Cache stays
            with the most recent successful payload.
          * Empty `ac` array — same as failure (we don't overwrite a good
            cache row with an empty FeatureCollection).
        """
        self.fetches_total += 1
        url = self._build_url()

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            self.fetches_failed += 1
            logger.warning("poller.network_error", url=url, error=str(exc))
            return

        if resp.status_code != 200:
            self.fetches_failed += 1
            logger.warning(
                "poller.upstream_status", url=url, status_code=resp.status_code
            )
            return

        try:
            body = resp.json()
        except ValueError:
            self.fetches_failed += 1
            logger.warning("poller.upstream_non_json", url=url)
            return

        aircraft = body.get("ac") or body.get("aircraft") or []
        if not isinstance(aircraft, list) or len(aircraft) == 0:
            self.fetches_failed += 1
            logger.warning("poller.empty_aircraft", url=url, total_field=body.get("total"))
            return

        fetched_at = datetime.now(timezone.utc)

        # Push the fresh snapshot into the sliding window and aggregate over
        # the union — gives statistically meaningful per-cell totals even
        # though one upstream call only returns ~25 aircraft.
        self._window.add_snapshot(aircraft, ts=fetched_at)
        windowed = list(self._window.flat_aircraft())

        try:
            payload = aggregate_aircraft_to_hex(
                windowed, self._settings, fetched_at=fetched_at
            )
        except Exception:
            self.fetches_failed += 1
            logger.exception("poller.aggregate_failed", url=url)
            return

        # Surface the window dimensions in the payload stats so the operator
        # can see when the window is "warm" (full) vs "warming up" after
        # a pod restart.
        coverage = self._window.coverage_window()
        payload.setdefault("stats", {}).update(
            {
                "window_samples": self._window.sample_count,
                "window_max_samples": self._window.max_samples,
                "window_oldest_ts": coverage[0].isoformat() if coverage else None,
                "window_newest_ts": coverage[1].isoformat() if coverage else None,
            }
        )

        # Don't write an empty FeatureCollection — it would mask the previous
        # good payload. Keep stale data instead.
        if not payload.get("features"):
            self.fetches_failed += 1
            logger.warning(
                "poller.empty_features",
                aircraft_count=len(aircraft),
                stats=payload.get("stats"),
            )
            return

        try:
            await self._cache.write_payload(
                layer="jamming",
                payload=payload,
                classification="OPEN",
                source="adsb.lol via ADS-B Exchange community feeders",
                fetched_at=fetched_at,
            )
        except Exception:
            self.fetches_failed += 1
            logger.exception("poller.cache_write_failed")
            return

        try:
            await self._audit.record_fetch(
                action="layer_fetch",
                resource_type="adsb.lol/aircraft",
                resource_id=fetched_at.strftime("%Y-%m-%dT%H:%MZ"),
                ols_label=100,
                payload={
                    "url": url,
                    "aircraft_in_snapshot": len(aircraft),
                    "aircraft_in_window": len(windowed),
                    "features_kept": len(payload.get("features", [])),
                    "stats": payload.get("stats", {}),
                },
            )
        except Exception:
            logger.exception("poller.audit_failed")

        self.fetches_ok += 1
        self.last_fetch_ts_iso = fetched_at.isoformat()
        logger.info(
            "poller.fetch_ok",
            url=url,
            aircraft_in_snapshot=len(aircraft),
            aircraft_in_window=len(windowed),
            features_kept=len(payload.get("features", [])),
            window_samples=self._window.sample_count,
            window_max_samples=self._window.max_samples,
        )

    def _build_url(self) -> str:
        s = self._settings
        return (
            f"{s.adsb_api_base.rstrip('/')}/v2/lat/"
            f"{s.adsb_center_lat}/lon/{s.adsb_center_lon}/dist/{s.adsb_radius_nm}"
        )

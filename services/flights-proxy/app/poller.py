"""
APScheduler-driven adsb.lol fetch → classifier → two osint_cache rows
(layer='flights-civil' and layer='flights-mil').
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
from .classifier import Classifier
from .settings import Settings

logger = structlog.get_logger(__name__)


def _aircraft_to_feature(ac: dict, mil_source: Optional[str], mil_label: Optional[str]) -> Optional[dict]:
    """Convert one adsb.lol aircraft record to a GeoJSON Point Feature."""
    lat = ac.get("lat")
    lon = ac.get("lon")
    if lat is None or lon is None:
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "hex24": (ac.get("hex") or "").upper(),
            "callsign": (ac.get("flight") or "").strip() or None,
            "icao_type": ac.get("t"),
            "registration": ac.get("r"),
            "altitude_ft": ac.get("alt_baro"),
            "ground_speed_kn": ac.get("gs"),
            "track_deg": ac.get("track"),
            "squawk": ac.get("squawk"),
            "nac_p": ac.get("nac_p"),
            "mil_source": mil_source,  # 'curated' | 'mictronics' | None
            "mil_label": mil_label,    # operator name (curated) or description (mictronics)
        },
    }


class FlightsPoller:
    def __init__(
        self,
        settings: Settings,
        cache: CacheRepo,
        audit: AuditWriter,
        classifier: Classifier,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._audit = audit
        self._classifier = classifier
        self._scheduler: Optional[AsyncIOScheduler] = None
        self.fetches_total = 0
        self.fetches_ok = 0
        self.fetches_failed = 0
        self.last_fetch_ts_iso: str = ""
        self.last_civil_count = 0
        self.last_mil_count = 0

    async def start(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.fetch_once,
            IntervalTrigger(minutes=self._settings.refresh_minutes),
            id="flights-fetch",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
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

    def _build_url(self) -> str:
        s = self._settings
        return (
            f"{s.adsb_api_base.rstrip('/')}/v2/lat/"
            f"{s.adsb_center_lat}/lon/{s.adsb_center_lon}/dist/{s.adsb_radius_nm}"
        )

    async def fetch_once(self) -> None:
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
            logger.warning("poller.upstream_status", url=url, status_code=resp.status_code)
            return

        try:
            body = resp.json()
        except ValueError:
            self.fetches_failed += 1
            logger.warning("poller.upstream_non_json", url=url)
            return

        aircraft = body.get("ac") or body.get("aircraft") or []
        if not isinstance(aircraft, list) or not aircraft:
            # Don't overwrite a good cache row with empty content; let next tick retry.
            self.fetches_failed += 1
            logger.warning("poller.empty_aircraft", url=url)
            return

        fetched_at = datetime.now(timezone.utc)

        civil_features: list[dict] = []
        mil_features: list[dict] = []
        for ac in aircraft:
            verdict = await self._classifier.classify(ac.get("hex") or "")
            feat = _aircraft_to_feature(ac, verdict.source, verdict.label)
            if feat is None:
                continue
            if verdict.category == "mil":
                mil_features.append(feat)
            else:
                civil_features.append(feat)

        civil_payload = {
            "type": "FeatureCollection",
            "features": civil_features,
            "fetched_at": fetched_at.isoformat(),
            "source": "adsb.lol via ADS-B Exchange community feeders",
            "stats": {
                "aircraft_in": len(aircraft),
                "civil_count": len(civil_features),
                "mil_count": len(mil_features),
                "url": url,
            },
        }
        mil_payload = {
            "type": "FeatureCollection",
            "features": mil_features,
            "fetched_at": fetched_at.isoformat(),
            "source": "adsb.lol via ADS-B Exchange + curated/Mictronics mil-DB",
            "stats": {
                "aircraft_in": len(aircraft),
                "civil_count": len(civil_features),
                "mil_count": len(mil_features),
                "url": url,
            },
        }

        try:
            await self._cache.write_payload(
                layer="flights-civil", payload=civil_payload,
                classification="OPEN", source="adsb.lol",
                fetched_at=fetched_at,
            )
            await self._cache.write_payload(
                layer="flights-mil", payload=mil_payload,
                classification="OPEN", source="adsb.lol+curated+mictronics",
                fetched_at=fetched_at,
            )
        except Exception:
            self.fetches_failed += 1
            logger.exception("poller.cache_write_failed")
            return

        try:
            await self._audit.record_fetch(
                action="layer_fetch", resource_type="adsb.lol/aircraft",
                resource_id=fetched_at.strftime("%Y-%m-%dT%H:%MZ"),
                ols_label=100,
                payload={
                    "url": url,
                    "aircraft_in": len(aircraft),
                    "civil_count": len(civil_features),
                    "mil_count": len(mil_features),
                    "classifier_cache_size": self._classifier.cached_size,
                },
            )
        except Exception:
            logger.exception("poller.audit_failed")

        self.fetches_ok += 1
        self.last_fetch_ts_iso = fetched_at.isoformat()
        self.last_civil_count = len(civil_features)
        self.last_mil_count = len(mil_features)
        logger.info(
            "poller.fetch_ok", url=url,
            aircraft_in=len(aircraft),
            civil_count=len(civil_features),
            mil_count=len(mil_features),
        )

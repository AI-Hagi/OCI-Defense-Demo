"""
Ports loader — one-shot Overpass query → classifier → osint_cache row.

Pattern A but explicitly NOT scheduler-driven. The loader is invoked:
  * once at service start when the cache is empty or older than
    `settings.ports_cache_ttl_days`
  * on demand via /api/osint/ports/refresh (operator-triggered, gated
    by X-Internal-Token)

Empty-response protection (lesson from jamming-poller): when Overpass
returns 0 elements AND a non-empty cache exists, the loader does NOT
overwrite — the previous snapshot stays. The audit row records the
attempted upstream URL and the empty-result outcome.

Single-Responsibility (lesson from sentinel + flights): the parser /
classifier live in their own modules; this class only orchestrates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

from .audit import AuditWriter
from .cache_repo import CacheRepo
from .classifier import PortClassifier
from .settings import Settings

logger = structlog.get_logger(__name__)


def _build_overpass_query(bbox: tuple[float, float, float, float], timeout_s: int) -> str:
    """
    Overpass QL — pulls every node, way and relation tagged harbour=*
    inside the bbox. We only need centroid coordinates, which Overpass
    provides via `out center` for ways/relations.

    bbox order: south, west, north, east (Overpass convention).
    """
    s, w, n, e = bbox
    return (
        f"[out:json][timeout:{int(timeout_s)}];"
        f"("
        f'  node["harbour"]({s},{w},{n},{e});'
        f'  way["harbour"]({s},{w},{n},{e});'
        f'  relation["harbour"]({s},{w},{n},{e});'
        f");"
        f"out center tags;"
    )


def _element_lat_lon(elem: dict) -> Optional[tuple[float, float]]:
    # `node` carries lat/lon directly; `way`/`relation` use `center`.
    if "lat" in elem and "lon" in elem:
        try:
            return (float(elem["lat"]), float(elem["lon"]))
        except (TypeError, ValueError):
            return None
    center = elem.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        try:
            return (float(center["lat"]), float(center["lon"]))
        except (TypeError, ValueError):
            return None
    return None


class PortsLoader:
    def __init__(
        self,
        settings: Settings,
        cache: CacheRepo,
        audit: AuditWriter,
        classifier: PortClassifier,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._audit = audit
        self._classifier = classifier
        self.last_run_ts_iso: str = ""
        self.last_element_count = 0
        self.last_run_ok = False

    async def run(self) -> dict:
        """
        Execute one full loader pass. Returns a small status dict for
        the /refresh endpoint and structured logs.
        """
        started_at = datetime.now(timezone.utc)
        bbox = self._settings.bbox_tuple()
        url = self._settings.overpass_api_url
        query = _build_overpass_query(bbox, self._settings.overpass_timeout_seconds)

        try:
            async with httpx.AsyncClient(
                timeout=float(self._settings.overpass_timeout_seconds + 30),
                follow_redirects=True,
                # Overpass returns 406 for httpx's default user-agent
                # (`python-httpx/<ver>`) — the server seems to filter on
                # bot-like UA strings. The actual content negotiation is
                # driven by the `[out:json]` directive in the QL query, so
                # we don't send an Accept header at all and we identify as
                # a normal sovereign-proxy client.
                headers={"User-Agent": "sovdefence-ports-proxy/0.1"},
            ) as client:
                resp = await client.post(
                    url,
                    data={"data": query},
                )
        except httpx.HTTPError as exc:
            logger.warning("loader.network_error", url=url, error=str(exc))
            return await self._record_failure("network_error", started_at, url, str(exc))

        if resp.status_code != 200:
            logger.warning("loader.upstream_status", url=url, status_code=resp.status_code)
            return await self._record_failure(
                f"upstream_{resp.status_code}", started_at, url,
                f"HTTP {resp.status_code}",
            )

        try:
            body = resp.json()
        except ValueError:
            return await self._record_failure("non_json_response", started_at, url, "")

        elements = body.get("elements") or []
        if not isinstance(elements, list) or not elements:
            # Empty-response protection: keep the existing cache row if
            # one exists. We still record the audit attempt so UC6 sees
            # the failed loader pass.
            existing = await self._cache.read_latest("ports", max_age_hours=24 * 365)
            logger.warning(
                "loader.empty_response", url=url,
                cache_age_preserved=existing is not None,
            )
            return await self._record_failure("empty_response", started_at, url, "")

        # Classify every element. Curated wins on 5 km nearest-neighbor.
        features: list[dict] = []
        for elem in elements:
            coords = _element_lat_lon(elem)
            if not coords:
                continue
            lat, lon = coords
            tags = elem.get("tags") or {}
            verdict = await self._classifier.classify(lat, lon, tags)

            # Feature name: prefer the verdict's curated name, else OSM
            # tags.name, else a synthetic ID-based label.
            display_name = (
                verdict.name
                or tags.get("name")
                or f"OSM #{elem.get('id', 'unknown')}"
            )

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "osm_id": str(elem.get("id", "")),
                    "osm_type": elem.get("type", "node"),
                    "name": display_name,
                    "country": tags.get("addr:country") or tags.get("is_in:country_code") or None,
                    "port_type": verdict.port_type,
                    "source": verdict.source,
                    "curated_id": verdict.curated_id,
                    "nato_member": verdict.nato_member,
                    "bundeswehr_facility": verdict.bundeswehr_facility,
                    # Carry the upstream tag set so the operator can
                    # inspect raw OSM context in the intel panel.
                    "osm_tags": tags,
                },
            })

        payload = {
            "type": "FeatureCollection",
            "features": features,
            "fetched_at": started_at.isoformat(),
            "source": "OpenStreetMap Overpass API + ports_curated (sovereign)",
            "stats": {
                "elements_in": len(elements),
                "feature_count": len(features),
                "curated_matches": self._classifier.curated_matches,
                "osm_fallbacks": self._classifier.osm_fallbacks,
                "bbox": list(bbox),
            },
        }

        try:
            await self._cache.write_payload(
                layer="ports",
                payload=payload,
                classification="OPEN",
                source="overpass+curated",
                fetched_at=started_at,
            )
        except Exception:
            logger.exception("loader.cache_write_failed")
            return await self._record_failure("cache_write_failed", started_at, url, "")

        try:
            await self._audit.record_fetch(
                action="layer_bootstrap",
                resource_type="ports",
                resource_id=started_at.strftime("%Y-%m-%dT%H:%MZ"),
                ols_label=100,
                payload={
                    "url": url,
                    "bbox": list(bbox),
                    "elements_in": len(elements),
                    "feature_count": len(features),
                    "curated_matches": self._classifier.curated_matches,
                    "osm_fallbacks": self._classifier.osm_fallbacks,
                },
            )
        except Exception:
            logger.exception("loader.audit_failed")

        self.last_run_ts_iso = started_at.isoformat()
        self.last_element_count = len(features)
        self.last_run_ok = True
        logger.info(
            "loader.run_ok", elements_in=len(elements), features=len(features),
            curated_matches=self._classifier.curated_matches,
            osm_fallbacks=self._classifier.osm_fallbacks,
        )
        return {
            "status": "ok",
            "elements_in": len(elements),
            "feature_count": len(features),
            "curated_matches": self._classifier.curated_matches,
            "osm_fallbacks": self._classifier.osm_fallbacks,
            "started_at": started_at.isoformat(),
        }

    async def _record_failure(
        self, reason: str, started_at: datetime, url: str, detail: str,
    ) -> dict:
        try:
            await self._audit.record_fetch(
                action="layer_bootstrap",
                resource_type="ports",
                resource_id=started_at.strftime("%Y-%m-%dT%H:%MZ"),
                ols_label=100,
                payload={"url": url, "outcome": reason, "detail": detail},
            )
        except Exception:
            logger.exception("loader.audit_failed_on_failure")
        self.last_run_ok = False
        return {"status": "failed", "reason": reason, "url": url}

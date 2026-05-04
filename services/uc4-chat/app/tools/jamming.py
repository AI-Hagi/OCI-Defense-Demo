"""
jamming_query — wraps jamming-poller /api/osint/jamming/current.

The upstream returns a GeoJSON FeatureCollection (jamming zones with NACP
aggregations). The LLM gets counts per severity bucket plus up to 8
representative zones (centroid lat/lon, severity, evidence_count).
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

from ..audit import AuditWriter, ols_label_to_int

logger = structlog.get_logger(__name__)

_GERMANY_BBOX = {"bbox_s": 47.3, "bbox_w": 5.9, "bbox_n": 55.1, "bbox_e": 15.0}
_BALTIC_BBOX = {"bbox_s": 53.0, "bbox_w": 13.0, "bbox_n": 60.0, "bbox_e": 30.0}


class JammingQueryTool:
    name = "jamming_query"
    description = (
        "Liefert eine Momentaufnahme der GPS-/EW-Jamming-Lage als Zonen "
        "mit aggregierten NACP-Indikatoren (open-source, ADS-B-NACP-basiert). "
        "Optional auf Bbox eingrenzbar; Region-Shortcuts: 'germany', 'baltic'. "
        "Liefert Anzahl Zonen pro Schweregrad-Bucket plus bis zu 8 Beispiel-Zonen. "
        "Keine kinetische Bewertung — der severity-Bucket ist eine Open-Source-"
        "Heuristik aus Aircraft-NACP-Drops."
    )
    parameters = {
        "region": {
            "type": "str",
            "description": "Region-Shortcut: 'germany' | 'baltic'. Optional.",
            "required": False,
        },
        "bbox_s": {"type": "float", "description": "Süd-Lat", "required": False},
        "bbox_w": {"type": "float", "description": "West-Lon", "required": False},
        "bbox_n": {"type": "float", "description": "Nord-Lat", "required": False},
        "bbox_e": {"type": "float", "description": "Ost-Lon", "required": False},
    }

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        audit: AuditWriter,
        ols_cap: str,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._audit = audit
        self._ols_cap = ols_cap

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        bbox = self._resolve_bbox(args)
        params: dict[str, float] = dict(bbox) if bbox else {}
        url = f"{self._base_url}/api/osint/jamming/current"

        out: dict[str, Any] = {"bbox": bbox, "buckets": {}, "samples": []}
        try:
            resp = await self._http.get(url, params=params)
            if resp.status_code >= 500:
                out["error"] = f"upstream {resp.status_code}"
            else:
                payload = resp.json()
                features = payload.get("features", []) if isinstance(payload, dict) else []
                out["buckets"] = self._bucketise(features)
                out["samples"] = self._summarise(features, limit=8)
                out["total"] = len(features)
                if isinstance(payload, dict) and payload.get("error"):
                    out["upstream_error"] = payload["error"]
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"

        await self._audit.record(
            action="chat_tool_call",
            resource_type="jamming_query",
            resource_id=None,
            ols_label=ols_label_to_int(self._ols_cap),
            payload={"args": args, "bbox": bbox, "total": out.get("total", 0)},
        )
        return out

    @staticmethod
    def _resolve_bbox(args: dict[str, Any]) -> Optional[dict[str, float]]:
        region = (args.get("region") or "").lower()
        if region == "germany":
            return dict(_GERMANY_BBOX)
        if region == "baltic":
            return dict(_BALTIC_BBOX)
        keys = ("bbox_s", "bbox_w", "bbox_n", "bbox_e")
        if all(args.get(k) is not None for k in keys):
            try:
                return {k: float(args[k]) for k in keys}
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _bucketise(features: list[dict[str, Any]]) -> dict[str, int]:
        buckets: dict[str, int] = {"low": 0, "moderate": 0, "high": 0, "unknown": 0}
        for f in features:
            sev = (f.get("properties") or {}).get("severity")
            key = str(sev).lower() if sev else "unknown"
            buckets[key if key in buckets else "unknown"] += 1
        return buckets

    @staticmethod
    def _summarise(features: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in features[:limit]:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or []
            # Polygons: take centroid; Points: as-is.
            if geom.get("type") == "Polygon" and isinstance(coords, list) and coords:
                ring = coords[0] or []
                if ring:
                    avg_lon = sum(p[0] for p in ring) / len(ring)
                    avg_lat = sum(p[1] for p in ring) / len(ring)
                    lon, lat = avg_lon, avg_lat
                else:
                    lon, lat = None, None
            elif geom.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
            else:
                lon, lat = None, None
            out.append(
                {
                    "id": props.get("id") or props.get("zone_id"),
                    "lat": lat,
                    "lon": lon,
                    "severity": props.get("severity"),
                    "evidence_count": props.get("evidence_count") or props.get("aircraft_count"),
                }
            )
        return out

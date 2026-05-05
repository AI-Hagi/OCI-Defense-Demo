"""
flights_query — wraps the flights-proxy /api/osint/flights/{civil,mil}/current
endpoints into a single LLM-friendly tool.

The raw upstream is GeoJSON FeatureCollection. The LLM doesn't need 200
features back — it needs counts + a representative sample. So this tool:

  * fetches civil + mil concurrently (or just one if `kind` is set)
  * filters to the requested bbox if provided
  * returns counts per kind, plus up to 12 sample aircraft (callsign,
    registration, lat/lon, altitude, speed, military flag).

bbox semantics match flights-proxy: bbox_s / bbox_w / bbox_n / bbox_e.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
import structlog

from ..audit import AuditWriter, ols_label_to_int

logger = structlog.get_logger(__name__)

_GERMANY_BBOX = {"bbox_s": 47.3, "bbox_w": 5.9, "bbox_n": 55.1, "bbox_e": 15.0}


class FlightsQueryTool:
    name = "flights_query"
    description = (
        "Liefert eine Momentaufnahme der Luftlage. Zeigt zivile und/oder "
        "militärische Flugzeuge, optional gefiltert nach Bounding-Box "
        "(z.B. Deutschland) und nach Art (civil | mil | both). Gibt Anzahl "
        "pro Kategorie plus eine Stichprobe von bis zu 12 Maschinen zurück. "
        "Daten kommen aus dem Sovereign-Proxy auf Basis von ADS-B (Open "
        "Source). Der military-Flag basiert auf einem kurierten Klassifikator "
        "+ Mictronics-DB — keine kinetische Bewertung."
    )
    parameters = {
        "kind": {
            "type": "str",
            "description": "Kategorie: 'civil' | 'mil' | 'both'. Default 'both'.",
            "required": False,
        },
        "region": {
            "type": "str",
            "description": (
                "Optionaler Region-Shortcut. Heute unterstützt: 'germany'. "
                "Wenn gesetzt, wird die Bounding-Box automatisch ergänzt."
            ),
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
        kind = (args.get("kind") or "both").lower()
        if kind not in {"civil", "mil", "both"}:
            return {"error": f"invalid kind: {kind}"}

        bbox = self._resolve_bbox(args)

        layers: list[str] = (
            ["flights-civil", "flights-mil"]
            if kind == "both"
            else (["flights-civil"] if kind == "civil" else ["flights-mil"])
        )
        results = await asyncio.gather(
            *(self._fetch_layer(layer, bbox) for layer in layers),
            return_exceptions=True,
        )

        out: dict[str, Any] = {
            "bbox": bbox,
            "kind": kind,
            "counts": {},
            "samples": [],
        }
        for layer, payload in zip(layers, results):
            label = "civil" if layer == "flights-civil" else "mil"
            if isinstance(payload, Exception):
                out["counts"][label] = 0
                out.setdefault("errors", {})[label] = str(payload)
                continue
            features = payload.get("features", []) if isinstance(payload, dict) else []
            features = self._apply_bbox_filter(features, bbox)
            out["counts"][label] = len(features)
            out["samples"].extend(self._summarise(features, label, limit=6))

        await self._audit.record(
            action="chat_tool_call",
            resource_type="flights_query",
            resource_id=kind,
            ols_label=ols_label_to_int(self._ols_cap),
            payload={"args": args, "bbox": bbox, "counts": out["counts"]},
        )
        return out

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _resolve_bbox(self, args: dict[str, Any]) -> Optional[dict[str, float]]:
        if (args.get("region") or "").lower() == "germany":
            return dict(_GERMANY_BBOX)
        keys = ("bbox_s", "bbox_w", "bbox_n", "bbox_e")
        if all(args.get(k) is not None for k in keys):
            try:
                return {k: float(args[k]) for k in keys}
            except (TypeError, ValueError):
                return None
        return None

    async def _fetch_layer(
        self, layer: str, bbox: Optional[dict[str, float]]
    ) -> dict[str, Any]:
        # flights-proxy supports either a center+dist viewport or a bbox via
        # query params. We prefer bbox when known, else fall back to the
        # backend's curated default.
        endpoint = (
            "/api/osint/flights/civil/current"
            if layer == "flights-civil"
            else "/api/osint/flights/mil/current"
        )
        params: dict[str, float] = {}
        if bbox:
            params.update(bbox)
        url = f"{self._base_url}{endpoint}"
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _apply_bbox_filter(
        features: list[dict[str, Any]], bbox: Optional[dict[str, float]]
    ) -> list[dict[str, Any]]:
        if not bbox:
            return features
        s, w, n, e = bbox["bbox_s"], bbox["bbox_w"], bbox["bbox_n"], bbox["bbox_e"]
        out: list[dict[str, Any]] = []
        for f in features:
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates")
            if not isinstance(coords, list) or len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if s <= lat <= n and w <= lon <= e:
                out.append(f)
        return out

    @staticmethod
    def _summarise(
        features: list[dict[str, Any]], label: str, limit: int
    ) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for f in features[:limit]:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None]
            samples.append(
                {
                    "category": label,
                    "callsign": (props.get("callsign") or "").strip() or None,
                    "registration": props.get("registration") or props.get("r"),
                    "icao24": props.get("hex") or props.get("icao24"),
                    "lat": coords[1],
                    "lon": coords[0],
                    "altitude_ft": props.get("alt_baro") or props.get("altitude_ft"),
                    "speed_kt": props.get("gs") or props.get("speed_kt"),
                    "military": bool(props.get("is_mil") or label == "mil"),
                    "type": props.get("t") or props.get("type"),
                }
            )
        return samples

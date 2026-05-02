"""
ADS-B aircraft snapshot → H3-hex GeoJSON FeatureCollection.

Aggregation pipeline:
  1. For each aircraft with lat/lon, bin to an H3 cell at resolution 4.
  2. Per cell, count total aircraft seen and aircraft with NACp below the
     LOW_NACP_THRESHOLD (default 8 — i.e. positional accuracy worse than
     ~30 m on the ADS-B NACp scale 0-11).
  3. Drop "noisy" cells (total < MINIMUM_AIRCRAFT_COUNT, default 3).
  4. Classify each surviving cell green/amber/red by the low-NACp ratio.
  5. Emit one GeoJSON Feature per cell with the H3 polygon boundary.

The output schema is byte-compatible with the original csv_parser output —
the frontend (frontend/src/layers/jamming.ts) doesn't care that the
upstream changed from gpsjam.org's CSV to adsb.lol's JSON.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional

import structlog

from .settings import Settings

logger = structlog.get_logger(__name__)


def classify(low_nacp: int, total: int, settings: Settings) -> str:
    if total <= 0:
        return "noisy"
    ratio = low_nacp / total
    if ratio > settings.classify_red_threshold:
        return "red"
    if ratio >= settings.classify_amber_threshold:
        return "amber"
    return "green"


def _hex_to_polygon_coords(hex_id: str) -> List[List[float]]:
    import h3

    boundary = h3.cell_to_boundary(hex_id)
    ring = [[lon, lat] for (lat, lon) in boundary]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _hex_centroid(hex_id: str) -> tuple[float, float]:
    import h3

    lat, lon = h3.cell_to_latlng(hex_id)
    return (lat, lon)


def aggregate_aircraft_to_hex(
    aircraft: Iterable[dict],
    settings: Settings,
    fetched_at: Optional[datetime] = None,
) -> dict:
    """
    Aggregate the `ac` array from an adsb.lol/api.adsb.fi response into an
    H3-hex GeoJSON FeatureCollection. Aircraft missing lat/lon are skipped
    silently — they typically came in via MLAT or other non-position
    sources.
    """
    import h3

    fetched_at = fetched_at or datetime.now(timezone.utc)

    # Materialise the iterable so we can log a count and traverse twice.
    aircraft_list = list(aircraft)
    aircraft_in = len(aircraft_list)

    # Per-cell rolling totals.
    by_cell: dict[str, dict[str, int]] = {}
    rejected_no_position = 0

    for ac in aircraft_list:
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            rejected_no_position += 1
            continue
        try:
            cell = h3.latlng_to_cell(float(lat), float(lon), settings.h3_resolution)
        except Exception:
            rejected_no_position += 1
            continue

        # NACp scale 0-11 (ADS-B). 0 means "unknown", which we count as
        # low-NACp because the aircraft cannot vouch for positional accuracy.
        nac_p = ac.get("nac_p")
        is_low = (nac_p is None) or (
            isinstance(nac_p, (int, float)) and nac_p < settings.low_nacp_threshold
        )

        agg = by_cell.setdefault(cell, {"total": 0, "low": 0})
        agg["total"] += 1
        if is_low:
            agg["low"] += 1

    rejected_noisy = 0
    counts: dict[str, int] = {"green": 0, "amber": 0, "red": 0}
    features: list[dict] = []

    for cell, agg in by_cell.items():
        total = agg["total"]
        low = agg["low"]
        if total < settings.minimum_aircraft_count:
            rejected_noisy += 1
            continue
        try:
            ring = _hex_to_polygon_coords(cell)
            cent_lat, cent_lon = _hex_centroid(cell)
        except Exception:
            rejected_noisy += 1
            continue

        cls = classify(low, total, settings)
        if cls in counts:
            counts[cls] += 1
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "h3_index": cell,
                    "aircraft_total": total,
                    "aircraft_low_nacp": low,
                    "low_nacp_ratio": round(low / total, 4),
                    "classification_color": cls,
                    "centroid_lat": round(cent_lat, 5),
                    "centroid_lon": round(cent_lon, 5),
                },
            }
        )

    logger.info(
        "nacp.aggregated",
        aircraft_in=aircraft_in,
        cells_kept=len(features),
        rejected_noisy=rejected_noisy,
        rejected_no_position=rejected_no_position,
        counts=counts,
    )

    return {
        "type": "FeatureCollection",
        "features": features,
        "fetched_at": fetched_at.isoformat(),
        "source": "adsb.lol via ADS-B Exchange community feeders",
        "stats": {
            "aircraft_in": aircraft_in,
            "kept": len(features),
            "rejected_noisy": rejected_noisy,
            "rejected_no_position": rejected_no_position,
            "counts": counts,
        },
    }

"""
gpsjam.org CSV → GeoJSON FeatureCollection.

CSV schema (gpsjam.org as of 2026):
  hex_id              H3 cell index (resolution 4)
  aircraft_total      total aircraft observations in this cell over the window
  aircraft_low_nacp   aircraft with low NACp (positional accuracy degraded)

We compute the ratio low_nacp/total, classify into green/amber/red, drop
"noisy" cells (aircraft_total < MINIMUM_AIRCRAFT_COUNT), and emit one
GeoJSON Feature per surviving cell with H3-derived polygon geometry.
"""
from __future__ import annotations

import csv
import io
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
    """Return the [[lon, lat], ...] ring for an H3 cell (closed)."""
    import h3

    boundary = h3.cell_to_boundary(hex_id)  # list of (lat, lon) tuples
    ring = [[lon, lat] for (lat, lon) in boundary]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _hex_centroid(hex_id: str) -> tuple[float, float]:
    import h3

    lat, lon = h3.cell_to_latlng(hex_id)
    return (lat, lon)


def parse_csv(
    csv_text: str,
    settings: Settings,
    fetched_at: Optional[datetime] = None,
) -> dict:
    """
    Parse the raw CSV bytes/text into a GeoJSON FeatureCollection.

    The result is what `/api/osint/jamming/current` serves verbatim from the
    cache. `fetched_at` is recorded as a top-level field for client-side
    age display.
    """
    fetched_at = fetched_at or datetime.now(timezone.utc)
    reader = csv.DictReader(io.StringIO(csv_text))
    features: list[dict] = []
    rejected_noisy = 0
    rejected_bad_hex = 0
    counts: dict[str, int] = {"green": 0, "amber": 0, "red": 0}

    for row in reader:
        hex_id = (row.get("hex_id") or row.get("h3") or "").strip()
        if not hex_id:
            continue
        try:
            total = int(row.get("aircraft_total") or row.get("total") or 0)
            low = int(row.get("aircraft_low_nacp") or row.get("low_nacp") or 0)
        except ValueError:
            continue
        if total < settings.minimum_aircraft_count:
            rejected_noisy += 1
            continue
        try:
            ring = _hex_to_polygon_coords(hex_id)
            lat, lon = _hex_centroid(hex_id)
        except Exception:  # bad hex id, h3 raised
            rejected_bad_hex += 1
            continue

        cls = classify(low, total, settings)
        if cls in counts:
            counts[cls] += 1
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "h3_index": hex_id,
                    "aircraft_total": total,
                    "aircraft_low_nacp": low,
                    "low_nacp_ratio": round(low / total, 4),
                    "classification_color": cls,
                    "centroid_lat": round(lat, 5),
                    "centroid_lon": round(lon, 5),
                },
            }
        )

    logger.info(
        "csv.parsed",
        kept=len(features),
        rejected_noisy=rejected_noisy,
        rejected_bad_hex=rejected_bad_hex,
        counts=counts,
    )

    return {
        "type": "FeatureCollection",
        "features": features,
        "fetched_at": fetched_at.isoformat(),
        "source": "gpsjam.org via ADS-B Exchange",
        "stats": {
            "kept": len(features),
            "rejected_noisy": rejected_noisy,
            "rejected_bad_hex": rejected_bad_hex,
            "counts": counts,
        },
    }

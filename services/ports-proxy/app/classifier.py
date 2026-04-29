"""
Hybrid port classifier — curated wins, OSM-tag mapping is the fallback.

Lookup precedence:

  1. nearest-neighbor over `ports_curated` within
     `settings.ports_curated_radius_m` (default 5 km)
       → ('curated', port_type from row, name from row,
          nato_member, bundeswehr_facility flags)

  2. OSM-tag heuristic over the element's `tags` dict
       → ('osm', port_type derived from tags, name from tags.name)

The OSM heuristic checks a *priority list* of tags. Pre-flight against
the live Overpass API showed that ~99 % of harbour=* nodes carry
harbour='yes' and put the actual subtype in other tags
(`seamark:harbour:category`, `landuse`, `industrial`, `leisure`,
`mooring`). Spec-vs-reality conflict was surfaced in the audit doc
and resolved as Path A.

Port-type taxonomy:
  'commercial' — cargo / container / industrial
  'military'   — naval / military / Bundeswehr
  'fishing'    — fishing harbour
  'marina'     — yacht / pleasure
  'mixed'      — anything else (the OSM "harbour=yes" default)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from .db import DBPool, get_db_pool
from .settings import Settings

logger = structlog.get_logger(__name__)

# Tuple shape returned by the curated nearest-neighbor query.
# (id, name, port_type, nato_member, bundeswehr_facility, distance_m)
_CuratedRow = tuple[int, str, str, int, int, float]


@dataclass(frozen=True)
class Verdict:
    source: str                       # 'curated' | 'osm'
    port_type: str                    # see taxonomy
    name: str
    curated_id: Optional[int] = None  # populated when source='curated'
    nato_member: bool = False
    bundeswehr_facility: bool = False


# Curated nearest-neighbor query. SDO_NN ranks by distance; the first
# result whose distance ≤ radius is the winner. ROWNUM = 1 is unsafe
# with SDO_NN_DISTANCE — we use a CTE and FETCH FIRST 1 instead.
_CURATED_NN_SQL = """
SELECT id, name, port_type, nato_member, bundeswehr_facility,
       SDO_GEOM.SDO_DISTANCE(
         geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(:lon, :lat, NULL),
           NULL, NULL),
         0.005,
         'unit=METER'
       ) AS distance_m
  FROM ports_curated
 WHERE SDO_WITHIN_DISTANCE(
         geometry,
         SDO_GEOMETRY(2001, 4326,
           SDO_POINT_TYPE(:lon, :lat, NULL),
           NULL, NULL),
         'distance=' || :radius_m || ' unit=METER'
       ) = 'TRUE'
 ORDER BY distance_m ASC
 FETCH FIRST 1 ROWS ONLY
"""


def osm_port_type(tags: dict) -> str:
    """
    Derive a port_type from a flattened OSM tags dict.

    Priority rules — first match wins. Naval/military signals are first
    so an `harbour=yes + landuse=military` element becomes 'military'
    even when the harbour tag is non-specific.
    """
    if not isinstance(tags, dict):
        return "mixed"
    cat = (tags.get("seamark:harbour:category") or "").lower()
    landuse = (tags.get("landuse") or "").lower()
    industrial = (tags.get("industrial") or "").lower()
    leisure = (tags.get("leisure") or "").lower()
    industry = (tags.get("industry") or "").lower()
    harbour = (tags.get("harbour") or "").lower()

    # 1. Military / naval (highest priority — tagged everywhere consistently)
    if cat in ("naval", "military"):
        return "military"
    if landuse == "military":
        return "military"
    if harbour in ("naval", "military"):
        return "military"

    # 2. Fishing
    if cat == "fishing":
        return "fishing"
    if industry == "fishing":
        return "fishing"
    if harbour == "fishing":
        return "fishing"

    # 3. Marina / yacht
    if cat == "marina":
        return "marina"
    if leisure == "marina":
        return "marina"
    if harbour in ("marina", "yacht"):
        return "marina"

    # 4. Commercial
    if industrial in ("port", "cargo", "container"):
        return "commercial"
    if landuse == "industrial" and harbour:
        return "commercial"
    if harbour in ("cargo", "container", "industrial"):
        return "commercial"

    # 5. Default — generic harbour=yes or unknown subtype.
    return "mixed"


class PortClassifier:
    """
    Stateful: caches the curated row count for /metrics. The actual NN
    lookup is one round-trip to ATP per OSM element — fine for the
    one-shot loader (~5000 elements ≈ 5000 cheap spatial queries).
    """

    def __init__(
        self,
        settings: Settings,
        pool: Optional[DBPool] = None,
    ) -> None:
        self._settings = settings
        self._pool = pool or get_db_pool()
        self.curated_matches = 0
        self.osm_fallbacks = 0
        self.lookups_total = 0

    async def classify(self, lat: float, lon: float, tags: Optional[dict]) -> Verdict:
        self.lookups_total += 1
        tags = tags or {}
        # 1. Curated nearest-neighbor (5 km default).
        try:
            row = await self._pool.fetchone(
                _CURATED_NN_SQL,
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "radius_m": int(self._settings.ports_curated_radius_m),
                },
            )
        except Exception:
            # Fail-open: log, fall through to OSM-tag mapping. Don't
            # crash the loader on a transient 26ai blip.
            logger.exception("classifier.curated_lookup_failed", lat=lat, lon=lon)
            row = None

        if row:
            curated_id, name, port_type, nato, bundeswehr, dist_m = row
            if dist_m is not None and dist_m <= self._settings.ports_curated_radius_m:
                self.curated_matches += 1
                return Verdict(
                    source="curated",
                    port_type=port_type,
                    name=name,
                    curated_id=int(curated_id),
                    nato_member=bool(nato),
                    bundeswehr_facility=bool(bundeswehr),
                )

        # 2. OSM-tag heuristic.
        self.osm_fallbacks += 1
        return Verdict(
            source="osm",
            port_type=osm_port_type(tags),
            name=tags.get("name") or "",
        )

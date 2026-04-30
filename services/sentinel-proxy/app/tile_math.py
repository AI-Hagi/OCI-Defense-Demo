"""
XYZ-tile <-> Web Mercator (EPSG:3857) bbox math.

Closed-form formulas — no pyproj/shapely needed. Same convention as
OpenStreetMap / Google Maps tiles:
  zoom 0  → 1 tile covering the whole world
  zoom z  → 2^z × 2^z tiles
  origin  → (0, 0) at top-left, y grows downward

Web Mercator constants:
  R   = 6378137 m       earth radius (matches EPSG:3857)
  CIRC = 2π·R           ≈ 40,075,016.6856 m
  HALF = π·R            ≈ 20,037,508.3428 m
"""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6378137.0
HALF_CIRCUMFERENCE_M = math.pi * EARTH_RADIUS_M


def tile_to_bbox_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """
    Returns (x_min, y_min, x_max, y_max) in EPSG:3857 metres for tile (z, x, y).

    Raises ValueError if (z, x, y) is out of range.
    """
    if z < 0 or z > 30:
        raise ValueError(f"z={z} out of range [0, 30]")
    n = 1 << z  # 2 ** z
    if x < 0 or x >= n or y < 0 or y >= n:
        raise ValueError(f"tile ({z},{x},{y}) out of range; n={n}")

    tile_size_m = (2 * HALF_CIRCUMFERENCE_M) / n
    x_min = -HALF_CIRCUMFERENCE_M + x * tile_size_m
    x_max = x_min + tile_size_m
    # y axis flipped: tile y=0 is the top of the map (max latitude).
    y_max = HALF_CIRCUMFERENCE_M - y * tile_size_m
    y_min = y_max - tile_size_m
    return (x_min, y_min, x_max, y_max)


def bbox_3857_to_latlon(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Convert (x_min, y_min, x_max, y_max) in 3857 to (south, west, north, east) lat/lon."""
    x_min, y_min, x_max, y_max = bbox
    west = math.degrees(x_min / EARTH_RADIUS_M)
    east = math.degrees(x_max / EARTH_RADIUS_M)
    south = math.degrees(2 * math.atan(math.exp(y_min / EARTH_RADIUS_M)) - math.pi / 2)
    north = math.degrees(2 * math.atan(math.exp(y_max / EARTH_RADIUS_M)) - math.pi / 2)
    return (south, west, north, east)

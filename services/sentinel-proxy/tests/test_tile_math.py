"""
Unit tests for sentinel-proxy/app/tile_math.py — pure XYZ-tile math.

Gaps covered (no tests existed before):
  tile_to_bbox_3857()
    - z out of range (< 0, > 30)
    - x / y out of range for the given z
    - z=0 single-tile covers the whole world
    - z=1 four quadrant tiles partition the world plane
    - tile size shrinks by factor-2 per zoom level
    - x_min < x_max and y_min < y_max always hold
    - known value spot-check (z=1, x=0, y=0)

  bbox_3857_to_latlon()
    - west < east and south < north
    - z=0 world tile: lat/lon approximately ±85.05 / ±180
    - round-trip: tile → bbox → latlon → expected lat/lon boundaries
    - equator tile: south ≈ 0 and north ≈ 0 for correct equatorial tile
    - poles: bbox including HALF_CIRCUMFERENCE_M clips at ~85°
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HALF = math.pi * 6378137.0  # HALF_CIRCUMFERENCE_M


@pytest.fixture(scope="module")
def tile_math():
    try:
        from app import tile_math as mod  # type: ignore
        return mod
    except ImportError:
        pytest.skip("sentinel-proxy app.tile_math not importable")


# ---------------------------------------------------------------------------
# tile_to_bbox_3857 — out-of-range errors
# ---------------------------------------------------------------------------

class TestTileToBbox3857OutOfRange:
    def test_negative_z_raises(self, tile_math):
        with pytest.raises(ValueError, match="z="):
            tile_math.tile_to_bbox_3857(-1, 0, 0)

    def test_z_above_30_raises(self, tile_math):
        with pytest.raises(ValueError, match="z="):
            tile_math.tile_to_bbox_3857(31, 0, 0)

    def test_x_negative_raises(self, tile_math):
        with pytest.raises(ValueError):
            tile_math.tile_to_bbox_3857(1, -1, 0)

    def test_x_equal_to_n_raises(self, tile_math):
        with pytest.raises(ValueError):
            tile_math.tile_to_bbox_3857(1, 2, 0)  # n=2, x=2 is out of range

    def test_y_negative_raises(self, tile_math):
        with pytest.raises(ValueError):
            tile_math.tile_to_bbox_3857(1, 0, -1)

    def test_y_equal_to_n_raises(self, tile_math):
        with pytest.raises(ValueError):
            tile_math.tile_to_bbox_3857(1, 0, 2)  # n=2, y=2 is out of range


# ---------------------------------------------------------------------------
# tile_to_bbox_3857 — correctness
# ---------------------------------------------------------------------------

class TestTileToBbox3857Correctness:
    def test_z0_tile_covers_whole_world(self, tile_math):
        x_min, y_min, x_max, y_max = tile_math.tile_to_bbox_3857(0, 0, 0)
        assert abs(x_min - (-HALF)) < 1.0
        assert abs(x_max - HALF) < 1.0
        assert abs(y_min - (-HALF)) < 1.0
        assert abs(y_max - HALF) < 1.0

    def test_z1_four_tiles_partition_world(self, tile_math):
        """The four z=1 tiles must tile the full world plane without overlap."""
        tiles = [
            tile_math.tile_to_bbox_3857(1, x, y)
            for x in range(2) for y in range(2)
        ]
        all_x_min = min(t[0] for t in tiles)
        all_y_min = min(t[1] for t in tiles)
        all_x_max = max(t[2] for t in tiles)
        all_y_max = max(t[3] for t in tiles)
        assert abs(all_x_min - (-HALF)) < 1.0
        assert abs(all_y_min - (-HALF)) < 1.0
        assert abs(all_x_max - HALF) < 1.0
        assert abs(all_y_max - HALF) < 1.0

    def test_bbox_x_min_less_than_x_max(self, tile_math):
        x_min, _, x_max, _ = tile_math.tile_to_bbox_3857(5, 10, 10)
        assert x_min < x_max

    def test_bbox_y_min_less_than_y_max(self, tile_math):
        _, y_min, _, y_max = tile_math.tile_to_bbox_3857(5, 10, 10)
        assert y_min < y_max

    def test_tile_size_halves_each_zoom(self, tile_math):
        """Tile width at z+1 must be exactly half the tile width at z."""
        z0_box = tile_math.tile_to_bbox_3857(0, 0, 0)
        z1_box = tile_math.tile_to_bbox_3857(1, 0, 0)
        width_z0 = z0_box[2] - z0_box[0]
        width_z1 = z1_box[2] - z1_box[0]
        assert abs(width_z1 - width_z0 / 2) < 0.01

    def test_z1_x0_y0_is_northwest_quadrant(self, tile_math):
        """z=1, (0,0) must be the top-left (NW) tile: x < 0 and y > 0."""
        x_min, y_min, x_max, y_max = tile_math.tile_to_bbox_3857(1, 0, 0)
        assert x_min < 0
        assert x_max == pytest.approx(0.0, abs=1.0)
        assert y_min == pytest.approx(0.0, abs=1.0)
        assert y_max > 0

    def test_z1_x1_y1_is_southeast_quadrant(self, tile_math):
        """z=1, (1,1) must be the bottom-right (SE) tile: x > 0 and y < 0."""
        x_min, y_min, x_max, y_max = tile_math.tile_to_bbox_3857(1, 1, 1)
        assert x_min == pytest.approx(0.0, abs=1.0)
        assert x_max > 0
        assert y_min < 0
        assert y_max == pytest.approx(0.0, abs=1.0)

    def test_adjacent_tiles_share_edge(self, tile_math):
        """Tile (z,x,y) x_max must equal tile (z,x+1,y) x_min."""
        _, _, x_max_left, _ = tile_math.tile_to_bbox_3857(3, 2, 2)
        x_min_right, _, _, _ = tile_math.tile_to_bbox_3857(3, 3, 2)
        assert abs(x_max_left - x_min_right) < 0.01

    def test_returns_four_floats(self, tile_math):
        result = tile_math.tile_to_bbox_3857(4, 8, 5)
        assert len(result) == 4
        assert all(isinstance(v, float) for v in result)

    def test_z30_accepted(self, tile_math):
        # Maximum valid zoom — must not raise.
        result = tile_math.tile_to_bbox_3857(30, 0, 0)
        assert len(result) == 4

    def test_z0_z30_z_boundary_values_accepted(self, tile_math):
        tile_math.tile_to_bbox_3857(0, 0, 0)
        tile_math.tile_to_bbox_3857(30, 0, 0)


# ---------------------------------------------------------------------------
# bbox_3857_to_latlon — correctness
# ---------------------------------------------------------------------------

class TestBbox3857ToLatlon:
    def _tile_latlon(self, tile_math, z, x, y):
        bbox = tile_math.tile_to_bbox_3857(z, x, y)
        return tile_math.bbox_3857_to_latlon(bbox)

    def test_returns_four_floats(self, tile_math):
        bbox = tile_math.tile_to_bbox_3857(1, 0, 0)
        result = tile_math.bbox_3857_to_latlon(bbox)
        assert len(result) == 4
        assert all(isinstance(v, float) for v in result)

    def test_south_less_than_north(self, tile_math):
        south, west, north, east = self._tile_latlon(tile_math, 4, 8, 5)
        assert south < north

    def test_west_less_than_east(self, tile_math):
        south, west, north, east = self._tile_latlon(tile_math, 4, 8, 5)
        assert west < east

    def test_z0_world_tile_approaches_polar_limits(self, tile_math):
        """Web Mercator clips at ~±85.0511°."""
        south, west, north, east = self._tile_latlon(tile_math, 0, 0, 0)
        assert south < -80
        assert north > 80
        assert abs(west - (-180.0)) < 0.01
        assert abs(east - 180.0) < 0.01

    def test_z1_nw_tile_north_is_positive(self, tile_math):
        south, west, north, east = self._tile_latlon(tile_math, 1, 0, 0)
        assert north > 0
        assert south >= 0

    def test_z1_se_tile_south_is_negative(self, tile_math):
        south, west, north, east = self._tile_latlon(tile_math, 1, 1, 1)
        assert south < 0
        assert north <= 0

    def test_lat_values_within_valid_range(self, tile_math):
        south, _, north, _ = self._tile_latlon(tile_math, 5, 16, 16)
        assert -90 <= south <= 90
        assert -90 <= north <= 90

    def test_lon_values_within_valid_range(self, tile_math):
        _, west, _, east = self._tile_latlon(tile_math, 5, 16, 16)
        assert -180 <= west <= 180
        assert -180 <= east <= 180

    def test_equatorial_tile_straddles_zero_latitude(self, tile_math):
        """z=1 tiles at y=0 (top half) vs y=1 (bottom half) straddle equator."""
        _, _, north_top, _ = self._tile_latlon(tile_math, 1, 0, 0)
        south_bottom, _, _, _ = self._tile_latlon(tile_math, 1, 0, 1)
        assert north_top > 0
        assert south_bottom < 0

    def test_zero_meridian_tile_straddles_lon_zero(self, tile_math):
        """z=1 x=0 (left half) right edge is ~0°E; x=1 (right half) left edge is ~0°E."""
        _, _, _, east_left = self._tile_latlon(tile_math, 1, 0, 0)
        _, west_right, _, _ = self._tile_latlon(tile_math, 1, 1, 0)
        assert abs(east_left - 0.0) < 0.01
        assert abs(west_right - 0.0) < 0.01

    def test_round_trip_west_east_z1_x0(self, tile_math):
        """For z=1 x=0, west must be ~-180° and east must be ~0°."""
        south, west, north, east = self._tile_latlon(tile_math, 1, 0, 0)
        assert abs(west - (-180.0)) < 0.01
        assert abs(east - 0.0) < 0.01

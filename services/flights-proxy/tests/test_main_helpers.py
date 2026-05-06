"""
Pure-unit tests for helper functions in flights-proxy app/main.py.

Gaps covered (none of these have tests in test_main.py):
  - _validate_bbox()      — all-None, partial set, valid tuple, lat/lon range errors
  - _validate_viewport()  — all-None, partial set, range errors, dist clamping
  - _quantise_viewport()  — 0.1° rounding, 5-nm dist snapping, min-clamp to 5

These functions contain no I/O and can be tested without any FastAPI test client
or mock DB pool.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def _fn():
    """Import the three helper callables once per module."""
    try:
        from app.main import _validate_bbox, _validate_viewport, _quantise_viewport  # type: ignore
        return _validate_bbox, _validate_viewport, _quantise_viewport
    except ImportError:
        pytest.skip("flights-proxy app.main not importable")


# ---------------------------------------------------------------------------
# _validate_bbox
# ---------------------------------------------------------------------------

class TestValidateBbox:
    @pytest.fixture(autouse=True)
    def _load(self, _fn):
        self.fn, _, _ = _fn

    def test_all_none_returns_none(self):
        assert self.fn(None, None, None, None) is None

    def test_partial_raises_value_error(self):
        with pytest.raises(ValueError, match="bbox"):
            self.fn(53.0, None, 56.0, None)

    def test_only_s_provided_raises(self):
        with pytest.raises(ValueError, match="bbox"):
            self.fn(53.0, None, None, None)

    def test_valid_bbox_returns_tuple(self):
        result = self.fn(53.0, 9.0, 56.0, 15.0)
        assert result == (53.0, 9.0, 56.0, 15.0)

    def test_lat_s_equals_n_raises(self):
        with pytest.raises(ValueError, match="lat"):
            self.fn(54.0, 9.0, 54.0, 15.0)

    def test_lat_s_greater_than_n_raises(self):
        with pytest.raises(ValueError, match="lat"):
            self.fn(56.0, 9.0, 53.0, 15.0)

    def test_lat_out_of_range_raises(self):
        with pytest.raises(ValueError, match="lat"):
            self.fn(-91.0, 9.0, 56.0, 15.0)

    def test_lat_n_out_of_range_raises(self):
        with pytest.raises(ValueError, match="lat"):
            self.fn(53.0, 9.0, 91.0, 15.0)

    def test_lon_w_out_of_range_raises(self):
        with pytest.raises(ValueError, match="lon"):
            self.fn(53.0, -181.0, 56.0, 15.0)

    def test_lon_e_out_of_range_raises(self):
        with pytest.raises(ValueError, match="lon"):
            self.fn(53.0, 9.0, 56.0, 181.0)

    def test_boundary_values_accepted(self):
        # Exact boundary lat/lon values must be accepted.
        result = self.fn(-90.0, -180.0, 90.0, 180.0)
        assert result == (-90.0, -180.0, 90.0, 180.0)

    def test_returns_four_element_tuple(self):
        result = self.fn(48.0, 6.0, 55.0, 14.0)
        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_values_preserved_in_order(self):
        s, w, n, e = self.fn(48.0, 6.5, 55.0, 14.5)
        assert s == 48.0
        assert w == 6.5
        assert n == 55.0
        assert e == 14.5


# ---------------------------------------------------------------------------
# _validate_viewport
# ---------------------------------------------------------------------------

class TestValidateViewport:
    @pytest.fixture(autouse=True)
    def _load(self, _fn):
        _, self.fn, _ = _fn

    def test_all_none_returns_none(self):
        assert self.fn(None, None, None) is None

    def test_partial_raises_value_error(self):
        with pytest.raises(ValueError, match="viewport"):
            self.fn(54.0, None, None)

    def test_only_lat_lon_raises(self):
        with pytest.raises(ValueError, match="viewport"):
            self.fn(54.0, 10.0, None)

    def test_valid_inputs_return_tuple(self):
        lat, lon, dist = self.fn(54.0, 10.0, 100)
        assert lat == 54.0
        assert lon == 10.0
        assert dist == 100

    def test_lat_too_low_raises(self):
        with pytest.raises(ValueError, match="lat"):
            self.fn(-91.0, 10.0, 100)

    def test_lat_too_high_raises(self):
        with pytest.raises(ValueError, match="lat"):
            self.fn(91.0, 10.0, 100)

    def test_lon_too_low_raises(self):
        with pytest.raises(ValueError, match="lon"):
            self.fn(54.0, -181.0, 100)

    def test_lon_too_high_raises(self):
        with pytest.raises(ValueError, match="lon"):
            self.fn(54.0, 181.0, 100)

    def test_dist_zero_raises(self):
        with pytest.raises(ValueError, match="dist"):
            self.fn(54.0, 10.0, 0)

    def test_dist_negative_raises(self):
        with pytest.raises(ValueError, match="dist"):
            self.fn(54.0, 10.0, -5)

    def test_dist_above_250_clamped_to_250(self):
        _, _, dist = self.fn(54.0, 10.0, 500)
        assert dist == 250

    def test_dist_exactly_250_accepted(self):
        _, _, dist = self.fn(54.0, 10.0, 250)
        assert dist == 250

    def test_dist_1_is_minimum_accepted(self):
        _, _, dist = self.fn(54.0, 10.0, 1)
        assert dist == 1

    def test_lat_boundary_90_accepted(self):
        lat, _, _ = self.fn(90.0, 0.0, 50)
        assert lat == 90.0

    def test_lat_boundary_minus_90_accepted(self):
        lat, _, _ = self.fn(-90.0, 0.0, 50)
        assert lat == -90.0

    def test_lon_boundary_180_accepted(self):
        _, lon, _ = self.fn(0.0, 180.0, 50)
        assert lon == 180.0

    def test_lon_boundary_minus_180_accepted(self):
        _, lon, _ = self.fn(0.0, -180.0, 50)
        assert lon == -180.0


# ---------------------------------------------------------------------------
# _quantise_viewport
# ---------------------------------------------------------------------------

class TestQuantiseViewport:
    @pytest.fixture(autouse=True)
    def _load(self, _fn):
        _, _, self.fn = _fn

    def test_lat_rounded_to_one_decimal(self):
        lat, _, _ = self.fn(54.123, 10.0, 100)
        assert lat == 54.1

    def test_lon_rounded_to_one_decimal(self):
        _, lon, _ = self.fn(54.0, 10.678, 100)
        assert lon == 10.7

    def test_dist_snapped_to_5nm_multiple(self):
        _, _, dist = self.fn(54.0, 10.0, 123)
        assert dist == 120  # 123 // 5 * 5

    def test_dist_exactly_on_5nm_boundary_unchanged(self):
        _, _, dist = self.fn(54.0, 10.0, 100)
        assert dist == 100

    def test_small_dist_clamped_to_5(self):
        _, _, dist = self.fn(54.0, 10.0, 3)
        assert dist == 5

    def test_dist_zero_clamped_to_5(self):
        # _quantise_viewport receives an already-validated dist (>= 1),
        # but the max(5, ...) guard still applies.
        _, _, dist = self.fn(54.0, 10.0, 0)
        assert dist == 5

    def test_negative_lat_rounded_correctly(self):
        lat, _, _ = self.fn(-33.456, 0.0, 50)
        assert lat == -33.5

    def test_returns_three_element_tuple(self):
        result = self.fn(54.0, 10.0, 100)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_adjacent_camera_jiggle_hits_same_key(self):
        # Two positions differing by ~0.01° must quantise to the same key —
        # that is the documented invariant for the in-process viewport cache.
        key1 = self.fn(54.001, 10.002, 98)
        key2 = self.fn(54.009, 10.008, 102)
        assert key1 == key2

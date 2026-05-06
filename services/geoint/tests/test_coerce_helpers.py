"""
Unit tests for _coerce_platform() and _coerce_float() helpers in scenes.py.

These helpers are called on every upload but have no direct unit coverage —
they are only exercised through the endpoint, which masks edge cases such as
empty-string headers, boundary values, and non-numeric input.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException


class TestCoercePlatform:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.scenes import _coerce_platform  # type: ignore
            self.fn = _coerce_platform
        except ImportError:
            pytest.skip("scenes router not importable")

    def test_none_defaults_to_satellite(self):
        assert self.fn(None) == "satellite"

    def test_satellite_accepted(self):
        assert self.fn("satellite") == "satellite"

    def test_uav_accepted(self):
        assert self.fn("uav") == "uav"

    def test_case_insensitive_uppercase(self):
        assert self.fn("UAV") == "uav"

    def test_mixed_case_accepted(self):
        assert self.fn("Satellite") == "satellite"

    def test_whitespace_stripped(self):
        assert self.fn("  satellite  ") == "satellite"

    def test_invalid_value_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("spaceship")
        assert exc_info.value.status_code == 400

    def test_empty_string_raises_400(self):
        # Empty string is not a valid kind — the strip() leaves "" which is
        # not in _VALID_PLATFORM_KINDS.
        with pytest.raises(HTTPException) as exc_info:
            self.fn("")
        assert exc_info.value.status_code == 400

    def test_error_detail_mentions_valid_kinds(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("drone")
        assert "satellite" in exc_info.value.detail
        assert "uav" in exc_info.value.detail

    @pytest.mark.parametrize("invalid", ["helicopter", "balloon", "ship", "123"])
    def test_various_invalid_values_rejected(self, invalid):
        with pytest.raises(HTTPException):
            self.fn(invalid)


class TestCoerceFloat:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.scenes import _coerce_float  # type: ignore
            self.fn = _coerce_float
        except ImportError:
            pytest.skip("scenes router not importable")

    # --- None / empty → None ---

    def test_none_returns_none(self):
        assert self.fn(None, "X-Altitude-M", 0.0, 100_000.0) is None

    def test_empty_string_returns_none(self):
        assert self.fn("", "X-Altitude-M", 0.0, 100_000.0) is None

    # --- Valid numeric strings ---

    def test_integer_string_accepted(self):
        assert self.fn("500", "X-Altitude-M", 0.0, 100_000.0) == 500.0

    def test_float_string_accepted(self):
        assert self.fn("120.5", "X-Altitude-M", 0.0, 100_000.0) == pytest.approx(120.5)

    def test_boundary_low_accepted(self):
        assert self.fn("0.0", "X-Altitude-M", 0.0, 100_000.0) == 0.0

    def test_boundary_high_accepted(self):
        assert self.fn("100000.0", "X-Altitude-M", 0.0, 100_000.0) == 100_000.0

    def test_heading_boundary_360_accepted(self):
        assert self.fn("360.0", "X-Heading-Deg", 0.0, 360.0) == 360.0

    def test_heading_zero_accepted(self):
        assert self.fn("0", "X-Heading-Deg", 0.0, 360.0) == 0.0

    # --- Non-numeric input → 400 ---

    def test_non_numeric_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("abc", "X-Altitude-M", 0.0, 100_000.0)
        assert exc_info.value.status_code == 400

    def test_error_detail_mentions_field_name(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("not-a-number", "X-Altitude-M", 0.0, 100_000.0)
        assert "X-Altitude-M" in exc_info.value.detail

    def test_numeric_message_says_must_be_numeric(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("abc", "X-Altitude-M", 0.0, 100_000.0)
        assert "numeric" in exc_info.value.detail.lower()

    @pytest.mark.parametrize("bad", ["NaN", "inf", "1e400", "--5", "1.2.3"])
    def test_malformed_numeric_strings_rejected(self, bad):
        # float("NaN") and float("inf") succeed in Python — only out-of-range
        # matters for those; truly malformed strings raise ValueError → 400.
        try:
            result = self.fn(bad, "X-Val", 0.0, 1000.0)
            # If it didn't raise, the value must be finite and in-range.
            assert 0.0 <= result <= 1000.0
        except HTTPException as exc:
            assert exc.status_code == 400

    # --- Out-of-range → 400 ---

    def test_above_max_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("100001", "X-Altitude-M", 0.0, 100_000.0)
        assert exc_info.value.status_code == 400

    def test_below_min_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("-1", "X-Altitude-M", 0.0, 100_000.0)
        assert exc_info.value.status_code == 400

    def test_heading_above_360_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("361", "X-Heading-Deg", 0.0, 360.0)
        assert exc_info.value.status_code == 400

    def test_range_error_detail_mentions_bounds(self):
        with pytest.raises(HTTPException) as exc_info:
            self.fn("999999", "X-Altitude-M", 0.0, 100_000.0)
        detail = exc_info.value.detail
        # Detail should contain the bounds so the caller knows what's valid.
        assert "0" in detail or "100000" in detail

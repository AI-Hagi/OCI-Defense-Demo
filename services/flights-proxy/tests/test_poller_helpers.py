"""
Unit tests for pure helper functions in app/poller.py:
  - _adsb_mil_bit(ac): military dbFlags bit extraction
  - _aircraft_to_feature(ac, mil_source, mil_label): GeoJSON feature builder

These are exported from poller.py alongside FlightsPoller and are the lowest-
level functions that feed every tile served by the flights layer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _import_helpers():
    try:
        from app.poller import _adsb_mil_bit, _aircraft_to_feature
    except Exception as exc:
        pytest.skip(f"app.poller not importable: {exc}")
    return _adsb_mil_bit, _aircraft_to_feature


# ---------------------------------------------------------------------------
# _adsb_mil_bit
# ---------------------------------------------------------------------------

class TestAdsbMilBit:
    def test_returns_true_when_bit0_is_set(self):
        bit, _ = _import_helpers()
        assert bit({"dbFlags": 1}) is True

    def test_returns_true_when_multiple_bits_set(self):
        bit, _ = _import_helpers()
        # bit 0 (military) + bit 1 (ladd) = 3
        assert bit({"dbFlags": 3}) is True

    def test_returns_false_when_bit0_not_set(self):
        bit, _ = _import_helpers()
        assert bit({"dbFlags": 2}) is False

    def test_returns_false_when_dbflags_is_zero(self):
        bit, _ = _import_helpers()
        assert bit({"dbFlags": 0}) is False

    def test_returns_false_when_dbflags_is_absent(self):
        bit, _ = _import_helpers()
        assert bit({}) is False

    def test_returns_false_when_dbflags_is_none(self):
        bit, _ = _import_helpers()
        assert bit({"dbFlags": None}) is False

    def test_returns_false_when_dbflags_is_non_numeric_string(self):
        bit, _ = _import_helpers()
        assert bit({"dbFlags": "mil"}) is False

    def test_handles_string_integer_dbflags(self):
        bit, _ = _import_helpers()
        # Some sources serialise integers as strings
        assert bit({"dbFlags": "1"}) is True

    def test_handles_large_integer_with_bit0_set(self):
        bit, _ = _import_helpers()
        assert bit({"dbFlags": 255}) is True

    def test_handles_large_integer_without_bit0_set(self):
        bit, _ = _import_helpers()
        assert bit({"dbFlags": 254}) is False


# ---------------------------------------------------------------------------
# _aircraft_to_feature
# ---------------------------------------------------------------------------

class TestAircraftToFeature:
    def _sample_ac(self, **overrides) -> dict:
        base = {
            "hex": "3f8032",
            "flight": "DLH1234 ",
            "lat": 50.1,
            "lon": 8.5,
            "alt_baro": 35000,
            "gs": 450,
            "track": 90,
            "squawk": "7000",
            "nac_p": 9,
            "t": "B738",
            "r": "D-ABCD",
        }
        base.update(overrides)
        return base

    def test_returns_geojson_feature_type(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(), None, None)
        assert result is not None
        assert result["type"] == "Feature"

    def test_geometry_is_point_with_lon_lat_order(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(lat=50.1, lon=8.5), None, None)
        coords = result["geometry"]["coordinates"]
        assert coords == [8.5, 50.1]

    def test_returns_none_when_lat_missing(self):
        _, feat = _import_helpers()
        ac = self._sample_ac()
        del ac["lat"]
        assert feat(ac, None, None) is None

    def test_returns_none_when_lon_missing(self):
        _, feat = _import_helpers()
        ac = self._sample_ac()
        del ac["lon"]
        assert feat(ac, None, None) is None

    def test_hex24_is_uppercased(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(hex="3f8032"), None, None)
        assert result["properties"]["hex24"] == "3F8032"

    def test_callsign_is_stripped_of_whitespace(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(flight="DLH1234 "), None, None)
        assert result["properties"]["callsign"] == "DLH1234"

    def test_callsign_is_none_when_empty(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(flight=""), None, None)
        assert result["properties"]["callsign"] is None

    def test_mil_source_and_label_propagated(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(), "curated", "Bundeswehr")
        props = result["properties"]
        assert props["mil_source"] == "curated"
        assert props["mil_label"] == "Bundeswehr"

    def test_civil_aircraft_has_nil_mil_fields(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(), None, None)
        props = result["properties"]
        assert props["mil_source"] is None
        assert props["mil_label"] is None

    def test_altitude_and_speed_are_included(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(alt_baro=35000, gs=450), None, None)
        props = result["properties"]
        assert props["altitude_ft"] == 35000
        assert props["ground_speed_kn"] == 450

    def test_properties_include_icao_type_and_registration(self):
        _, feat = _import_helpers()
        result = feat(self._sample_ac(t="A320", r="D-AIBL"), None, None)
        props = result["properties"]
        assert props["icao_type"] == "A320"
        assert props["registration"] == "D-AIBL"

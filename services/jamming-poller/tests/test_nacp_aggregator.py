"""
Tests for app/nacp_aggregator.py — ADS-B NACp jamming aggregation pipeline.

Covers:
  - classify(): green/amber/red ratio thresholds, zero-total guard
  - aggregate_aircraft_to_hex(): empty input, aircraft missing lat/lon skipped,
    minimum_aircraft_count filter, NACp=None counts as low, valid GeoJSON shape,
    stats section completeness, low_nacp_ratio precision
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Minimal Settings stub — avoids touching env / pydantic_settings in pure unit tests
# ---------------------------------------------------------------------------

class _Settings:
    """Minimal stub matching the Settings fields used by nacp_aggregator."""
    h3_resolution: int = 4
    low_nacp_threshold: int = 8
    classify_amber_threshold: float = 0.02
    classify_red_threshold: float = 0.10
    minimum_aircraft_count: int = 3


SETTINGS = _Settings()


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

def test_classify_green_below_amber():
    from app.nacp_aggregator import classify
    # 0 / 10 = 0.0 ratio → green
    assert classify(0, 10, SETTINGS) == "green"


def test_classify_amber_at_threshold():
    from app.nacp_aggregator import classify
    # 2 / 100 = 0.02 = amber_threshold → amber
    assert classify(2, 100, SETTINGS) == "amber"


def test_classify_amber_above_threshold_below_red():
    from app.nacp_aggregator import classify
    # 5 / 100 = 0.05 → amber (> 0.02 but ≤ 0.10)
    assert classify(5, 100, SETTINGS) == "amber"


def test_classify_red_above_red_threshold():
    from app.nacp_aggregator import classify
    # 11 / 100 = 0.11 > 0.10 → red
    assert classify(11, 100, SETTINGS) == "red"


def test_classify_red_at_threshold_plus_one():
    from app.nacp_aggregator import classify
    # 10 / 100 = 0.10 → NOT > red_threshold, so amber
    assert classify(10, 100, SETTINGS) == "amber"


def test_classify_zero_total_returns_noisy():
    from app.nacp_aggregator import classify
    assert classify(0, 0, SETTINGS) == "noisy"


def test_classify_all_low_nacp_is_red():
    from app.nacp_aggregator import classify
    # 10 / 10 = 1.0 > 0.10 → red
    assert classify(10, 10, SETTINGS) == "red"


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — helpers for fake H3
# ---------------------------------------------------------------------------

_FAKE_CELL = "8429a7fffffffff"  # a valid H3 cell id at resolution 4


def _make_fake_h3(cell: str = _FAKE_CELL):
    """Return a fake h3 module that bins every aircraft to the same cell."""
    fake_h3 = MagicMock()
    fake_h3.latlng_to_cell.return_value = cell
    fake_h3.cell_to_boundary.return_value = [
        (53.0, 15.0), (53.5, 15.0), (53.5, 15.5), (53.0, 15.5),
    ]
    fake_h3.cell_to_latlng.return_value = (53.25, 15.25)
    return fake_h3


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — empty input
# ---------------------------------------------------------------------------

def test_aggregate_empty_input_returns_empty_feature_collection():
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex([], SETTINGS)

    assert result["type"] == "FeatureCollection"
    assert result["features"] == []
    assert result["stats"]["aircraft_in"] == 0
    assert result["stats"]["kept"] == 0


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — skips aircraft without position
# ---------------------------------------------------------------------------

def test_aggregate_skips_aircraft_without_lat_lon():
    aircraft = [
        {"icao": "abc123"},                         # no lat/lon
        {"icao": "def456", "lat": None, "lon": 15}, # lat is None
        {"icao": "ghi789", "lat": 53.0},            # no lon
    ]
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS)

    assert result["stats"]["rejected_no_position"] == 3
    assert result["stats"]["kept"] == 0


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — minimum aircraft count filter
# ---------------------------------------------------------------------------

def test_aggregate_filters_cells_below_minimum_count():
    # 2 aircraft in same cell, but minimum_aircraft_count = 3 → cell dropped
    aircraft = [
        {"lat": 53.0, "lon": 15.0, "nac_p": 10},
        {"lat": 53.1, "lon": 15.1, "nac_p": 10},
    ]
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS)

    assert result["stats"]["rejected_noisy"] == 1
    assert result["stats"]["kept"] == 0
    assert result["features"] == []


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — NACp=None counts as low
# ---------------------------------------------------------------------------

def test_aggregate_none_nacp_counts_as_low():
    # 3 aircraft (meets minimum), all NACp=None → all low → red cell
    aircraft = [
        {"lat": 53.0, "lon": 15.0, "nac_p": None},
        {"lat": 53.1, "lon": 15.1, "nac_p": None},
        {"lat": 53.2, "lon": 15.2, "nac_p": None},
    ]
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS)

    assert len(result["features"]) == 1
    props = result["features"][0]["properties"]
    assert props["aircraft_low_nacp"] == 3
    assert props["classification_color"] == "red"


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — high NACp aircraft all green
# ---------------------------------------------------------------------------

def test_aggregate_high_nacp_aircraft_is_green():
    # 5 aircraft, all NACp=10 (≥ threshold 8 → NOT low) → 0 low → green
    aircraft = [{"lat": 53.0, "lon": 15.0, "nac_p": 10} for _ in range(5)]
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS)

    assert len(result["features"]) == 1
    props = result["features"][0]["properties"]
    assert props["aircraft_low_nacp"] == 0
    assert props["classification_color"] == "green"


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — GeoJSON feature schema
# ---------------------------------------------------------------------------

def test_aggregate_feature_has_correct_geojson_schema():
    aircraft = [{"lat": 53.0, "lon": 15.0, "nac_p": 5} for _ in range(3)]
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS)

    assert result["type"] == "FeatureCollection"
    assert "fetched_at" in result
    assert "source" in result
    assert "stats" in result

    feat = result["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Polygon"
    assert isinstance(feat["geometry"]["coordinates"], list)

    props = feat["properties"]
    required_keys = {
        "h3_index", "aircraft_total", "aircraft_low_nacp",
        "low_nacp_ratio", "classification_color",
        "centroid_lat", "centroid_lon",
    }
    assert required_keys.issubset(props.keys())


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — fetched_at defaults to now
# ---------------------------------------------------------------------------

def test_aggregate_uses_provided_fetched_at():
    aircraft = [{"lat": 53.0, "lon": 15.0, "nac_p": 5} for _ in range(3)]
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS, fetched_at=ts)

    assert result["fetched_at"] == ts.isoformat()


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — low_nacp_ratio precision
# ---------------------------------------------------------------------------

def test_aggregate_low_nacp_ratio_rounded_to_4_decimal_places():
    # 1 low out of 3 = 0.3333... → rounded to 4 places = 0.3333
    aircraft = [
        {"lat": 53.0, "lon": 15.0, "nac_p": 2},   # low
        {"lat": 53.1, "lon": 15.1, "nac_p": 10},  # high
        {"lat": 53.2, "lon": 15.2, "nac_p": 10},  # high
    ]
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS)

    props = result["features"][0]["properties"]
    ratio_str = str(props["low_nacp_ratio"])
    decimal_places = len(ratio_str.split(".")[-1]) if "." in ratio_str else 0
    assert decimal_places <= 4


# ---------------------------------------------------------------------------
# aggregate_aircraft_to_hex — counts by classification
# ---------------------------------------------------------------------------

def test_aggregate_stats_counts_match_features():
    aircraft = [{"lat": 53.0, "lon": 15.0, "nac_p": 5} for _ in range(3)]
    with patch.dict(sys.modules, {"h3": _make_fake_h3()}):
        from app.nacp_aggregator import aggregate_aircraft_to_hex
        result = aggregate_aircraft_to_hex(aircraft, SETTINGS)

    total_counted = sum(result["stats"]["counts"].values())
    assert total_counted == len(result["features"])

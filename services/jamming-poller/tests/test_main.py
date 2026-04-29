"""
Mock-first endpoint tests for jamming-poller.

Tests:
  * /healthz returns a JSON body with "status"
  * NACp aggregator: aircraft list → GeoJSON FeatureCollection with the
    expected classifications and noisy-cell filtering
  * /api/osint/jamming/current returns a FeatureCollection (or 503 cold-cache)
  * /api/osint/jamming/current rejects partial bbox query with 400
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------
def test_healthz_shape(client: Any) -> None:
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    assert "status" in body
    assert body.get("service") == "jamming-poller"


# ---------------------------------------------------------------------------
# NACp aggregator — pure unit, no DB / no HTTP
# ---------------------------------------------------------------------------
def test_nacp_aggregator_classifies_and_filters(mock_db: Any) -> None:  # noqa: ARG001
    from app import nacp_aggregator
    from app.settings import get_settings

    settings = get_settings()

    # Build a deterministic aircraft list across three distinct positions
    # (so they bin into different H3 cells at resolution 4) plus one
    # mostly-empty cell that should be filtered out as noisy.
    def _ac(lat: float, lon: float, nac_p: int | None) -> dict:
        return {"hex": "abcdef", "lat": lat, "lon": lon, "nac_p": nac_p}

    aircraft = []
    # Cell A — Frankfurt area, 100 aircraft, 0 low-NACp → green (0%).
    aircraft += [_ac(50.11, 8.68, 9) for _ in range(100)]
    # Cell B — Berlin area, 100 aircraft, 5 low-NACp → amber (5%).
    aircraft += [_ac(52.52, 13.40, 9) for _ in range(95)]
    aircraft += [_ac(52.52, 13.40, 5) for _ in range(5)]
    # Cell C — Munich area, 100 aircraft, 25 low-NACp → red (25%).
    aircraft += [_ac(48.13, 11.58, 9) for _ in range(75)]
    aircraft += [_ac(48.13, 11.58, 4) for _ in range(25)]
    # Cell D — Hamburg area, only 2 aircraft → noisy, dropped.
    aircraft += [_ac(53.55, 9.99, 9), _ac(53.55, 9.99, 9)]
    # Aircraft without lat/lon — rejected silently.
    aircraft += [{"hex": "deadbe", "nac_p": 9}]

    out = nacp_aggregator.aggregate_aircraft_to_hex(aircraft, settings)
    assert out["type"] == "FeatureCollection"

    # Three surviving cells (Frankfurt / Berlin / Munich); Hamburg dropped.
    feats = out["features"]
    assert len(feats) == 3
    classes = sorted(f["properties"]["classification_color"] for f in feats)
    assert classes == ["amber", "green", "red"]

    # Stats reflect the noisy + no-position drops.
    stats = out["stats"]
    assert stats["aircraft_in"] == len(aircraft)
    assert stats["rejected_noisy"] == 1
    assert stats["rejected_no_position"] == 1

    # Each feature carries the wire schema.
    for feat in feats:
        ring = feat["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1]  # polygon ring closes
        assert "h3_index" in feat["properties"]
        assert "centroid_lat" in feat["properties"]
        assert "low_nacp_ratio" in feat["properties"]


def test_nacp_treats_missing_nacp_as_low(mock_db: Any) -> None:  # noqa: ARG001
    from app import nacp_aggregator
    from app.settings import get_settings

    settings = get_settings()
    # 10 aircraft over a single point, all with nac_p=None → 100% low → red.
    aircraft = [{"lat": 50.11, "lon": 8.68, "nac_p": None} for _ in range(10)]
    out = nacp_aggregator.aggregate_aircraft_to_hex(aircraft, settings)
    feats = out["features"]
    assert len(feats) == 1
    assert feats[0]["properties"]["classification_color"] == "red"
    assert feats[0]["properties"]["low_nacp_ratio"] == 1.0


# ---------------------------------------------------------------------------
# /api/osint/jamming/current — integration via TestClient + mocked DB
# ---------------------------------------------------------------------------
def test_jamming_current_cold_cache_returns_503(client: Any) -> None:
    resp = client.get("/api/osint/jamming/current")
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    if resp.status_code == 503:
        assert body.get("error") == "no_cache_yet"
        assert body.get("type") == "FeatureCollection"
        assert body.get("features") == []
    else:
        assert body.get("type") == "FeatureCollection"


def test_jamming_current_partial_bbox_400(client: Any) -> None:
    resp = client.get("/api/osint/jamming/current?bbox_s=53&bbox_w=8")
    assert resp.status_code == 400
    assert "bbox" in resp.json().get("error", "")


# ---------------------------------------------------------------------------
# Sliding-window accumulator — pure unit
# ---------------------------------------------------------------------------
def test_aircraft_window_caps_and_flat_iter(mock_db: Any) -> None:  # noqa: ARG001
    from app.aircraft_window import AircraftWindow

    w = AircraftWindow(max_samples=3)
    assert w.sample_count == 0
    assert not w.is_full
    assert w.coverage_window() is None

    w.add_snapshot([{"hex": "a"}, {"hex": "b"}])
    w.add_snapshot([{"hex": "c"}])
    assert w.sample_count == 2
    assert list(w.flat_aircraft()) == [{"hex": "a"}, {"hex": "b"}, {"hex": "c"}]

    # Push past the cap — oldest sample is evicted.
    w.add_snapshot([{"hex": "d"}])
    w.add_snapshot([{"hex": "e"}])
    assert w.sample_count == 3
    assert w.is_full
    flat = list(w.flat_aircraft())
    # First snapshot ([a, b]) should be gone.
    hexes = [a["hex"] for a in flat]
    assert "a" not in hexes
    assert "b" not in hexes
    assert hexes == ["c", "d", "e"]
    cov = w.coverage_window()
    assert cov is not None
    assert cov[0] <= cov[1]


def test_aircraft_window_rejects_invalid_size(mock_db: Any) -> None:  # noqa: ARG001
    from app.aircraft_window import AircraftWindow

    import pytest as _pytest
    with _pytest.raises(ValueError):
        AircraftWindow(max_samples=0)

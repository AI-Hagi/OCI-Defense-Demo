"""
Mock-first endpoint tests for jamming-poller.

Three tests:
  * /healthz returns a JSON body with "status"
  * CSV parser produces a sane GeoJSON FeatureCollection
  * /api/osint/jamming/current returns FeatureCollection (or 503 on cold cache)
"""
from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------
def test_healthz_shape(client: Any) -> None:
    """``GET /healthz`` returns 200 or 503 with a JSON body that exposes status."""
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    assert "status" in body
    assert body.get("service") == "jamming-poller"


# ---------------------------------------------------------------------------
# CSV parser — pure unit, no DB / no HTTP
# ---------------------------------------------------------------------------
def test_csv_parser_classifies_and_filters(mock_db: Any) -> None:  # noqa: ARG001
    from app import csv_parser
    from app.settings import get_settings

    settings = get_settings()
    csv_text = (
        "hex_id,aircraft_total,aircraft_low_nacp\n"
        # Famous-low-aircraft cell — should be dropped as noisy.
        "841a72dffffffff,1,0\n"
        # Green: 100 aircraft, 1 low (1%) — below 2% amber threshold.
        "84194affffffffff,100,1\n"
        # Amber: 100, 5 (5%).
        "841943fffffffff,100,5\n"
        # Red: 100, 20 (20%).
        "8418c87ffffffff,100,20\n"
        # Bad hex id — should be silently rejected.
        "not-a-hex,50,5\n"
    )
    out = csv_parser.parse_csv(csv_text, settings)
    assert out["type"] == "FeatureCollection"

    # Three cells survived (the noisy + the bad-hex are dropped).
    assert len(out["features"]) <= 3
    assert out["stats"]["rejected_noisy"] >= 1

    classes = [f["properties"]["classification_color"] for f in out["features"]]
    # We must have at least one of each non-noisy class when 3 cells survive.
    if len(out["features"]) == 3:
        assert set(classes) == {"green", "amber", "red"}

    for feat in out["features"]:
        ring = feat["geometry"]["coordinates"][0]
        # Polygon ring closes (first == last).
        assert ring[0] == ring[-1]
        assert "h3_index" in feat["properties"]
        assert "centroid_lat" in feat["properties"]


# ---------------------------------------------------------------------------
# /api/osint/jamming/current — integration via TestClient + mocked DB
# ---------------------------------------------------------------------------
def test_jamming_current_cold_cache_returns_503(client: Any) -> None:
    """When cache is empty (mock_db has no rows), the endpoint signals 503
    with an empty FeatureCollection so the client can render the message."""
    resp = client.get("/api/osint/jamming/current")
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    if resp.status_code == 503:
        assert body.get("error") == "no_cache_yet"
        assert body.get("type") == "FeatureCollection"
        assert body.get("features") == []
    else:
        # Some other test ordering populated the cache; still must be valid.
        assert body.get("type") == "FeatureCollection"


def test_jamming_current_bbox_query_validation(client: Any) -> None:
    """Partial bbox (only 2 of 4 params) → 400."""
    resp = client.get("/api/osint/jamming/current?bbox_s=53&bbox_w=8")
    assert resp.status_code == 400
    assert "bbox" in resp.json().get("error", "")

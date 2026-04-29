"""Endpoint tests for ports-proxy."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def test_healthz_shape(client: Any) -> None:
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body.get("service") == "ports-proxy"
    assert "status" in body


def test_current_with_seeded_cache_returns_payload(
    mock_db: Any, client: Any,
) -> None:
    seed = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [9.9836, 53.5418]},
            "properties": {
                "osm_id": "100", "name": "Hamburg",
                "port_type": "commercial", "source": "curated",
                "curated_id": 1001, "nato_member": True,
            },
        }],
        "stats": {"feature_count": 1},
    }
    mock_db.cache_latest["ports"] = (
        json.dumps(seed),
        datetime.now(timezone.utc),
        "overpass+curated",
    )
    resp = client.get("/api/osint/ports/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("type") == "FeatureCollection"
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["source"] == "curated"


def test_refresh_disabled_when_token_unset(client: Any) -> None:
    """
    PORTS_INTERNAL_TOKEN is unset by default in tests. /refresh must
    return 503 (refresh disabled) — it's an opt-in management endpoint.
    """
    resp = client.post("/api/osint/ports/refresh")
    assert resp.status_code == 503
    body = resp.json()
    assert body.get("error") == "refresh_disabled"

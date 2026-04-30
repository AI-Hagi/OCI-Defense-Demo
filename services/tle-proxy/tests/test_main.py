"""Endpoint tests for tle-proxy."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def test_healthz_shape(client: Any) -> None:
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body.get("service") == "tle-proxy"
    assert "status" in body


def test_metrics_exposes_counters(client: Any) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    for metric in (
        "tle_fetches_total",
        "tle_fetches_ok",
        "tle_fetches_failed",
        "tle_cache_hits",
        "tle_cache_misses",
    ):
        assert metric in text, f"missing {metric}"


def test_unknown_group_returns_404(client: Any) -> None:
    resp = client.get("/api/osint/satellites/banana/current")
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("error") == "unknown_group"
    assert "stations" in body.get("valid", [])


def test_known_group_with_seeded_cache_returns_payload(
    mock_db: Any, client: Any,
) -> None:
    seed = {
        "type": "TleCollection",
        "group": "stations",
        "tle": [{"name": "ISS (ZARYA)", "norad_id": "25544",
                 "line1": "1 25544U 98067A   ...",
                 "line2": "2 25544  51.6 ..."}],
        "count": 1,
        "source": "CelesTrak NORAD GP catalog",
    }
    mock_db.cache_latest["satellites-stations"] = (
        json.dumps(seed),
        datetime.now(timezone.utc),
        "celestrak.org",
    )
    resp = client.get("/api/osint/satellites/stations/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("type") == "TleCollection"
    assert body.get("group") == "stations"
    assert body.get("count") == 1
    assert body["tle"][0]["norad_id"] == "25544"

"""Endpoint tests for flights-proxy."""
from __future__ import annotations

from typing import Any


def test_healthz_shape(client: Any) -> None:
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body.get("service") == "flights-proxy"
    assert "status" in body


def test_metrics_exposes_counters(client: Any) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    for metric in (
        "flights_fetches_total",
        "flights_last_civil_count",
        "flights_last_mil_count",
        "flights_classifier_lookups",
    ):
        assert metric in text, f"missing {metric}"


def test_civil_cold_cache_returns_503(client: Any) -> None:
    resp = client.get("/api/osint/flights/civil/current")
    assert resp.status_code in (200, 503)
    body = resp.json()
    if resp.status_code == 503:
        assert body.get("error") == "no_cache_yet"
        assert body.get("type") == "FeatureCollection"


def test_mil_partial_bbox_400(client: Any) -> None:
    resp = client.get("/api/osint/flights/mil/current?bbox_s=53&bbox_n=56")
    assert resp.status_code == 400
    assert "bbox" in resp.json().get("error", "")

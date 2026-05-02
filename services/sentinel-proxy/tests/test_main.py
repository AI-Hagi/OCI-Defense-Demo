"""
Endpoint tests for sentinel-proxy.

Tests:
  * /healthz JSON shape (200 or 503 with status)
  * /metrics exposes the named counters
  * /api/osint/sentinel/layers returns default_layer + layers list
  * Tile coord → 3857 bbox closed-form math
"""
from __future__ import annotations

from typing import Any

import pytest


def test_healthz_shape(client: Any) -> None:
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body.get("service") == "sentinel-proxy"
    assert "status" in body


def test_metrics_exposes_counters(client: Any) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    for metric in (
        "sentinel_token_refreshes",
        "sentinel_token_refresh_failures",
        "sentinel_audit_writes",
        "sentinel_audit_write_failures",
    ):
        assert metric in body, f"missing {metric} in /metrics body"


def test_layers_endpoint_returns_default_layer(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the WMS capabilities call so we don't hit the network."""
    from app import main as app_main

    # Mirrors the real Sentinel Hub capabilities shape (verified manually):
    # the parent <Layer> has no <Name> — only <Title> and <CRS>... — and
    # the children sit at the same nesting level. Our regex parser relies
    # on this structure (non-greedy `<Layer.*?</Layer>` with an outer that
    # lacks <Name> so it is filtered out as the no-name root).
    async def _fake_caps(*_args: Any, **_kwargs: Any) -> str:
        return """<?xml version="1.0"?>
<WMS_Capabilities>
  <Capability>
    <Layer>
      <Title>Sentinel Hub WMS</Title>
      <CRS>EPSG:3857</CRS>
      <Layer><Name>TRUE-COLOR-HIGHLIGHT-OPTIMIZED</Name><Title>True Color Highlight</Title></Layer>
      <Layer><Name>NDVI</Name><Title>NDVI</Title></Layer>
    </Layer>
  </Capability>
</WMS_Capabilities>
"""

    monkeypatch.setattr(app_main, "fetch_capabilities", _fake_caps, raising=True)

    resp = client.get("/api/osint/sentinel/layers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_layer"] == "TRUE-COLOR-HIGHLIGHT-OPTIMIZED"
    names = [l["name"] for l in body["layers"]]
    assert "TRUE-COLOR-HIGHLIGHT-OPTIMIZED" in names
    assert "NDVI" in names


def test_tile_math_zoom0_world_bbox(mock_db: Any) -> None:  # noqa: ARG001
    from app.tile_math import tile_to_bbox_3857, HALF_CIRCUMFERENCE_M

    bbox = tile_to_bbox_3857(0, 0, 0)
    x_min, y_min, x_max, y_max = bbox
    assert abs(x_min - (-HALF_CIRCUMFERENCE_M)) < 1.0
    assert abs(x_max - HALF_CIRCUMFERENCE_M) < 1.0
    assert abs(y_min - (-HALF_CIRCUMFERENCE_M)) < 1.0
    assert abs(y_max - HALF_CIRCUMFERENCE_M) < 1.0


def test_tile_math_rejects_out_of_range(mock_db: Any) -> None:  # noqa: ARG001
    from app.tile_math import tile_to_bbox_3857

    with pytest.raises(ValueError):
        tile_to_bbox_3857(2, 4, 0)  # n=4 ⇒ x in [0..3]
    with pytest.raises(ValueError):
        tile_to_bbox_3857(-1, 0, 0)

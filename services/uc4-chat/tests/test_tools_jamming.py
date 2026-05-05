"""Smoke tests for JammingQueryTool against a mocked jamming-poller."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.audit import AuditWriter
from app.db import DBPool
from app.tools.jamming import JammingQueryTool


class _NoopPool(DBPool):
    def is_available(self) -> bool:  # type: ignore[override]
        return False


def _audit() -> AuditWriter:
    return AuditWriter(tenant_id="T001", pool=_NoopPool())


def _zone(zone_id: str, lat: float, lon: float, severity: str, evidence: int) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon - 0.1, lat - 0.1],
                    [lon + 0.1, lat - 0.1],
                    [lon + 0.1, lat + 0.1],
                    [lon - 0.1, lat + 0.1],
                    [lon - 0.1, lat - 0.1],
                ]
            ],
        },
        "properties": {
            "id": zone_id,
            "severity": severity,
            "evidence_count": evidence,
        },
    }


@pytest.mark.asyncio
async def test_germany_region_buckets_severity_and_returns_centroids() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            _zone("Z1", 50.0, 8.0, "high", 12),
            _zone("Z2", 51.0, 9.0, "moderate", 4),
            _zone("Z3", 52.5, 13.4, "moderate", 5),
            _zone("Z4", 49.0, 11.0, "low", 1),
        ],
    }

    captured: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.url.params))
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://j") as http:
        tool = JammingQueryTool(http=http, base_url="http://j", audit=_audit(), ols_cap="OFFEN")
        out = await tool.run({"region": "germany"})

    # Bbox forwarded as query params
    assert captured[0]["bbox_s"] == "47.3"
    assert captured[0]["bbox_e"] == "15.0"

    assert out["total"] == 4
    assert out["buckets"]["high"] == 1
    assert out["buckets"]["moderate"] == 2
    assert out["buckets"]["low"] == 1
    assert out["buckets"]["unknown"] == 0
    assert len(out["samples"]) == 4
    # Centroid calc should produce something near the input lat/lon.
    sample = next(s for s in out["samples"] if s["id"] == "Z3")
    assert abs(sample["lat"] - 52.5) < 0.5
    assert abs(sample["lon"] - 13.4) < 0.5


@pytest.mark.asyncio
async def test_upstream_503_recorded_as_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"features": [], "error": "no_cache_yet"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://j") as http:
        tool = JammingQueryTool(http=http, base_url="http://j", audit=_audit(), ols_cap="OFFEN")
        out = await tool.run({})
    assert out["error"] == "upstream 503"


@pytest.mark.asyncio
async def test_unknown_severity_falls_into_unknown_bucket() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [13.0, 53.0]},
                "properties": {"id": "ZX", "severity": "weird"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [13.0, 53.0]},
                "properties": {"id": "ZY"},
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://j") as http:
        tool = JammingQueryTool(http=http, base_url="http://j", audit=_audit(), ols_cap="OFFEN")
        out = await tool.run({})
    assert out["buckets"]["unknown"] == 2

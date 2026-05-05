"""Smoke tests for FlightsQueryTool against a mocked flights-proxy."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.audit import AuditWriter
from app.db import DBPool
from app.tools.flights import FlightsQueryTool


class _NoopPool(DBPool):
    """Pool that always reports unavailable so audit writes are skipped."""

    def is_available(self) -> bool:  # type: ignore[override]
        return False


def _audit() -> AuditWriter:
    return AuditWriter(tenant_id="T001", pool=_NoopPool())


def _civil_payload(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features, "_layer": "flights-civil"}


def _mil_payload(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features, "_layer": "flights-mil"}


def _feature(callsign: str, lat: float, lon: float, *, mil: bool = False) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "callsign": callsign,
            "is_mil": mil,
            "alt_baro": 32000,
            "gs": 420,
            "hex": callsign.lower(),
        },
    }


@pytest.mark.asyncio
async def test_germany_region_calls_both_layers_and_filters_bbox() -> None:
    civil = [
        _feature("DLH123", 50.0, 8.5),  # Frankfurt — inside DE bbox
        _feature("BAW900", 51.0, 1.0),  # London — outside DE bbox
    ]
    mil = [
        _feature("GAF071", 52.5, 13.4, mil=True),  # Berlin — inside
    ]
    civil_calls = mil_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal civil_calls, mil_calls
        if "civil" in request.url.path:
            civil_calls += 1
            return httpx.Response(200, json=_civil_payload(civil))
        if "mil" in request.url.path:
            mil_calls += 1
            return httpx.Response(200, json=_mil_payload(mil))
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://flights") as http:
        tool = FlightsQueryTool(
            http=http,
            base_url="http://flights",
            audit=_audit(),
            ols_cap="OFFEN",
        )
        out = await tool.run({"region": "germany", "kind": "both"})

    assert civil_calls == 1 and mil_calls == 1
    assert out["bbox"]["bbox_s"] == pytest.approx(47.3)
    assert out["counts"]["civil"] == 1  # London filtered out
    assert out["counts"]["mil"] == 1
    samples = {s["callsign"] for s in out["samples"]}
    assert samples == {"DLH123", "GAF071"}
    assert any(s["military"] for s in out["samples"] if s["callsign"] == "GAF071")


@pytest.mark.asyncio
async def test_kind_mil_only_skips_civil_layer() -> None:
    mil = [_feature("GAF071", 52.5, 13.4, mil=True)]
    civil_calls = 0
    mil_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal civil_calls, mil_calls
        if "civil" in request.url.path:
            civil_calls += 1
            return httpx.Response(200, json=_civil_payload([]))
        if "mil" in request.url.path:
            mil_calls += 1
            return httpx.Response(200, json=_mil_payload(mil))
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x") as http:
        tool = FlightsQueryTool(
            http=http, base_url="http://x", audit=_audit(), ols_cap="OFFEN"
        )
        out = await tool.run({"kind": "mil"})

    assert civil_calls == 0
    assert mil_calls == 1
    assert "civil" not in out["counts"]
    assert out["counts"]["mil"] == 1


@pytest.mark.asyncio
async def test_invalid_kind_returns_error_dict() -> None:
    async with httpx.AsyncClient() as http:
        tool = FlightsQueryTool(
            http=http, base_url="http://x", audit=_audit(), ols_cap="OFFEN"
        )
        out = await tool.run({"kind": "spaceships"})
    assert out == {"error": "invalid kind: spaceships"}


@pytest.mark.asyncio
async def test_upstream_5xx_records_error_per_layer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "civil" in request.url.path:
            return httpx.Response(503, text="upstream cold")
        return httpx.Response(200, json=_mil_payload([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x") as http:
        tool = FlightsQueryTool(
            http=http, base_url="http://x", audit=_audit(), ols_cap="OFFEN"
        )
        out = await tool.run({"region": "germany"})

    assert out["counts"]["civil"] == 0
    assert "errors" in out and "civil" in out["errors"]
    assert out["counts"]["mil"] == 0

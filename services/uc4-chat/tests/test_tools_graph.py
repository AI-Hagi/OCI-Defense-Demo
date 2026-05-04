"""Smoke tests for GraphQueryTool against a mocked osint-fusion proxy."""
from __future__ import annotations

import json

import httpx
import pytest

from app.audit import AuditWriter
from app.db import DBPool
from app.tools.graph import GraphQueryTool


class _NoopPool(DBPool):
    def is_available(self) -> bool:  # type: ignore[override]
        return False


def _audit() -> AuditWriter:
    return AuditWriter(tenant_id="T001", pool=_NoopPool())


@pytest.mark.asyncio
async def test_multi_source_pattern_forwards_args_and_caps_samples() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "request_id": "abc-123",
                "duration_ms": 42.0,
                "ols_cap_applied": 50,
                "ols_cap_label": "NFD",
                "data": {
                    "entities": [
                        {
                            "entity_kind": "vessel",
                            "canonical_id": f"V{i:03d}",
                            "display_name": f"Vessel {i}",
                            "corr_count": 3,
                        }
                        for i in range(20)
                    ]
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://osint") as http:
        tool = GraphQueryTool(
            http=http,
            proxy_base_url="http://osint",
            audit=_audit(),
            ols_cap="NFD",
        )
        out = await tool.run(
            {
                "pattern": "multi_source_entity",
                "hours": 48,
                "min_correlations": 3,
                "entity_kind": "vessel",
            }
        )

    # Header propagation
    assert captured["headers"].get("x-ols-label-max") == "NFD"
    body = captured["body"]
    assert body["pattern"] == "multi_source_entity"
    assert body["args"]["hours"] == 48
    assert body["args"]["min_correlations"] == 3
    assert body["args"]["entity_kind"] == "vessel"

    # Output trimming + envelope passthrough
    assert out["count"] == 20
    assert len(out["samples"]) == 15
    assert out["request_id"] == "abc-123"
    assert out["ols_cap_label"] == "NFD"


@pytest.mark.asyncio
async def test_unknown_pattern_short_circuits_without_http_call() -> None:
    calls = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"entities": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x") as http:
        tool = GraphQueryTool(
            http=http, proxy_base_url="http://x", audit=_audit(), ols_cap="OFFEN"
        )
        out = await tool.run({"pattern": "deep_dream"})

    assert calls == 0
    assert "error" in out and "deep_dream" in out["error"]


@pytest.mark.asyncio
async def test_upstream_403_returned_as_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"title": "forbidden", "detail": "OLS cap exceeded"},
            headers={"content-type": "application/problem+json"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x") as http:
        tool = GraphQueryTool(
            http=http, proxy_base_url="http://x", audit=_audit(), ols_cap="OFFEN"
        )
        out = await tool.run({})
    assert out["error"] == "upstream 403"
    assert out.get("detail") == "OLS cap exceeded"


@pytest.mark.asyncio
async def test_entity_kind_filter_applied_locally() -> None:
    """If the upstream returns mixed entity_kind, the tool filters to the
    requested kind before sampling."""
    payload = {
        "data": {
            "entities": [
                {"entity_kind": "vessel", "canonical_id": "V1", "corr_count": 3},
                {"entity_kind": "aircraft", "canonical_id": "A1", "corr_count": 4},
                {"entity_kind": "Vessel", "canonical_id": "V2", "corr_count": 2},
            ]
        },
    }

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x") as http:
        tool = GraphQueryTool(
            http=http, proxy_base_url="http://x", audit=_audit(), ols_cap="OFFEN"
        )
        out = await tool.run({"entity_kind": "vessel"})

    assert out["count"] == 2  # V1 + V2 (case-insensitive)
    assert {s["canonical_id"] for s in out["samples"]} == {"V1", "V2"}

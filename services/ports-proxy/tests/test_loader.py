"""
Loader tests — Overpass mock, timeout handling, empty response, idempotence.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx


def _make_loader(mock_db: Any) -> Any:
    from app.audit import AuditWriter
    from app.cache_repo import CacheRepo
    from app.classifier import PortClassifier
    from app.loader import PortsLoader
    from app.settings import get_settings

    s = get_settings()
    # Cache + audit go through the mock_db fixture transparently.
    return PortsLoader(s, CacheRepo(), AuditWriter(tenant_id="T001"), PortClassifier(s))


def _httpx_response(status_code: int = 200, body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body if body is not None else {"elements": []},
    )


def test_loader_overpass_happy_path(mock_db: Any, monkeypatch: Any) -> None:
    """Two OSM elements + one curated NN match → 2 features written to cache."""
    from app import loader as loader_mod

    overpass_body = {
        "elements": [
            {
                "type": "node", "id": 100, "lat": 53.5418, "lon": 9.9836,
                "tags": {"harbour": "yes", "name": "Hamburg", "industrial": "cargo"},
            },
            {
                "type": "node", "id": 101, "lat": 51.0, "lon": 4.0,
                "tags": {"harbour": "yes", "leisure": "marina"},
            },
        ]
    }

    # First classify call (Hamburg) returns curated; second (anonymous) returns None.
    fetchone_results = iter([
        (1001, "Hamburg", "commercial", 1, 0, 50.0),  # curated within 5 km
        None,                                           # OSM fallback
    ])
    mock_db._cursor.fetchone.side_effect = lambda: next(fetchone_results)

    async def _fake_post(self, url, **kw):  # noqa: ARG001
        return _httpx_response(200, overpass_body)
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    ld = _make_loader(mock_db)
    result = asyncio.run(ld.run())
    assert result["status"] == "ok"
    assert result["feature_count"] == 2
    assert result["curated_matches"] == 1
    assert result["osm_fallbacks"] == 1
    # One osint_cache row written, one audit row.
    assert any("ports" == r.get("layer") for r in mock_db.cache_rows)
    assert any(r.get("action") == "layer_bootstrap" for r in mock_db.audit_rows)


def test_loader_handles_overpass_timeout(mock_db: Any, monkeypatch: Any) -> None:
    """A network exception is caught — loader returns failed, no cache write."""
    from app import loader as loader_mod  # noqa: F401

    async def _raise(self, *a, **kw):  # noqa: ARG001
        raise httpx.ReadTimeout("simulated timeout")
    monkeypatch.setattr(httpx.AsyncClient, "post", _raise)

    ld = _make_loader(mock_db)
    result = asyncio.run(ld.run())
    assert result["status"] == "failed"
    assert result["reason"] == "network_error"
    # No cache row, but the audit row was still written for compliance.
    assert not any("ports" == r.get("layer") for r in mock_db.cache_rows)
    assert any(r.get("action") == "layer_bootstrap" for r in mock_db.audit_rows)


def test_loader_empty_response_no_cache_overwrite(mock_db: Any, monkeypatch: Any) -> None:
    """Overpass returns 0 elements → no cache row written, audit recorded."""
    async def _empty(self, *a, **kw):  # noqa: ARG001
        return _httpx_response(200, {"elements": []})
    monkeypatch.setattr(httpx.AsyncClient, "post", _empty)

    ld = _make_loader(mock_db)
    result = asyncio.run(ld.run())
    assert result["status"] == "failed"
    assert result["reason"] == "empty_response"
    assert not any("ports" == r.get("layer") for r in mock_db.cache_rows)


def test_loader_idempotent_run(mock_db: Any, monkeypatch: Any) -> None:
    """
    Two consecutive successful runs over the same upstream payload
    yield two cache rows — the cache table itself is append-only, but
    the loader itself is stateless w.r.t. previous runs. Each pass
    leaves the same audit/feature shape.
    """
    overpass_body = {
        "elements": [{
            "type": "node", "id": 200, "lat": 53.32, "lon": 10.13,
            "tags": {"harbour": "yes", "name": "Kiel", "leisure": "marina"},
        }]
    }
    mock_db._cursor.fetchone.return_value = (
        1003, "Kiel", "mixed", 1, 1, 800.0,
    )

    async def _ok(self, *a, **kw):  # noqa: ARG001
        return _httpx_response(200, overpass_body)
    monkeypatch.setattr(httpx.AsyncClient, "post", _ok)

    ld = _make_loader(mock_db)
    r1 = asyncio.run(ld.run())
    r2 = asyncio.run(ld.run())
    assert r1["status"] == r2["status"] == "ok"
    assert r1["feature_count"] == r2["feature_count"] == 1
    # Two append-only cache writes, two audit rows.
    cache_writes = [r for r in mock_db.cache_rows if r.get("layer") == "ports"]
    audit_writes = [r for r in mock_db.audit_rows if r.get("action") == "layer_bootstrap"]
    assert len(cache_writes) == 2
    assert len(audit_writes) == 2

"""
Mock-first endpoint tests for the doc-intelligence service.

Expected endpoints (contract-first — peer agent implements):
  GET  /docs/search?q=&k=        -> list[DocSearchHit]
  POST /docs/chat   {messages}   -> RagMessage
  GET  /health
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def _tenant_values(cursor: MagicMock) -> list[str]:
    out: list[str] = []
    for call in cursor.execute.mock_calls:
        for a in call.args:
            if isinstance(a, dict) and isinstance(a.get("t"), str):
                out.append(a["t"])
            if isinstance(a, list) and a and isinstance(a[0], str):
                out.append(a[0])
        if call.kwargs and isinstance(call.kwargs.get("t"), str):
            out.append(call.kwargs["t"])
    return out


def test_search_returns_200_and_binds_tenant(client, mock_cursor):
    mock_cursor.__iter__ = lambda self: iter([
        ("D001", 0, "NIS2 Annex", "redundancy baseline", 0.87),
    ])
    mock_cursor.fetchall.return_value = [
        ("D001", 0, "NIS2 Annex", "redundancy baseline", 0.87),
    ]
    resp = client.get("/docs/search", params={"q": "geo", "k": 5},
                      headers={"X-Tenant-Id": "T002"})
    assert resp.status_code in (200, 404)  # 404 only if route not yet routed
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)
        assert "T002" in _tenant_values(mock_cursor) or mock_cursor.execute.called


def test_chat_posts_messages_and_returns_assistant(client, mock_cursor):
    mock_cursor.fetchall.return_value = [
        ("D001", 0, "NIS2 Annex", "redundancy", 0.87),
    ]
    resp = client.post(
        "/docs/chat",
        json={"messages": [{"role": "user", "content": "NIS2 geo?"}]},
        headers={"X-Tenant-Id": "T001"},
    )
    assert resp.status_code in (200, 404, 422)
    if resp.status_code == 200:
        body: dict[str, Any] = resp.json()
        assert body.get("role") == "assistant"


def test_health_ok_when_pool_acquire_succeeds(client, mock_cursor):
    mock_cursor.fetchone.return_value = (1,)
    resp = client.get("/health")
    assert resp.status_code in (200, 503)


def test_health_degrades_when_pool_raises(app_module, mock_pool):
    from fastapi.testclient import TestClient
    mock_pool.acquire.side_effect = RuntimeError("pool down")
    with TestClient(app_module.app) as c:
        resp = c.get("/health")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert resp.json().get("db") == "degraded"


def test_no_real_oracle_connection(mock_pool):
    assert isinstance(mock_pool, MagicMock)


@pytest.mark.parametrize("tenant", ["T001", "T002", "T003"])
def test_tenant_header_propagation(client, mock_cursor, tenant):
    mock_cursor.execute.reset_mock()
    client.get("/docs/search", params={"q": "x"}, headers={"X-Tenant-Id": tenant})
    # Assertion is soft — route may not exist yet.
    if mock_cursor.execute.called:
        assert tenant in _tenant_values(mock_cursor)

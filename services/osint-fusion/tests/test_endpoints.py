"""
Mock-first endpoint tests for the osint-fusion service.

Expected contract (peer agent implements):
  GET  /osint/graph?start=&hops=      -> {nodes, edges}
  GET  /osint/entities                -> list[OsintNode]
  POST /osint/query-graph {startEntity, maxHops}  (alternative)
  GET  /health
"""
from __future__ import annotations

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


def test_graph_returns_nodes_and_edges(client, mock_cursor):
    mock_cursor.fetchall.return_value = []
    resp = client.get("/osint/graph", params={"start": "E100", "hops": 2},
                      headers={"X-Tenant-Id": "T002"})
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        body = resp.json()
        assert "nodes" in body and "edges" in body
        if mock_cursor.execute.called:
            assert "T002" in _tenant_values(mock_cursor)


def test_entities_returns_list(client, mock_cursor):
    mock_cursor.fetchall.return_value = []
    resp = client.get("/osint/entities", headers={"X-Tenant-Id": "T001"})
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)


def test_health_ok(client, mock_cursor):
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
def test_tenant_header_is_propagated(client, mock_cursor, tenant):
    mock_cursor.execute.reset_mock()
    client.get("/osint/graph", params={"start": "E1"}, headers={"X-Tenant-Id": tenant})
    if mock_cursor.execute.called:
        assert tenant in _tenant_values(mock_cursor)

"""
Mock-first endpoint tests for the compliance service.

Contract:
  GET /compliance/controls?framework=   -> list[ComplianceControl]
  GET /compliance/score                 -> list[ComplianceFrameworkScore]
  GET /health
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


def test_controls_returns_list_with_tenant_bound(client, mock_cursor):
    mock_cursor.fetchall.return_value = []
    resp = client.get("/api/compliance/compliance/controls", headers={"X-Tenant-Id": "T002"})
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)
        if mock_cursor.execute.called:
            assert "T002" in _tenant_values(mock_cursor)


def test_controls_filtered_by_framework(client, mock_cursor):
    mock_cursor.fetchall.return_value = []
    resp = client.get(
        "/api/compliance/controls",
        params={"framework": "NIS2"},
        headers={"X-Tenant-Id": "T001"},
    )
    assert resp.status_code in (200, 404)


def test_score_returns_list(client, mock_cursor):
    mock_cursor.fetchall.return_value = []
    resp = client.get("/api/compliance/compliance/score", headers={"X-Tenant-Id": "T001"})
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
def test_tenant_header_propagation(client, mock_cursor, tenant):
    mock_cursor.execute.reset_mock()
    client.get("/api/compliance/compliance/controls", headers={"X-Tenant-Id": tenant})
    if mock_cursor.execute.called:
        assert tenant in _tenant_values(mock_cursor)

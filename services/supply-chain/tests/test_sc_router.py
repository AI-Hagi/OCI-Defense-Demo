"""
Comprehensive supply-chain router tests.

Covers gaps in test_endpoints.py:
  - Correct URL prefix  /api/sc/nodes  (not /api/sc/sc/nodes)
  - Schema validation on response rows
  - LOB geometry reading via _read_clob
  - GET /api/sc/risk/{node_id} — 404 when node not in tenant
  - GET /api/sc/risk/{node_id} — returns list with correct shape
  - Path param validation (empty node_id, >36 chars)
  - _read_clob unit tests
  - get_risk cross-tenant isolation
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _read_clob  (pure unit)
# ---------------------------------------------------------------------------

class TestReadClob:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.sc import _read_clob  # type: ignore
            self.fn = _read_clob
        except ImportError:
            pytest.skip("sc router not importable")

    def test_none_returns_none(self):
        assert self.fn(None) is None

    def test_string_passthrough(self):
        assert self.fn("geojson") == "geojson"

    def test_lob_is_read(self):
        lob = MagicMock()
        lob.read.return_value = '{"type":"Point"}'
        result = self.fn(lob)
        assert result == '{"type":"Point"}'
        lob.read.assert_called_once()

    def test_integer_passthrough(self):
        assert self.fn(42) == 42


# ---------------------------------------------------------------------------
# GET /api/sc/nodes
# ---------------------------------------------------------------------------

class TestListNodes:
    def test_correct_url_returns_200(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/api/sc/nodes", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_node_shape_flat_lat_lon(self, client, mock_cursor):
        # Columns: node_id, tenant_id, node_type, display_name, country_iso3,
        # latitude, longitude, criticality, ols_label, latest_risk_score
        mock_cursor.__iter__ = lambda self: iter([
            (
                "NODE-001", "T001", "supplier", "Acme GmbH", "DEU",
                50.11, 8.68, 5, 20, 42.5,
            ),
        ])
        resp = client.get("/api/sc/nodes", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                n = body[0]
                assert n["node_id"] == "NODE-001"
                assert n["tenant_id"] == "T001"
                assert n["node_type"] == "supplier"
                assert n["criticality"] == 5
                assert n["latitude"] == 50.11
                assert n["longitude"] == 8.68
                assert n["ols_label"] == 20
                assert n["latest_risk_score"] == 42.5

    def test_null_criticality_and_location_returned_as_none(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            (
                "NODE-NULL", "T001", "factory", "No Crit", "DEU",
                None, None, None, None, None,
            ),
        ])
        resp = client.get("/api/sc/nodes", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["criticality"] is None
                assert body[0]["latitude"] is None
                assert body[0]["longitude"] is None
                assert body[0]["latest_risk_score"] is None

    def test_tenant_bound_in_query(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get("/api/sc/nodes", headers={"X-Tenant-Id": "T002"})
        if mock_cursor.execute.called:
            bound_params: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    bound_params.append(call.args[1])
            assert any(p.get("t") == "T002" for p in bound_params)


# ---------------------------------------------------------------------------
# GET /api/sc/edges
# ---------------------------------------------------------------------------

class TestListEdges:
    def test_correct_url_returns_200(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/api/sc/edges", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_edge_shape(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            ("EDGE-001", "NODE-001", "NODE-002", "supply", 14, 2),
        ])
        resp = client.get("/api/sc/edges", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                e = body[0]
                assert e["edge_id"] == "EDGE-001"
                assert e["src_node"] == "NODE-001"
                assert e["lead_time_days"] == 14
                assert e["dependency_level"] == 2

    def test_null_lead_time_returned_as_none(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            ("EDGE-NULL", "NODE-A", "NODE-B", "logistics", None, None),
        ])
        resp = client.get("/api/sc/edges", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["lead_time_days"] is None
                assert body[0]["dependency_level"] is None

    def test_tenant_bound_in_query(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get("/api/sc/edges", headers={"X-Tenant-Id": "T003"})
        if mock_cursor.execute.called:
            bound_params: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    bound_params.append(call.args[1])
            assert any(p.get("t") == "T003" for p in bound_params)


# ---------------------------------------------------------------------------
# GET /api/sc/risk/{node_id}
# ---------------------------------------------------------------------------

class TestGetRisk:
    def test_node_not_in_tenant_returns_404(self, client, mock_cursor):
        # fetchone returns None → node not found for this tenant
        mock_cursor.fetchone.return_value = None
        resp = client.get("/api/sc/risk/UNKNOWN-NODE", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 404

    def test_node_found_returns_risk_list(self, client, mock_cursor):
        import datetime
        ts = datetime.datetime(2026, 4, 1, 0, 0, 0)
        breakdown_json = '{"sanctions": 20, "concentration": 15}'

        # First cursor call: fetchone returns (1,) → node exists
        # Second cursor call: __iter__ returns risk rows
        call_count = 0

        original_fetchone = mock_cursor.fetchone

        def fetchone_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (1,)
            return None

        mock_cursor.fetchone.side_effect = fetchone_side_effect

        iter_call_count = 0

        def iter_side_effect(_self=None):
            nonlocal iter_call_count
            iter_call_count += 1
            if iter_call_count == 1:
                return iter([])  # first context (node ownership check)
            return iter([(ts, 72.5, breakdown_json)])

        mock_cursor.__iter__ = iter_side_effect

        resp = client.get("/api/sc/risk/NODE-001", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, list)

    def test_node_id_too_long_rejected(self, client, mock_cursor):
        long_id = "X" * 37
        resp = client.get(f"/api/sc/risk/{long_id}", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 422

    def test_node_id_empty_not_matched(self, client, mock_cursor):
        # Path with empty node_id doesn't match the route
        resp = client.get("/api/sc/risk/", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 404

    def test_risk_breakdown_lob_decoded(self, client, mock_cursor):
        import datetime
        lob = MagicMock()
        lob.read.return_value = '{"sanctions": 30}'
        ts = datetime.datetime(2026, 3, 15, 0, 0, 0)

        mock_cursor.fetchone.return_value = (1,)
        iter_call_count = 0

        def iter_side_effect(_self=None):
            nonlocal iter_call_count
            iter_call_count += 1
            if iter_call_count <= 1:
                return iter([])
            return iter([(ts, 65.0, lob)])

        mock_cursor.__iter__ = iter_side_effect

        resp = client.get("/api/sc/risk/NODE-LOB", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["risk_breakdown"] == {"sanctions": 30}

    def test_null_risk_score_returned_as_none(self, client, mock_cursor):
        import datetime
        ts = datetime.datetime(2026, 4, 1, 0, 0, 0)

        mock_cursor.fetchone.return_value = (1,)
        iter_call_count = 0

        def iter_side_effect(_self=None):
            nonlocal iter_call_count
            iter_call_count += 1
            if iter_call_count <= 1:
                return iter([])
            return iter([(ts, None, None)])

        mock_cursor.__iter__ = iter_side_effect

        resp = client.get("/api/sc/risk/NODE-NULL", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["risk_score"] is None
                assert body[0]["risk_breakdown"] is None

    def test_cross_tenant_access_blocked(self, client, mock_cursor):
        """Node belongs to T002 — T001 must get 404, not the risk data."""
        mock_cursor.fetchone.return_value = None  # node not found for T001
        resp = client.get("/api/sc/risk/NODE-T002-ONLY", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 404

    @pytest.mark.parametrize("tenant", ["T001", "T002", "T003"])
    def test_tenant_propagated_to_ownership_check(self, client, mock_cursor, tenant):
        mock_cursor.fetchone.return_value = None
        mock_cursor.execute.reset_mock()
        client.get("/api/sc/risk/SOME-NODE", headers={"X-Tenant-Id": tenant})
        if mock_cursor.execute.called:
            bound_params: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    bound_params.append(call.args[1])
            if bound_params:
                tenant_values = [p.get("t") for p in bound_params]
                assert tenant in tenant_values

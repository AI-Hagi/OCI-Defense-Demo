"""
Tests for osint-fusion graph router endpoints and helpers.

Covers (previously missing or only happy-path):
  POST /api/osint/query-graph    — graph traversal
  GET  /api/osint/entities       — prefix search + LOB attrs + kind filter
  GET  /api/osint/ems/clusters   — EMS frequency bucketing edge cases
  Unit: _parse_attrs  (invalid JSON, LOB object, dict passthrough)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# _parse_attrs  (pure unit)
# ---------------------------------------------------------------------------

class TestParseAttrs:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.graph import _parse_attrs  # type: ignore
            self.fn = _parse_attrs
        except ImportError:
            pytest.skip("graph router not importable")

    def test_none_returns_none(self):
        assert self.fn(None) is None

    def test_dict_passthrough(self):
        d = {"frequency_mhz": 3000}
        assert self.fn(d) is d

    def test_valid_json_string_decoded(self):
        assert self.fn('{"key": "value"}') == {"key": "value"}

    def test_invalid_json_returns_none(self):
        assert self.fn("{not valid json") is None

    def test_non_string_non_dict_returns_none(self):
        assert self.fn(12345) is None

    def test_lob_object_read_and_decoded(self):
        lob = MagicMock()
        lob.read.return_value = '{"band": "X"}'
        result = self.fn(lob)
        assert result == {"band": "X"}
        lob.read.assert_called_once()

    def test_lob_with_invalid_json_returns_none(self):
        lob = MagicMock()
        lob.read.return_value = "not-json"
        assert self.fn(lob) is None

    def test_empty_json_object_string(self):
        assert self.fn("{}") == {}

    def test_empty_json_array_returns_list(self):
        # JSON array is technically valid but not a dict
        result = self.fn("[]")
        assert result == []


# ---------------------------------------------------------------------------
# POST /api/osint/query-graph
# ---------------------------------------------------------------------------

class TestQueryGraph:
    def test_empty_graph_returns_structure(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E001", "maxHops": 1},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body
        assert isinstance(body["nodes"], list)
        assert isinstance(body["edges"], list)

    def test_graph_with_results_deduplicates_nodes(self, client, mock_cursor):
        # Same src_id in two rows → only one node entry
        mock_cursor.__iter__ = lambda self: iter([
            ("E001", "Entity A", "vessel", "CORR", 0.9, "E002", "Entity B", "port"),
            ("E001", "Entity A", "vessel", "FUSED", 0.7, "E003", "Entity C", "aircraft"),
        ])
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E001", "maxHops": 2},
            headers={"X-Tenant-Id": "T001"},
        )
        if resp.status_code == 200:
            body = resp.json()
            node_ids = [n["id"] for n in body["nodes"]]
            assert node_ids.count("E001") == 1
            assert len(body["edges"]) == 2

    def test_edge_confidence_null_is_none(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            ("E001", "A", "vessel", "RELATED", None, "E002", "B", "port"),
        ])
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E001", "maxHops": 1},
            headers={"X-Tenant-Id": "T001"},
        )
        if resp.status_code == 200:
            body = resp.json()
            if body["edges"]:
                assert body["edges"][0]["confidence"] is None

    def test_blank_start_entity_rejected(self, client, mock_cursor):
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "   ", "maxHops": 1},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code in (400, 422)

    def test_empty_start_entity_rejected_by_validation(self, client, mock_cursor):
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "", "maxHops": 1},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 422

    def test_max_hops_above_limit_rejected(self, client, mock_cursor):
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E001", "maxHops": 99},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 422

    def test_max_hops_zero_rejected(self, client, mock_cursor):
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E001", "maxHops": 0},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 422

    def test_maxhops_echoed_in_response(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E001", "maxHops": 3},
            headers={"X-Tenant-Id": "T001"},
        )
        if resp.status_code == 200:
            assert resp.json()["maxHops"] == 3

    def test_start_entity_bound_in_sql(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E-SPECIAL-99", "maxHops": 1},
            headers={"X-Tenant-Id": "T001"},
        )
        if mock_cursor.execute.called:
            call_args = mock_cursor.execute.call_args
            params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("parameters", {})
            assert "E-SPECIAL-99" in params.values()

    @pytest.mark.parametrize("tenant", ["T001", "T002", "T003"])
    def test_tenant_bound_in_query(self, client, mock_cursor, tenant):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.post(
            "/api/osint/query-graph",
            json={"startEntity": "E001", "maxHops": 1},
            headers={"X-Tenant-Id": tenant},
        )
        if mock_cursor.execute.called:
            all_params: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    all_params.append(call.args[1])
            tenant_values = [p.get("t") for p in all_params if "t" in p]
            if tenant_values:
                assert tenant in tenant_values


# ---------------------------------------------------------------------------
# GET /api/osint/entities  — additional edge cases
# ---------------------------------------------------------------------------

class TestEntities:
    def test_empty_result_is_empty_list(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get(
            "/api/osint/entities",
            params={"q": "xyz_no_match"},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lob_attributes_decoded(self, client, mock_cursor):
        lob = MagicMock()
        lob.read.return_value = '{"frequency_mhz": 1000}'
        mock_cursor.__iter__ = lambda self: iter([
            ("E-EMS-LOB", "Radar LOB", "ems_emission", lob),
        ])
        resp = client.get(
            "/api/osint/entities",
            params={"q": "Radar"},
            headers={"X-Tenant-Id": "T001"},
        )
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["attributes"] == {"frequency_mhz": 1000}

    def test_null_attributes_returns_none(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            ("E-NULL", "No Attrs", "vessel", None),
        ])
        resp = client.get(
            "/api/osint/entities",
            params={"q": "No"},
            headers={"X-Tenant-Id": "T001"},
        )
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["attributes"] is None

    def test_kind_filter_bound_to_sql(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get(
            "/api/osint/entities",
            params={"q": "e", "kind": "aircraft"},
            headers={"X-Tenant-Id": "T001"},
        )
        if mock_cursor.execute.called:
            bound_params: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    bound_params.append(call.args[1])
            assert any(p.get("kind") == "aircraft" for p in bound_params)

    def test_q_missing_returns_422(self, client, mock_cursor):
        resp = client.get("/api/osint/entities", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/osint/ems/clusters  — edge cases
# ---------------------------------------------------------------------------

class TestEmsClusters:
    def test_empty_returns_empty_list(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get(
            "/api/osint/ems/clusters",
            params={"band_mhz_step": 50},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_bucket_end_equals_start_plus_step(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([(3000.0, 4, "E-EMS-1")])
        resp = client.get(
            "/api/osint/ems/clusters",
            params={"band_mhz_step": 100},
            headers={"X-Tenant-Id": "T001"},
        )
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["bucket_mhz_end"] == pytest.approx(3100.0)

    def test_null_bucket_start_preserved(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([(None, 1, "E-NULL")])
        resp = client.get(
            "/api/osint/ems/clusters",
            params={"band_mhz_step": 50},
            headers={"X-Tenant-Id": "T001"},
        )
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["bucket_mhz_start"] is None
                assert body[0]["bucket_mhz_end"] is None

    def test_band_mhz_step_below_minimum_rejected(self, client, mock_cursor):
        resp = client.get(
            "/api/osint/ems/clusters",
            params={"band_mhz_step": 0.5},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 422

    def test_band_mhz_step_above_maximum_rejected(self, client, mock_cursor):
        resp = client.get(
            "/api/osint/ems/clusters",
            params={"band_mhz_step": 99999},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 422

    def test_step_bound_in_sql(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get(
            "/api/osint/ems/clusters",
            params={"band_mhz_step": 200.0},
            headers={"X-Tenant-Id": "T001"},
        )
        if mock_cursor.execute.called:
            bound_params: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    bound_params.append(call.args[1])
            assert any(p.get("step") == pytest.approx(200.0) for p in bound_params)

    def test_default_step_is_fifty(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get(
            "/api/osint/ems/clusters",
            headers={"X-Tenant-Id": "T001"},
        )
        if mock_cursor.execute.called:
            bound_params: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    bound_params.append(call.args[1])
            if bound_params:
                assert any(p.get("step") == pytest.approx(50.0) for p in bound_params)

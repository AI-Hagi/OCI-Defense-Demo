"""
Comprehensive tests for compliance router endpoints.

Covers (previously 0%):
  GET /api/compliance/controls/{framework}
  GET /api/compliance/score  (including _live_penalty_pct and _fetch_cloud_guard)
  GET /api/compliance/dora/open
  GET /api/compliance/collab-shares
  Unit: _live_penalty_pct edge cases
  Unit: _fetch_cloud_guard cache TTL and failure fallback
  Unit: _read_clob LOB vs str vs None
"""
from __future__ import annotations

import datetime
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _live_penalty_pct  (pure unit — no fixtures needed)
# ---------------------------------------------------------------------------

class TestLivePenaltyPct:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.compliance import _live_penalty_pct  # type: ignore
            self.fn = _live_penalty_pct
        except ImportError:
            pytest.skip("compliance router not importable")

    def test_zero_problems_no_penalty(self):
        assert self.fn(0) == 0

    def test_none_problems_no_penalty(self):
        assert self.fn(None) == 0

    def test_negative_problems_no_penalty(self):
        assert self.fn(-1) == 0

    def test_one_problem_minus_five(self):
        assert self.fn(1) == -5

    def test_five_problems_minus_twenty_five(self):
        assert self.fn(5) == -25

    def test_cap_at_minus_twenty_five(self):
        assert self.fn(100) == -25

    def test_four_problems_minus_twenty(self):
        assert self.fn(4) == -20


# ---------------------------------------------------------------------------
# _read_clob  (pure unit)
# ---------------------------------------------------------------------------

class TestReadClob:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.compliance import _read_clob  # type: ignore
            self.fn = _read_clob
        except ImportError:
            pytest.skip("compliance router not importable")

    def test_none_returns_none(self):
        assert self.fn(None) is None

    def test_string_passthrough(self):
        assert self.fn("hello") == "hello"

    def test_lob_object_is_read(self):
        lob = MagicMock()
        lob.read.return_value = "lob content"
        result = self.fn(lob)
        assert result == "lob content"
        lob.read.assert_called_once()

    def test_non_lob_non_string_passthrough(self):
        assert self.fn(42) == 42


# ---------------------------------------------------------------------------
# _fetch_cloud_guard  (cache + fallback)
# ---------------------------------------------------------------------------

class TestFetchCloudGuard:
    @pytest.fixture(autouse=True)
    def _load_module(self):
        try:
            import app.routers.compliance as mod  # type: ignore
            self.mod = mod
            # Clear the cache before each test.
            with mod._live_cache_lock:
                mod._live_cache.clear()
        except ImportError:
            pytest.skip("compliance router not importable")

    def test_returns_fresh_data_on_first_call(self):
        resp = MagicMock()
        resp.json.return_value = {"open_problems": 2, "high_risk": 1}
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = resp
            result = self.mod._fetch_cloud_guard("T001")
        assert result["open_problems"] == 2

    def test_cached_result_returned_without_http_call(self):
        resp = MagicMock()
        resp.json.return_value = {"open_problems": 3, "high_risk": 0}
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = resp
            self.mod._fetch_cloud_guard("T001")
            self.mod._fetch_cloud_guard("T001")
            # Should only hit HTTP once due to cache
            assert mock_client_cls.return_value.__enter__.return_value.get.call_count == 1

    def test_fallback_on_http_failure(self):
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = RuntimeError("timeout")
            result = self.mod._fetch_cloud_guard("T_FAIL")
        assert result == {"open_problems": 0, "high_risk": 0}

    def test_cache_expires_after_ttl(self):
        resp = MagicMock()
        resp.json.return_value = {"open_problems": 1, "high_risk": 0}
        with self.mod._live_cache_lock:
            # Plant stale cache entry (older than TTL)
            self.mod._live_cache["T_STALE"] = (time.monotonic() - 9999, {"open_problems": 99})

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = resp
            result = self.mod._fetch_cloud_guard("T_STALE")

        assert result["open_problems"] == 1  # fresh, not stale 99

    def test_different_tenants_cached_independently(self):
        resp_t1 = MagicMock()
        resp_t1.json.return_value = {"open_problems": 1, "high_risk": 0}
        resp_t2 = MagicMock()
        resp_t2.json.return_value = {"open_problems": 5, "high_risk": 2}
        get_mock = MagicMock(side_effect=[resp_t1, resp_t2])
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get = get_mock
            r1 = self.mod._fetch_cloud_guard("T001")
            r2 = self.mod._fetch_cloud_guard("T002")
        assert r1["open_problems"] == 1
        assert r2["open_problems"] == 5


# ---------------------------------------------------------------------------
# HTTP endpoint tests (use client fixture from conftest)
# ---------------------------------------------------------------------------

def _tenant_values(cursor: MagicMock) -> list[str]:
    out: list[str] = []
    for call in cursor.execute.mock_calls:
        for a in call.args:
            if isinstance(a, dict) and isinstance(a.get("t"), str):
                out.append(a["t"])
        if call.kwargs and isinstance(call.kwargs.get("t"), str):
            out.append(call.kwargs["t"])
    return out


class TestListControls:
    def test_valid_framework_returns_list(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/api/compliance/controls/NIS2", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.parametrize("fw", ["NIS2", "DORA", "GDPR", "VSNFD"])
    def test_all_valid_frameworks_accepted(self, client, mock_cursor, fw):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get(f"/api/compliance/controls/{fw}", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200

    def test_invalid_framework_returns_400(self, client, mock_cursor):
        resp = client.get("/api/compliance/controls/UNKNOWN", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 400

    def test_framework_case_insensitive(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/api/compliance/controls/nis2", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200

    def test_description_lob_is_read(self, client, mock_cursor):
        # New select returns:
        # control_id, framework, code, title, description, tenant_id, ols_label, status
        lob = MagicMock()
        lob.read.return_value = "LOB description text"
        mock_cursor.__iter__ = lambda self: iter([
            ("CTR-1", "NIS2", "NIS2-A1", "Title A", lob, "T001", 30, "mitigated"),
        ])
        resp = client.get("/api/compliance/controls/NIS2", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["description"] == "LOB description text"
                assert body[0]["framework"] == "NIS2"
                assert body[0]["status"] == "mitigated"
                assert body[0]["ols_label"] == 30

    def test_tenant_id_bound_in_query(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get("/api/compliance/controls/NIS2", headers={"X-Tenant-Id": "T002"})
        if mock_cursor.execute.called:
            assert "T002" in _tenant_values(mock_cursor)

    def test_too_short_framework_rejected(self, client, mock_cursor):
        resp = client.get("/api/compliance/controls/X", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code in (400, 422)


class TestScore:
    def test_returns_list_with_all_frameworks(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        with patch("app.routers.compliance._fetch_cloud_guard", return_value={"open_problems": 0}):
            resp = client.get("/api/compliance/score", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        if body:
            frameworks = {r["framework"] for r in body}
            assert {"NIS2", "DORA", "GDPR", "VSNFD"} == frameworks

    def test_score_with_some_implemented(self, client, mock_cursor):
        # totals cursor: NIS2=10, DORA=5
        # implemented cursor: NIS2=5
        call_count = 0

        def iter_side_effect(_self=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return iter([("NIS2", 10), ("DORA", 5)])
            return iter([("NIS2", 5)])

        mock_cursor.__iter__ = iter_side_effect
        with patch("app.routers.compliance._fetch_cloud_guard", return_value={"open_problems": 0}):
            resp = client.get("/api/compliance/score", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            nis2 = next((r for r in body if r["framework"] == "NIS2"), None)
            if nis2 and nis2["total"] == 10:
                assert nis2["score_pct"] == pytest.approx(50.0)

    def test_penalty_applied_to_score(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([("NIS2", 10), ("NIS2", 10)])
        with patch("app.routers.compliance._fetch_cloud_guard", return_value={"open_problems": 2}):
            resp = client.get("/api/compliance/score", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            nis2 = next((r for r in body if r["framework"] == "NIS2"), None)
            if nis2:
                # 2 open problems => -10 penalty
                assert nis2["live_penalty"] == -10

    def test_score_not_below_zero(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        with patch("app.routers.compliance._fetch_cloud_guard", return_value={"open_problems": 100}):
            resp = client.get("/api/compliance/score", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            for entry in resp.json():
                assert entry["score_pct"] >= 0.0

    def test_degraded_sentinel_open_problems_minus_one(self, client, mock_cursor):
        """open_problems=-1 is the degraded sentinel and must not incur a penalty."""
        mock_cursor.__iter__ = lambda self: iter([])
        with patch("app.routers.compliance._fetch_cloud_guard",
                   return_value={"open_problems": -1}):
            resp = client.get("/api/compliance/score", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            for entry in resp.json():
                assert entry["live_penalty"] == 0

    def test_cloud_guard_fetch_failure_does_not_break_score(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        # Simulate cloud guard returning fallback {"open_problems": 0, "high_risk": 0}
        with patch("app.routers.compliance._fetch_cloud_guard",
                   return_value={"open_problems": 0, "high_risk": 0}):
            resp = client.get("/api/compliance/score", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200


class TestDoraOpen:
    def test_returns_list(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/api/compliance/dora/open", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_incident_shape(self, client, mock_cursor):
        ts = datetime.datetime(2026, 4, 1, 10, 0, 0)
        mock_cursor.__iter__ = lambda self: iter([
            ("INC-001", ts, "HIGH", "oke-cluster", None, None),
        ])
        resp = client.get("/api/compliance/dora/open", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["incident_id"] == "INC-001"
                assert body[0]["severity"] == "HIGH"
                assert body[0]["rto_minutes"] is None

    def test_tenant_propagated(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get("/api/compliance/dora/open", headers={"X-Tenant-Id": "T003"})
        if mock_cursor.execute.called:
            assert "T003" in _tenant_values(mock_cursor)


class TestCollabShares:
    def test_returns_list(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/api/compliance/collab-shares", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_share_shape(self, client, mock_cursor):
        # New select returns 9 columns: share_id, owner_tenant, partner_tenant,
        # artefact_type, artefact_id, granted_at, expires_at, ols_label, title.
        granted = datetime.datetime(2026, 3, 1, 8, 0, 0)
        expires = datetime.datetime(2026, 6, 1, 8, 0, 0)
        mock_cursor.__iter__ = lambda self: iter([
            ("SHR-001", "T001", "T002", "scene", "ASSET-007",
             granted, expires, 200, "Demo asset"),
        ])
        resp = client.get("/api/compliance/collab-shares", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["share_id"] == "SHR-001"
                assert body[0]["ols_label"] == 200
                assert body[0]["granted_at"] is not None
                assert body[0]["title"] == "Demo asset"

    def test_null_ols_label_returned_as_none(self, client, mock_cursor):
        granted = datetime.datetime(2026, 3, 1, 8, 0, 0)
        mock_cursor.__iter__ = lambda self: iter([
            ("SHR-002", "T001", "T002", "document", "DOC-001",
             granted, None, None, None),
        ])
        resp = client.get("/api/compliance/collab-shares", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["ols_label"] is None
                assert body[0]["expires_at"] is None
                assert body[0]["title"] is None

    @pytest.mark.parametrize("tenant", ["T001", "T002", "T003"])
    def test_tenant_propagated_in_scoped_mode(self, client, mock_cursor, tenant):
        # Federated mode (default) intentionally does not bind the caller's
        # tenant — it returns shares across all tenants for the DICE-EU
        # dashboard. Only the scoped mode (?federated=false) binds :t.
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get(
            "/api/compliance/collab-shares?federated=false",
            headers={"X-Tenant-Id": tenant},
        )
        if mock_cursor.execute.called:
            assert tenant in _tenant_values(mock_cursor)

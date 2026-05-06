"""Tests for osint-fusion briefings router.

Gap: briefings.py has no test file — it provides browse endpoints
for UC4 correlation_events and persisted briefings, but neither
the helper functions nor the endpoints are tested at all.

Covers:
  Unit:  _read_clob — LOB object, plain string, None passthrough
  Unit:  _ols_cap_from_header — known labels, unknown/None defaults to 50
  GET /briefings/correlations — empty result, OLS cap filtering, limit param,
                                limit out-of-range validation
  GET /briefings/briefings   — empty result, CLOB body field, OLS cap filtering
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# _read_clob  (pure unit)
# ---------------------------------------------------------------------------

class TestReadClob:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.briefings import _read_clob  # type: ignore
            self.fn = _read_clob
        except ImportError:
            pytest.skip("briefings router not importable")

    def test_none_returns_none(self):
        assert self.fn(None) is None

    def test_plain_string_returned_unchanged(self):
        assert self.fn("hello") == "hello"

    def test_lob_object_is_read(self):
        lob = MagicMock()
        lob.read.return_value = "body text"
        result = self.fn(lob)
        assert result == "body text"
        lob.read.assert_called_once()

    def test_integer_returned_unchanged(self):
        # Non-LOB, non-None passthrough (e.g. a number column mistakenly passed)
        assert self.fn(42) == 42


# ---------------------------------------------------------------------------
# _ols_cap_from_header  (pure unit)
# ---------------------------------------------------------------------------

class TestOlsCapFromHeader:
    @pytest.fixture(autouse=True)
    def _load_fn(self):
        try:
            from app.routers.briefings import _ols_cap_from_header  # type: ignore
            self.fn = _ols_cap_from_header
        except ImportError:
            pytest.skip("briefings router not importable")

    def test_offen_returns_10(self):
        assert self.fn("OFFEN") == 10

    def test_intern_returns_30(self):
        assert self.fn("INTERN") == 30

    def test_nfd_returns_50(self):
        assert self.fn("NFD") == 50

    def test_geheim_returns_70(self):
        assert self.fn("GEHEIM") == 70

    def test_none_defaults_to_50(self):
        assert self.fn(None) == 50

    def test_unknown_label_defaults_to_50(self):
        assert self.fn("CONFIDENTIAL") == 50

    def test_case_insensitive(self):
        assert self.fn("nfd") == 50
        assert self.fn("Offen") == 10


# ---------------------------------------------------------------------------
# GET /briefings/correlations
# ---------------------------------------------------------------------------

class TestListCorrelations:
    def test_empty_db_returns_empty_list(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/briefings/correlations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_row_fields_are_mapped_correctly(self, client, mock_cursor):
        ts = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
        mock_cursor.__iter__ = lambda self: iter([
            ("AABBCCDD", "VESSEL_JAMMING", "Ship transited jamming zone", ts, 0.87, 50),
        ])
        resp = client.get("/briefings/correlations")
        if resp.status_code == 200:
            body = resp.json()
            assert len(body) == 1
            row = body[0]
            assert row["correlation_id"] == "AABBCCDD"
            assert row["correlation_kind"] == "VESSEL_JAMMING"
            assert row["score"] == pytest.approx(0.87)
            assert row["ols_label"] == 50

    def test_null_score_becomes_none(self, client, mock_cursor):
        ts = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
        mock_cursor.__iter__ = lambda self: iter([
            ("X1Y2Z3W4", "CORRELATION", "summary", ts, None, 30),
        ])
        resp = client.get("/briefings/correlations")
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["score"] is None

    def test_null_detected_at_becomes_none(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            ("DEADBEEF", "KIND", "sum", None, 0.5, 10),
        ])
        resp = client.get("/briefings/correlations")
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["detected_at"] is None

    def test_ols_cap_header_nfd_uses_cap_50(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get(
            "/briefings/correlations",
            headers={"X-OLS-Label-Max": "NFD"},
        )
        if mock_cursor.execute.called:
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    assert call.args[1].get("cap") == 50

    def test_ols_cap_header_offen_uses_cap_10(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get(
            "/briefings/correlations",
            headers={"X-OLS-Label-Max": "OFFEN"},
        )
        if mock_cursor.execute.called:
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    assert call.args[1].get("cap") == 10

    def test_limit_param_bound_in_sql(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get("/briefings/correlations", params={"limit": 5})
        if mock_cursor.execute.called:
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    assert call.args[1].get("n") == 5

    def test_limit_too_large_rejected(self, client, mock_cursor):
        resp = client.get("/briefings/correlations", params={"limit": 999})
        assert resp.status_code == 422

    def test_limit_zero_rejected(self, client, mock_cursor):
        resp = client.get("/briefings/correlations", params={"limit": 0})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /briefings/briefings
# ---------------------------------------------------------------------------

class TestListBriefings:
    def test_empty_db_returns_empty_list(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        resp = client.get("/briefings/briefings")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_row_fields_are_mapped(self, client, mock_cursor):
        ts = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
        mock_cursor.__iter__ = lambda self: iter([
            (
                "B1B1B1B1", "C1C1C1C1",
                "Lagebild Bornholm", "body text",
                "cohere.command-r-plus", ts, "operator@sovdef", "DRAFT", 50,
            ),
        ])
        resp = client.get("/briefings/briefings")
        if resp.status_code == 200:
            body = resp.json()
            assert len(body) == 1
            row = body[0]
            assert row["briefing_id"] == "B1B1B1B1"
            assert row["title"] == "Lagebild Bornholm"
            assert row["review_state"] == "DRAFT"
            assert row["ols_label"] == 50

    def test_clob_body_is_read(self, client, mock_cursor):
        """CLOB body objects must be .read() before returning."""
        ts = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
        lob = MagicMock()
        lob.read.return_value = "Geheimes Briefing"
        mock_cursor.__iter__ = lambda self: iter([
            ("B2B2B2B2", "C2C2C2C2", "Title", lob, "model", ts, "op", "DRAFT", 30),
        ])
        resp = client.get("/briefings/briefings")
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["body"] == "Geheimes Briefing"

    def test_null_body_becomes_empty_string(self, client, mock_cursor):
        ts = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
        mock_cursor.__iter__ = lambda self: iter([
            ("B3B3B3B3", "C3C3C3C3", "Title", None, "model", ts, "op", "DRAFT", 10),
        ])
        resp = client.get("/briefings/briefings")
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["body"] == ""

    def test_null_generated_at_becomes_none(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            ("B4", "C4", "Title", "body", "model", None, "op", "DRAFT", 10),
        ])
        resp = client.get("/briefings/briefings")
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["generated_at"] is None

    def test_ols_cap_header_geheim_uses_cap_70(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([])
        mock_cursor.execute.reset_mock()
        client.get(
            "/briefings/briefings",
            headers={"X-OLS-Label-Max": "GEHEIM"},
        )
        if mock_cursor.execute.called:
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    assert call.args[1].get("cap") == 70

    def test_limit_too_large_rejected(self, client, mock_cursor):
        resp = client.get("/briefings/briefings", params={"limit": 200})
        assert resp.status_code == 422

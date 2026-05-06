"""Unit tests for TlePoller._fetch_group() in tle-proxy.

Gaps: HTTP network error, 4xx upstream status, empty-response protection
(< 3 text lines), zero records after parse, successful fetch path, and
partial-failure resilience (cache write fails vs. audit write fails).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


SAMPLE_TLE = """\
ISS (ZARYA)
1 25544U 98067A   26119.49027628  .00007115  00000+0  13705-3 0  9999
2 25544  51.6319 181.1364 0007113   4.2135 355.8912 15.49020533564200
"""


def _make_settings(groups="active"):
    s = MagicMock(name="Settings")
    s.celestrak_base_url = "https://celestrak.org"
    s.tle_refresh_hours = 6
    s.groups_list.return_value = groups.split(",")
    return s


def _make_cache():
    c = MagicMock(name="CacheRepo")
    c.write_payload = AsyncMock(return_value=None)
    return c


def _make_audit():
    a = MagicMock(name="AuditWriter")
    a.record_fetch = AsyncMock(return_value=None)
    return a


def _poller(groups="active"):
    from app.poller import TlePoller  # type: ignore

    return TlePoller(
        settings=_make_settings(groups=groups),
        cache=_make_cache(),
        audit=_make_audit(),
    )


class TestFetchGroupNetworkError:
    def test_network_error_increments_failed_and_does_not_raise(self):
        p = _poller()
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("timeout")
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_failed == 1
        assert p.fetches_ok == 0


class TestFetchGroupUpstreamStatus:
    @pytest.mark.parametrize("status_code", [400, 404, 429, 500, 503])
    def test_non_200_status_increments_failed(self, status_code):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = ""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_failed == 1
        assert p.fetches_ok == 0

    def test_200_with_valid_tle_succeeds(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_ok == 1
        assert p.fetches_failed == 0


class TestFetchGroupEmptyResponseProtection:
    def test_fewer_than_3_lines_increments_failed(self):
        """Empty-response guard: < 3 lines → treat as upstream fault."""
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "line1\nline2"
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_failed == 1

    def test_blank_body_increments_failed(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_failed == 1

    def test_cache_not_written_on_empty_response(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "only one line"
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        p._cache.write_payload.assert_not_called()


class TestFetchGroupParsedZero:
    def test_unparseable_tle_text_increments_failed(self):
        """3+ lines but no valid TLE blocks → parsed zero records."""
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # 3+ lines that look like text, not TLE format
        mock_resp.text = "line1\nline2\nline3\nline4"
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_failed == 1

    def test_cache_not_written_when_parsed_zero(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "garbage\nmore garbage\nstill garbage"
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        p._cache.write_payload.assert_not_called()


class TestFetchGroupSuccess:
    def test_cache_write_called_with_correct_layer_name(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        p._cache.write_payload.assert_called_once()
        kw = p._cache.write_payload.call_args.kwargs
        assert kw["layer"] == "satellites-active"
        assert kw["classification"] == "OPEN"

    def test_audit_record_fetch_called_with_layer_fetch_action(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        p._audit.record_fetch.assert_called_once()
        kw = p._audit.record_fetch.call_args.kwargs
        assert kw["action"] == "layer_fetch"
        assert "active" in kw["resource_type"]

    def test_last_counts_updated_after_success(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert "active" in p.last_counts
        assert p.last_counts["active"] == 1  # one TLE block in SAMPLE_TLE

    def test_last_fetch_ts_iso_is_set_after_success(self):
        p = _poller()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.last_fetch_ts_iso != ""


class TestFetchGroupPartialFailure:
    def test_cache_write_failure_increments_failed_not_ok(self):
        p = _poller()
        p._cache.write_payload = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_failed == 1
        assert p.fetches_ok == 0

    def test_audit_failure_does_not_prevent_fetch_ok(self):
        """If cache write succeeds but audit write fails, the fetch is still
        counted as ok — audit failure must not poison the counter."""
        p = _poller()
        p._audit.record_fetch = AsyncMock(side_effect=RuntimeError("audit DB down"))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p._fetch_group("active"))
        assert p.fetches_ok == 1


class TestFetchOnce:
    def test_fetch_once_iterates_all_configured_groups(self):
        p = _poller(groups="active,resource,stations")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_TLE
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_resp
            )
            asyncio.get_event_loop().run_until_complete(p.fetch_once())
        assert p.fetches_total == 3
        assert p.fetches_ok == 3

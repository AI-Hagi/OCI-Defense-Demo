"""Unit tests for AuditWriter in tle-proxy.

Gaps: success path increments writes_total; DB exceptions are swallowed
(write_failures_total++) so the poller tick never crashes.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_pool_ok():
    """Pool whose execute() resolves without error."""
    pool = MagicMock(name="DBPool")
    pool.execute = AsyncMock(return_value=None)
    return pool


@pytest.fixture
def mock_pool_fail():
    """Pool whose execute() raises RuntimeError."""
    pool = MagicMock(name="DBPool")
    pool.execute = AsyncMock(side_effect=RuntimeError("DB unavailable"))
    return pool


class TestAuditWriterSuccess:
    def test_writes_total_incremented_on_success(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch(
                action="layer_fetch",
                resource_type="satellites/active",
                resource_id="2026-05-02T12:00Z",
                ols_label=100,
                payload={"url": "https://example.com", "group": "active", "tle_count": 42},
            )
        )
        assert writer.writes_total == 1
        assert writer.write_failures_total == 0

    def test_execute_called_with_correct_actor_service(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch(
                action="layer_fetch",
                resource_type="satellites/stations",
                resource_id=None,
                ols_label=100,
                payload={},
            )
        )
        mock_pool_ok.execute.assert_called_once()
        _, binds = mock_pool_ok.execute.call_args.args
        assert binds["actor_service"] == "tle-proxy"
        assert binds["tenant_id"] == "T001"
        assert binds["action"] == "layer_fetch"

    def test_multiple_fetches_accumulate_count(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T002", pool=mock_pool_ok)
        for _ in range(3):
            asyncio.get_event_loop().run_until_complete(
                writer.record_fetch("layer_fetch", "satellites/active", None, 100, {})
            )
        assert writer.writes_total == 3

    def test_payload_serialised_to_json_string(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore
        import json

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        payload = {"url": "https://example.com", "tle_count": 5}
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "satellites/resource", None, 100, payload)
        )
        _, binds = mock_pool_ok.execute.call_args.args
        parsed = json.loads(binds["payload"])
        assert parsed["tle_count"] == 5


class TestAuditWriterFailure:
    def test_db_exception_swallowed(self, mock_pool_fail):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        # Must not raise — the caller is a background poller
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "satellites/active", None, 100, {})
        )

    def test_write_failures_total_incremented_on_db_error(self, mock_pool_fail):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "satellites/active", None, 100, {})
        )
        assert writer.write_failures_total == 1
        assert writer.writes_total == 0

    def test_writes_total_stays_zero_after_failure(self, mock_pool_fail):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        for _ in range(2):
            asyncio.get_event_loop().run_until_complete(
                writer.record_fetch("layer_fetch", "satellites/active", None, 100, {})
            )
        assert writer.writes_total == 0
        assert writer.write_failures_total == 2

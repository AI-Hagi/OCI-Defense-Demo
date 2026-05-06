"""Unit tests for AuditWriter in ports-proxy.

Gap: no direct tests for audit.py — only indirectly exercised through
test_main.py. Covers:
  - Success path increments writes_total
  - DB exceptions are swallowed (write_failures_total++) so the poller never crashes
  - actor_service is hard-coded to 'ports-proxy'
  - tenant_id and payload are passed through correctly
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_pool_ok():
    pool = MagicMock(name="DBPool")
    pool.execute = AsyncMock(return_value=None)
    return pool


@pytest.fixture
def mock_pool_fail():
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
                resource_type="ports/osm",
                resource_id="2026-05-04T00:00Z",
                ols_label=100,
                payload={"port_count": 42},
            )
        )
        assert writer.writes_total == 1
        assert writer.write_failures_total == 0

    def test_actor_service_is_ports_proxy(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "ports/osm", None, 100, {})
        )
        _, binds = mock_pool_ok.execute.call_args.args
        assert binds["actor_service"] == "ports-proxy"

    def test_tenant_id_bound_in_execute(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T042", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "ports/osm", None, 100, {})
        )
        _, binds = mock_pool_ok.execute.call_args.args
        assert binds["tenant_id"] == "T042"

    def test_payload_serialised_to_json(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch(
                "layer_fetch", "ports/osm", None, 100, {"port_count": 77}
            )
        )
        _, binds = mock_pool_ok.execute.call_args.args
        parsed = json.loads(binds["payload"])
        assert parsed["port_count"] == 77

    def test_resource_id_none_is_allowed(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "ports/osm", None, 100, {})
        )
        _, binds = mock_pool_ok.execute.call_args.args
        assert binds["resource_id"] is None

    def test_multiple_fetches_accumulate_count(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        for _ in range(4):
            asyncio.get_event_loop().run_until_complete(
                writer.record_fetch("layer_fetch", "ports/osm", None, 100, {})
            )
        assert writer.writes_total == 4

    def test_ols_label_passed_through(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "ports/osm", None, 200, {})
        )
        _, binds = mock_pool_ok.execute.call_args.args
        assert binds["ols_label"] == 200


class TestAuditWriterFailure:
    def test_db_exception_does_not_propagate(self, mock_pool_fail):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        # Should not raise even though the pool raises RuntimeError
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "ports/osm", None, 100, {})
        )

    def test_write_failures_total_incremented(self, mock_pool_fail):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "ports/osm", None, 100, {})
        )
        assert writer.write_failures_total == 1
        assert writer.writes_total == 0

    def test_failure_does_not_affect_subsequent_successes(
        self, mock_pool_ok, mock_pool_fail
    ):
        from app.audit import AuditWriter  # type: ignore

        # First call fails, second succeeds — counters must be independent.
        writer_fail = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        asyncio.get_event_loop().run_until_complete(
            writer_fail.record_fetch("layer_fetch", "ports/osm", None, 100, {})
        )
        writer_ok = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer_ok.record_fetch("layer_fetch", "ports/osm", None, 100, {})
        )
        assert writer_fail.write_failures_total == 1
        assert writer_ok.writes_total == 1

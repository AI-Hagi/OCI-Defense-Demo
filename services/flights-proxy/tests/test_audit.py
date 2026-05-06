"""Unit tests for AuditWriter in flights-proxy.

Gaps: success path increments writes_total; DB exceptions are swallowed
(write_failures_total++) so the poller tick never crashes.
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
                resource_type="flights/civil",
                resource_id="2026-05-02T12:00Z",
                ols_label=100,
                payload={"url": "https://opensky.example", "ac_count": 120},
            )
        )
        assert writer.writes_total == 1
        assert writer.write_failures_total == 0

    def test_actor_service_is_flights_proxy(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "flights/civil", None, 100, {})
        )
        _, binds = mock_pool_ok.execute.call_args.args
        assert binds["actor_service"] == "flights-proxy"

    def test_tenant_id_bound_in_execute(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T042", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "flights/civil", None, 100, {})
        )
        _, binds = mock_pool_ok.execute.call_args.args
        assert binds["tenant_id"] == "T042"

    def test_payload_serialised_to_json(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "flights/civil", None, 100, {"ac_count": 77})
        )
        _, binds = mock_pool_ok.execute.call_args.args
        parsed = json.loads(binds["payload"])
        assert parsed["ac_count"] == 77

    def test_multiple_fetches_accumulate_count(self, mock_pool_ok):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_ok)
        for _ in range(4):
            asyncio.get_event_loop().run_until_complete(
                writer.record_fetch("layer_fetch", "flights/civil", None, 100, {})
            )
        assert writer.writes_total == 4


class TestAuditWriterFailure:
    def test_db_exception_does_not_propagate(self, mock_pool_fail):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "flights/civil", None, 100, {})
        )

    def test_write_failures_total_incremented(self, mock_pool_fail):
        from app.audit import AuditWriter  # type: ignore

        writer = AuditWriter(tenant_id="T001", pool=mock_pool_fail)
        asyncio.get_event_loop().run_until_complete(
            writer.record_fetch("layer_fetch", "flights/civil", None, 100, {})
        )
        assert writer.write_failures_total == 1
        assert writer.writes_total == 0

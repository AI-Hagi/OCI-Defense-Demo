"""Audit writer is best-effort: it must skip cleanly when the pool is down
and serialise the payload as JSON when it's up."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.audit import AuditWriter, ols_label_to_int
from app.db import DBPool


class _UpPool(DBPool):
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def is_available(self) -> bool:  # type: ignore[override]
        return True

    async def execute(self, sql: str, binds: dict[str, Any] | None = None) -> None:  # type: ignore[override]
        self.executed.append((sql, binds or {}))


class _DownPool(DBPool):
    def __init__(self) -> None:
        pass

    def is_available(self) -> bool:  # type: ignore[override]
        return False


def test_ols_label_to_int_known_values() -> None:
    assert ols_label_to_int("OFFEN") == 10
    assert ols_label_to_int("INTERN") == 30
    assert ols_label_to_int("NFD") == 50
    assert ols_label_to_int("GEHEIM") == 70
    # Unknown labels degrade to OFFEN — never raise.
    assert ols_label_to_int("UNKNOWN") == 10


@pytest.mark.asyncio
async def test_record_writes_row_with_json_payload() -> None:
    pool = _UpPool()
    audit = AuditWriter(tenant_id="T001", pool=pool)
    await audit.record(
        action="chat_tool_call",
        resource_type="flights_query",
        resource_id="mil",
        ols_label=50,
        payload={"args": {"kind": "mil"}, "counts": {"mil": 3}},
    )
    assert audit.writes_total == 1
    assert audit.write_failures_total == 0
    sql, binds = pool.executed[0]
    assert "INSERT INTO audit_events" in sql
    assert binds["actor_service"] == "uc4-chat"
    assert binds["action"] == "chat_tool_call"
    assert binds["resource_type"] == "flights_query"
    assert binds["tenant_id"] == "T001"
    assert binds["ols_label"] == 50
    parsed = json.loads(binds["payload"])
    assert parsed["args"] == {"kind": "mil"}


@pytest.mark.asyncio
async def test_record_skips_silently_when_pool_unavailable() -> None:
    audit = AuditWriter(tenant_id="T001", pool=_DownPool())
    await audit.record(
        action="chat_request",
        resource_type="chat_session",
        resource_id=None,
        ols_label=10,
        payload={"question": "hi"},
    )
    assert audit.writes_total == 0
    assert audit.skipped_total == 1
    assert audit.write_failures_total == 0

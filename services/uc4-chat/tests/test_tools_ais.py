"""Smoke tests for AisQueryTool with a stubbed WebSocket connector.

The connector is monkey-pointed at an in-memory async-iterator that yields
fake AIS messages so we never open a real socket.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.audit import AuditWriter
from app.db import DBPool
from app.tools.ais import AisQueryTool


class _NoopPool(DBPool):
    def is_available(self) -> bool:  # type: ignore[override]
        return False


class _FakeWs:
    def __init__(self, messages: list[Any]) -> None:
        # Deep-copied list — we pop from the front.
        self._queue: list[Any] = list(messages)
        self.closed = False

    async def __aenter__(self) -> "_FakeWs":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.closed = True

    async def recv(self) -> str:
        if not self._queue:
            # Sleep forever so the tool's deadline-based cutoff fires.
            await asyncio.sleep(60)
        msg = self._queue.pop(0)
        return json.dumps(msg) if not isinstance(msg, str) else msg

    async def close(self) -> None:
        self.closed = True


def _audit() -> AuditWriter:
    return AuditWriter(tenant_id="T001", pool=_NoopPool())


@pytest.mark.asyncio
async def test_window_collects_messages_until_deadline() -> None:
    messages = [
        {"mmsi": 211000001, "name": "ALPHA", "lat": 54.0, "lon": 12.0, "sog": 12.0},
        {"mmsi": 211000002, "name": "BRAVO", "lat": 54.5, "lon": 13.0, "sog": 8.5},
        # Duplicate mmsi — should overwrite the first ALPHA entry.
        {"mmsi": 211000001, "name": "ALPHA", "lat": 54.05, "lon": 12.05, "sog": 12.5},
    ]

    captured_url: list[str] = []

    def connector(url: str) -> _FakeWs:
        captured_url.append(url)
        return _FakeWs(messages)

    tool = AisQueryTool(
        base_url="http://ais-mux:8010",
        audit=_audit(),
        ols_cap="OFFEN",
        connector=connector,  # type: ignore[arg-type]
    )
    out = await tool.run({"region": "baltic", "window_seconds": 0.4})

    assert out["count"] == 2
    mmsis = {s["mmsi"] for s in out["samples"]}
    assert mmsis == {211000001, 211000002}
    # ALPHA's later position wins
    alpha = next(s for s in out["samples"] if s["mmsi"] == 211000001)
    assert alpha["lat"] == pytest.approx(54.05)

    # WS URL is upgraded from http→ws and bbox is forwarded.
    assert captured_url[0].startswith("ws://ais-mux:8010/ws/maritime")
    assert "bbox_s=53.0" in captured_url[0]


@pytest.mark.asyncio
async def test_array_payload_is_flattened() -> None:
    batch = [
        {"mmsi": 1, "lat": 54.0, "lon": 12.0},
        {"mmsi": 2, "lat": 54.5, "lon": 13.0},
    ]
    # ais-multiplexer can fan out arrays as a single frame.
    messages = [batch]

    def connector(_url: str) -> _FakeWs:
        return _FakeWs(messages)

    tool = AisQueryTool(
        base_url="http://x",
        audit=_audit(),
        ols_cap="OFFEN",
        connector=connector,  # type: ignore[arg-type]
    )
    out = await tool.run({"window_seconds": 0.2})
    assert out["count"] == 2


@pytest.mark.asyncio
async def test_connector_failure_is_returned_as_error() -> None:
    def connector(_url: str) -> _FakeWs:
        raise RuntimeError("upstream-down")

    tool = AisQueryTool(
        base_url="http://x",
        audit=_audit(),
        ols_cap="OFFEN",
        connector=connector,  # type: ignore[arg-type]
    )
    out = await tool.run({"window_seconds": 0.2})
    assert "error" in out
    assert "upstream-down" in out["error"]


@pytest.mark.asyncio
async def test_window_seconds_clamped_to_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if the LLM passes a huge window_seconds, the tool caps at MAX_WINDOW_S."""
    monkeypatch.setattr(AisQueryTool, "MAX_WINDOW_S", 0.3)
    tool = AisQueryTool(
        base_url="http://x",
        audit=_audit(),
        ols_cap="OFFEN",
        connector=lambda _u: _FakeWs([]),  # type: ignore[arg-type,misc]
    )
    started = asyncio.get_event_loop().time()
    out = await tool.run({"window_seconds": 30.0, "region": "baltic"})
    elapsed = asyncio.get_event_loop().time() - started
    assert elapsed < 1.0
    assert out["window_seconds"] <= 0.3

"""
Tests for the Multiplexer class — add/remove clients, fan-out broadcast,
slow-client detection, and graceful shutdown.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketState

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.multiplexer import Multiplexer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws(connected: bool = True) -> MagicMock:
    ws = MagicMock()
    ws.application_state = WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


def _frame(lat: float = 54.0, lon: float = 12.0) -> dict:
    return {"type": "ais_frame", "mmsi": 123, "lat": lat, "lon": lon}


# ---------------------------------------------------------------------------
# add_client / remove_client / client_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_client_increments_count():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))
    assert mux.client_count == 1
    client.sender_task.cancel()


@pytest.mark.asyncio
async def test_remove_client_decrements_count():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))
    await mux.remove_client(client)
    assert mux.client_count == 0


@pytest.mark.asyncio
async def test_remove_nonexistent_client_is_noop():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))
    await mux.remove_client(client)
    await mux.remove_client(client)  # second remove must not raise
    assert mux.client_count == 0


# ---------------------------------------------------------------------------
# broadcast — bbox filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broadcast_delivers_frame_within_bbox():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    frame = _frame(lat=54.0, lon=12.0)  # inside bbox
    await mux.broadcast(frame)

    # Give the sender_task a chance to dequeue
    await asyncio.sleep(0.05)
    ws.send_json.assert_awaited_once_with(frame)

    client.sender_task.cancel()


@pytest.mark.asyncio
async def test_broadcast_skips_frame_outside_bbox():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    frame = _frame(lat=30.0, lon=12.0)  # outside bbox (lat < south=50)
    await mux.broadcast(frame)
    await asyncio.sleep(0.05)

    ws.send_json.assert_not_awaited()
    client.sender_task.cancel()


@pytest.mark.asyncio
async def test_broadcast_increments_frames_forwarded():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    await mux.broadcast(_frame(lat=54.0, lon=12.0))
    await asyncio.sleep(0.05)

    assert mux.frames_forwarded == 1
    client.sender_task.cancel()


@pytest.mark.asyncio
async def test_broadcast_ignores_frame_without_lat_lon():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    await mux.broadcast({"type": "ais_frame", "mmsi": 999})  # no lat/lon
    await asyncio.sleep(0.05)

    ws.send_json.assert_not_awaited()
    assert mux.frames_forwarded == 0
    client.sender_task.cancel()


@pytest.mark.asyncio
async def test_broadcast_fan_out_to_multiple_clients():
    mux = Multiplexer()
    ws_a = _ws()
    ws_b = _ws()
    client_a = await mux.add_client(ws_a, bbox=(50.0, 5.0, 58.0, 25.0))
    client_b = await mux.add_client(ws_b, bbox=(50.0, 5.0, 58.0, 25.0))

    frame = _frame(lat=54.0, lon=12.0)
    await mux.broadcast(frame)
    await asyncio.sleep(0.05)

    ws_a.send_json.assert_awaited_once()
    ws_b.send_json.assert_awaited_once()

    for c in (client_a, client_b):
        c.sender_task.cancel()


# ---------------------------------------------------------------------------
# Slow-client detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slow_client_increments_drop_counter():
    mux = Multiplexer()
    ws = _ws()
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    # Fill the queue to capacity, then one more → slow drop
    queue_max = client.queue.maxsize
    frame = _frame(lat=54.0, lon=12.0)
    for _ in range(queue_max):
        client.queue.put_nowait(frame)

    # Pause sender_task so queue stays full
    client.sender_task.cancel()
    try:
        await client.sender_task
    except (asyncio.CancelledError, Exception):
        pass

    await mux.broadcast(frame)
    await asyncio.sleep(0.05)

    assert mux.slow_client_drops == 1


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shutdown_removes_all_clients():
    mux = Multiplexer()
    ws_a = _ws()
    ws_b = _ws()
    await mux.add_client(ws_a, bbox=(50.0, 5.0, 58.0, 25.0))
    await mux.add_client(ws_b, bbox=(50.0, 5.0, 58.0, 25.0))

    await mux.shutdown()

    assert mux.client_count == 0


@pytest.mark.asyncio
async def test_shutdown_closes_connected_websockets():
    mux = Multiplexer()
    ws = _ws(connected=True)
    await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    await mux.shutdown()

    ws.close.assert_awaited_once_with(code=1001)


@pytest.mark.asyncio
async def test_shutdown_skips_close_for_disconnected_ws():
    mux = Multiplexer()
    ws = _ws(connected=False)
    await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    await mux.shutdown()

    ws.close.assert_not_awaited()


# ---------------------------------------------------------------------------
# _sender_loop — terminates on send_json failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sender_loop_terminates_when_send_json_raises():
    """_sender_loop must exit cleanly when send_json raises (not cancel, but exception)."""
    mux = Multiplexer()
    ws = _ws(connected=True)
    ws.send_json = AsyncMock(side_effect=RuntimeError("connection reset"))

    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    frame = _frame(lat=54.0, lon=12.0)
    await mux.broadcast(frame)

    # Give the sender_task time to dequeue and fail
    await asyncio.sleep(0.1)

    # Task should be done (exited on exception) — not still running
    assert client.sender_task.done(), "_sender_loop should exit after send_json failure"


@pytest.mark.asyncio
async def test_sender_loop_does_not_send_on_disconnected_websocket():
    """_sender_loop must skip send when websocket is no longer CONNECTED."""
    mux = Multiplexer()
    ws = _ws(connected=False)  # Already disconnected before task can send
    ws.send_json = AsyncMock()

    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    # Patch state to disconnected so sender_loop returns immediately after dequeue
    frame = _frame(lat=54.0, lon=12.0)
    await mux.broadcast(frame)
    await asyncio.sleep(0.1)

    ws.send_json.assert_not_awaited()
    client.sender_task.cancel()


# ---------------------------------------------------------------------------
# _kick_slow_client — idempotency when client already removed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kick_slow_client_is_safe_when_client_already_removed():
    """_kick_slow_client must not raise if the client was already removed first."""
    mux = Multiplexer()
    ws = _ws(connected=True)
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    # Remove client before kick runs
    await mux.remove_client(client)
    assert mux.client_count == 0

    # Calling _kick_slow_client on an already-removed client must be a no-op
    await mux._kick_slow_client(client)

    assert mux.client_count == 0  # still 0 — no double-add


@pytest.mark.asyncio
async def test_kick_slow_client_closes_ws_with_1013():
    """_kick_slow_client must close the WebSocket with code 1013 (try-again-later)."""
    mux = Multiplexer()
    ws = _ws(connected=True)
    client = await mux.add_client(ws, bbox=(50.0, 5.0, 58.0, 25.0))

    await mux._kick_slow_client(client)

    ws.close.assert_awaited_once_with(code=1013)
    assert mux.client_count == 0

"""
Tests for UpstreamConnection — WebSocket reconnect, frame normalisation,
subscribe payload, and stop behaviour.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.upstream import UpstreamConnection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connection(api_key: str = "key", bbox=(50.0, 5.0, 58.0, 25.0)) -> UpstreamConnection:
    return UpstreamConnection(api_key=api_key, bbox=bbox)


def _position_report(mmsi: int = 123456789, lat: float = 54.0, lon: float = 12.0) -> str:
    return json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": "TEST VESSEL",
            "time_utc": "2026-01-01T00:00:00Z",
        },
        "Message": {
            "PositionReport": {
                "UserID": mmsi,
                "Latitude": lat,
                "Longitude": lon,
                "TrueHeading": 90,
                "Sog": 12.5,
            }
        },
    })


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

def test_empty_api_key_raises():
    with pytest.raises(ValueError, match="non-empty api_key"):
        UpstreamConnection(api_key="", bbox=(50.0, 5.0, 58.0, 25.0))


def test_initial_counters():
    conn = _make_connection()
    assert conn.reconnects == 0
    assert conn.frames_received == 0


# ---------------------------------------------------------------------------
# _subscribe_payload
# ---------------------------------------------------------------------------

def test_subscribe_payload_structure():
    conn = _make_connection(api_key="mykey", bbox=(50.0, 5.0, 58.0, 25.0))
    payload = json.loads(conn._subscribe_payload())
    assert payload["APIKey"] == "mykey"
    assert payload["FilterMessageTypes"] == ["PositionReport"]
    # bbox order: south-west then north-east  →  [[s, w], [n, e]]
    bb = payload["BoundingBoxes"][0]
    assert bb == [[50.0, 5.0], [58.0, 25.0]]


# ---------------------------------------------------------------------------
# _normalise — happy paths
# ---------------------------------------------------------------------------

def test_normalise_valid_position_report():
    raw = _position_report(mmsi=987654321, lat=55.5, lon=13.2)
    frame = UpstreamConnection._normalise(raw)
    assert frame is not None
    assert frame["mmsi"] == 987654321
    assert frame["lat"] == 55.5
    assert frame["lon"] == 13.2
    assert frame["vessel_name"] == "TEST VESSEL"
    assert frame["type"] == "ais_frame"
    assert frame["classification"] == 100


def test_normalise_bytes_input():
    raw = _position_report().encode("utf-8")
    frame = UpstreamConnection._normalise(raw)
    assert frame is not None
    assert frame["mmsi"] == 123456789


def test_normalise_heading_511_treated_as_unavailable():
    msg = json.loads(_position_report())
    msg["Message"]["PositionReport"]["TrueHeading"] = 511
    frame = UpstreamConnection._normalise(json.dumps(msg))
    assert frame is not None
    assert frame["heading_deg"] is None


def test_normalise_speed_over_102_3_treated_as_unavailable():
    msg = json.loads(_position_report())
    msg["Message"]["PositionReport"]["Sog"] = 102.3
    frame = UpstreamConnection._normalise(json.dumps(msg))
    assert frame is not None
    assert frame["speed_kn"] is None


def test_normalise_vessel_name_stripped():
    msg = json.loads(_position_report())
    msg["MetaData"]["ShipName"] = "  PADDED  "
    frame = UpstreamConnection._normalise(json.dumps(msg))
    assert frame["vessel_name"] == "PADDED"


def test_normalise_empty_vessel_name_becomes_none():
    msg = json.loads(_position_report())
    msg["MetaData"]["ShipName"] = "   "
    frame = UpstreamConnection._normalise(json.dumps(msg))
    assert frame["vessel_name"] is None


# ---------------------------------------------------------------------------
# _normalise — skip / reject paths
# ---------------------------------------------------------------------------

def test_normalise_non_position_report_returns_none():
    raw = json.dumps({"MessageType": "StandardClassBPositionReport"})
    assert UpstreamConnection._normalise(raw) is None


def test_normalise_missing_lat_returns_none():
    msg = json.loads(_position_report())
    del msg["Message"]["PositionReport"]["Latitude"]
    assert UpstreamConnection._normalise(json.dumps(msg)) is None


def test_normalise_missing_mmsi_returns_none():
    msg = json.loads(_position_report())
    del msg["MetaData"]["MMSI"]
    del msg["Message"]["PositionReport"]["UserID"]
    assert UpstreamConnection._normalise(json.dumps(msg)) is None


def test_normalise_malformed_json_returns_none():
    assert UpstreamConnection._normalise("{not-valid-json") is None


def test_normalise_invalid_utf8_bytes_returns_none():
    assert UpstreamConnection._normalise(b"\xff\xfe bad bytes") is None


# ---------------------------------------------------------------------------
# iter_frames — stop() terminates the generator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_iter_frames_stop_before_connect():
    conn = _make_connection()
    conn._stop.set()  # stop immediately

    frames = []
    async for frame in conn.iter_frames():
        frames.append(frame)

    assert frames == []


@pytest.mark.asyncio
async def test_iter_frames_yields_normalised_frames():
    """Mock websockets.connect so we can feed two frames then close."""
    conn = _make_connection()

    frame1 = _position_report(mmsi=111, lat=54.1, lon=10.0)
    frame2 = _position_report(mmsi=222, lat=54.2, lon=10.1)
    stop_evt = asyncio.Event()

    async def fake_ws_iter():
        yield frame1
        yield frame2
        conn._stop.set()  # signal stop after two frames

    ws_mock = AsyncMock()
    ws_mock.__aiter__ = MagicMock(return_value=fake_ws_iter())
    ws_mock.send = AsyncMock()
    ws_mock.close = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=ws_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.upstream.websockets.connect", return_value=ctx):
        frames = []
        async for f in conn.iter_frames():
            frames.append(f)

    assert len(frames) == 2
    assert frames[0]["mmsi"] == 111
    assert frames[1]["mmsi"] == 222
    assert conn.frames_received == 2


@pytest.mark.asyncio
async def test_iter_frames_reconnects_on_connection_closed():
    """ConnectionClosed increments reconnect counter; second connect yields stop."""
    from websockets.exceptions import ConnectionClosed

    conn = _make_connection()
    attempt = 0

    async def fake_ws_iter_error():
        # Raise on first connection attempt
        raise ConnectionClosed(None, None)
        yield  # unreachable but makes this an async generator

    async def fake_ws_iter_stop():
        conn._stop.set()
        yield  # nothing to yield — we just stop

    call_count = [0]

    async def fake_connect(*a, **kw):
        call_count[0] += 1

    class FakeCtx:
        def __init__(self, n):
            self._n = n
        async def __aenter__(self):
            ws = AsyncMock()
            if self._n == 0:
                async def _iter():
                    raise ConnectionClosed(None, None)
                    yield
                ws.__aiter__ = MagicMock(return_value=_iter())
            else:
                conn._stop.set()
                async def _iter2():
                    return
                    yield
                ws.__aiter__ = MagicMock(return_value=_iter2())
            ws.send = AsyncMock()
            return ws
        async def __aexit__(self, *a):
            return False

    connect_calls = [0]

    def make_ctx(*a, **kw):
        n = connect_calls[0]
        connect_calls[0] += 1
        return FakeCtx(n)

    with patch("app.upstream.websockets.connect", side_effect=make_ctx):
        with patch("asyncio.wait_for", return_value=None):  # skip backoff sleep
            frames = []
            async for f in conn.iter_frames():
                frames.append(f)

    assert conn.reconnects >= 1


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_sets_event_and_closes_ws():
    conn = _make_connection()
    ws_mock = AsyncMock()
    conn._ws = ws_mock

    await conn.stop()

    assert conn._stop.is_set()
    ws_mock.close.assert_awaited_once()
    assert conn._ws is None


@pytest.mark.asyncio
async def test_stop_when_ws_is_none_does_not_raise():
    conn = _make_connection()
    conn._ws = None
    await conn.stop()  # must not raise
    assert conn._stop.is_set()

"""
Test skeletons for JammingPoller lifecycle and edge case gaps.

Gaps covered:
  - start() creates scheduler and triggers immediate first fetch
  - stop() shuts scheduler down idempotently
  - _first_fetch() catches and logs exceptions without propagating
  - fetch_once(): cache.write_payload() raises → increments fetches_failed
  - fetch_once(): audit.record_fetch() raises → does NOT fail the tick (logged only)
  - AircraftWindow.flat_aircraft() when window is empty
  - nacp_aggregator: classify() protects against zero-count division
  - CacheRepo: aware-datetime stale-drop vs naive-datetime comparison
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.poller import JammingPoller
from app.settings import Settings


# ---------------------------------------------------------------------------
# Helpers (mirrors test_poller.py helpers)
# ---------------------------------------------------------------------------

def _settings(**overrides) -> MagicMock:
    defaults = dict(
        adsb_api_base="http://fake-adsb.local",
        adsb_center_lat=54.0,
        adsb_center_lon=10.0,
        adsb_radius_nm=250,
        refresh_minutes=5,
        window_samples=3,
        h3_resolution=4,
        nacp_low_threshold=3,
        nacp_high_threshold=20,
        band_step=50,
        cache_ttl_hours=6,
    )
    defaults.update(overrides)
    s = MagicMock(spec=Settings)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _fake_aircraft(count: int = 10) -> list[dict]:
    return [
        {"lat": 54.0 + i * 0.01, "lon": 10.0 + i * 0.01, "NACp": 8}
        for i in range(count)
    ]


def _make_poller(settings=None, cache=None, audit=None):
    s = settings or _settings()
    c = cache or AsyncMock()
    a = audit or AsyncMock()
    return JammingPoller(settings=s, cache=c, audit=a)


# ---------------------------------------------------------------------------
# start() / stop() lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_creates_scheduler():
    """start() must create an AsyncIOScheduler with the fetch job registered."""
    poller = _make_poller()

    with patch("app.poller.AsyncIOScheduler") as mock_scheduler_cls:
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        with patch.object(poller, "_first_fetch", new=AsyncMock()):
            await poller.start()

    mock_scheduler_cls.assert_called_once()
    mock_scheduler.add_job.assert_called_once()
    add_job_kwargs = mock_scheduler.add_job.call_args
    # fetch_once must be the scheduled callable
    assert add_job_kwargs[0][0] is poller.fetch_once
    mock_scheduler.start.assert_called_once()


@pytest.mark.asyncio
async def test_start_creates_immediate_first_fetch_task():
    """start() must schedule _first_fetch() immediately (not wait refresh_minutes)."""
    poller = _make_poller()
    first_fetch_called = asyncio.Event()

    async def _fake_first_fetch():
        first_fetch_called.set()

    with patch("app.poller.AsyncIOScheduler") as mock_scheduler_cls:
        mock_scheduler_cls.return_value = MagicMock()
        with patch.object(poller, "_first_fetch", side_effect=_fake_first_fetch):
            await poller.start()
            # give the task a tick to run
            await asyncio.sleep(0)

    assert first_fetch_called.is_set(), "_first_fetch was not called immediately on start()"


@pytest.mark.asyncio
async def test_stop_shuts_scheduler_down():
    """stop() must call scheduler.shutdown(wait=False) and clear reference."""
    poller = _make_poller()

    mock_scheduler = MagicMock()
    poller._scheduler = mock_scheduler

    await poller.stop()

    mock_scheduler.shutdown.assert_called_once_with(wait=False)
    assert poller._scheduler is None


@pytest.mark.asyncio
async def test_stop_is_idempotent_when_not_started():
    """stop() on an unstarted poller must not raise."""
    poller = _make_poller()
    assert poller._scheduler is None
    await poller.stop()  # must not raise


# ---------------------------------------------------------------------------
# _first_fetch() — exception swallowed, not propagated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_fetch_catches_exceptions_from_fetch_once():
    """_first_fetch() must catch any exception from fetch_once() and log it."""
    poller = _make_poller()

    with patch.object(
        poller, "fetch_once", new=AsyncMock(side_effect=RuntimeError("boom"))
    ):
        # Must not raise — exceptions are swallowed and logged
        await poller._first_fetch()


# ---------------------------------------------------------------------------
# fetch_once — cache write failure → increments fetches_failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_once_cache_write_failure_increments_failed():
    """When cache.write_payload() raises, fetches_failed must increment."""
    cache = AsyncMock()
    cache.write_payload.side_effect = RuntimeError("DB unavailable")
    poller = _make_poller(cache=cache)

    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"ac": _fake_aircraft(10)})

    fake_payload = {"features": [{"type": "Feature"}], "stats": {}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=fake_payload):
            await poller.fetch_once()

    assert poller.fetches_failed == 1
    assert poller.fetches_ok == 0


# ---------------------------------------------------------------------------
# fetch_once — audit failure must NOT fail the tick
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_once_audit_failure_does_not_fail_tick():
    """Audit write failure must be logged but must not flip fetches_ok to failed."""
    cache = AsyncMock()
    audit = AsyncMock()
    audit.record_fetch.side_effect = RuntimeError("audit DB down")
    poller = _make_poller(cache=cache, audit=audit)

    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"ac": _fake_aircraft(10)})

    fake_payload = {"features": [{"type": "Feature"}], "stats": {}}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.poller.aggregate_aircraft_to_hex", return_value=fake_payload):
            await poller.fetch_once()

    # Audit failure must not roll back the ok counter
    assert poller.fetches_ok == 1
    assert poller.fetches_failed == 0


# ---------------------------------------------------------------------------
# AircraftWindow — flat_aircraft() on empty window
# ---------------------------------------------------------------------------

def test_aircraft_window_flat_aircraft_empty():
    """flat_aircraft() on a fresh window must yield nothing without raising."""
    try:
        from app.aircraft_window import AircraftWindow  # type: ignore
    except ImportError:
        pytest.skip("AircraftWindow not yet importable")

    window = AircraftWindow(max_samples=5)
    result = list(window.flat_aircraft())
    assert result == []


def test_aircraft_window_flat_aircraft_after_add():
    """flat_aircraft() yields all aircraft from the window after add_snapshot()."""
    try:
        from app.aircraft_window import AircraftWindow  # type: ignore
    except ImportError:
        pytest.skip("AircraftWindow not yet importable")

    aircraft = [{"lat": 54.0, "lon": 10.0, "NACp": 5}]
    window = AircraftWindow(max_samples=3)
    window.add_snapshot(aircraft, ts=datetime.now(timezone.utc))

    result = list(window.flat_aircraft())
    assert len(result) == 1
    assert result[0]["lat"] == 54.0


# ---------------------------------------------------------------------------
# nacp_aggregator — classify() with zero total count
# ---------------------------------------------------------------------------

def test_nacp_classify_zero_total_does_not_raise():
    """classify() must handle zero-count cell without ZeroDivisionError."""
    try:
        from app.nacp_aggregator import classify  # type: ignore
    except ImportError:
        pytest.skip("classify not yet importable")

    # zero total → should return some valid classification, not raise
    result = classify(low_count=0, total=0)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# CacheRepo — aware vs naive datetime stale-drop
# ---------------------------------------------------------------------------

def test_cache_repo_aware_datetime_marked_stale():
    """Aware datetime older than max_age_hours must be marked stale."""
    try:
        from app.cache_repo import CacheRepo  # type: ignore
    except ImportError:
        pytest.skip("CacheRepo not yet importable")

    mock_pool = MagicMock()
    repo = CacheRepo(pool=mock_pool, max_age_hours=1)

    stale_ts = datetime.now(timezone.utc) - timedelta(hours=2)

    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone = MagicMock(return_value=(b'{"features":[]}', stale_ts))
    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_pool.acquire = MagicMock(return_value=mock_conn)

    # read_latest may be sync or async depending on implementation
    import inspect
    result_fn = repo.read_latest
    if asyncio.iscoroutinefunction(result_fn):
        result = asyncio.get_event_loop().run_until_complete(result_fn(layer="jamming"))
    else:
        result = result_fn(layer="jamming")

    assert result is None, "stale row must return None"
    assert repo.stale_drops >= 1

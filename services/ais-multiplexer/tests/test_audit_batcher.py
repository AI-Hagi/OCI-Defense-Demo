"""
Tests for AuditBatcher — add(), flush(), timer-driven flush, retry logic,
start()/stop() lifecycle, and counter accuracy.

Gaps covered:
  - add() triggers flush when batch reaches audit_flush_frames limit
  - add() accumulates frames without flushing below the limit
  - flush() no-ops on an empty batch
  - flush() writes INSERT with correct SQL and binds
  - flush() retries up to 3 times on DBPoolUnavailable before incrementing write_failures_total
  - flush() increments writes_total on success
  - flush() resets the batch after writing
  - flush() increments write_failures_total after all 3 retries fail
  - start() creates the timer task
  - stop() flushes remaining batch and cancels timer task
  - stop() is idempotent when called twice
  - _timer_loop flushes when batch age exceeds audit_flush_seconds
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.audit import AuditBatcher, AuditFrame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(flush_frames: int = 50, flush_seconds: float = 10.0) -> MagicMock:
    s = MagicMock()
    s.audit_flush_frames = flush_frames
    s.audit_flush_seconds = flush_seconds
    return s


def _db(fail: bool = False, fail_times: int = 0) -> MagicMock:
    db = MagicMock()
    if fail:
        from app.db import DBPoolUnavailable  # type: ignore
        db.execute = AsyncMock(side_effect=DBPoolUnavailable("pool down"))
    elif fail_times > 0:
        from app.db import DBPoolUnavailable  # type: ignore
        side_effects = [DBPoolUnavailable("pool down")] * fail_times + [None]
        db.execute = AsyncMock(side_effect=side_effects)
    else:
        db.execute = AsyncMock(return_value=None)
    return db


def _frame(mmsi: int = 123, ts: str = "2026-01-01T00:00:00Z") -> AuditFrame:
    return AuditFrame(mmsi=mmsi, ts=ts, lat=54.0, lon=12.0)


def _batcher(flush_frames: int = 50, flush_seconds: float = 10.0, db=None):
    s = _settings(flush_frames=flush_frames, flush_seconds=flush_seconds)
    d = db if db is not None else _db()
    return AuditBatcher(
        bbox=(53.0, 8.0, 56.0, 22.0),
        tenant_id="T001",
        settings=s,
        db_pool=d,
    )


# ---------------------------------------------------------------------------
# flush() — empty batch is a no-op
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_noop_on_empty_batch():
    batcher = _batcher()
    await batcher.flush()
    batcher._db.execute.assert_not_awaited()
    assert batcher.writes_total == 0


# ---------------------------------------------------------------------------
# flush() — inserts correct SQL and binds on non-empty batch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_executes_insert_with_correct_actor_and_action():
    batcher = _batcher(flush_frames=5)
    await batcher.add(_frame(mmsi=111, ts="2026-01-01T00:00:00Z"))
    await batcher.flush()

    batcher._db.execute.assert_awaited_once()
    sql, binds = batcher._db.execute.await_args.args
    assert "INSERT INTO audit_events" in sql
    assert binds["actor_service"] == "ais-multiplexer"
    assert binds["action"] == "ais_frame_batch"
    assert binds["resource_type"] == "vessel"
    assert binds["resource_id"] is None
    assert binds["tenant_id"] == "T001"
    assert binds["ols_label"] == 100


@pytest.mark.asyncio
async def test_flush_payload_contains_frame_count_and_mmsi_sample():
    import json
    batcher = _batcher()
    await batcher.add(_frame(mmsi=999, ts="2026-01-01T12:00:00Z"))
    await batcher.flush()

    _, binds = batcher._db.execute.await_args.args
    payload = json.loads(binds["payload"])
    assert payload["frame_count"] == 1
    assert 999 in payload["mmsi_sample"]


# ---------------------------------------------------------------------------
# flush() — increments writes_total on success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_increments_writes_total():
    batcher = _batcher()
    await batcher.add(_frame())
    await batcher.flush()
    assert batcher.writes_total == 1


# ---------------------------------------------------------------------------
# flush() — resets batch to empty after write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_resets_batch_after_write():
    batcher = _batcher()
    await batcher.add(_frame())
    await batcher.flush()
    # Second flush should be a no-op (batch was cleared)
    call_count_before = batcher._db.execute.await_count
    await batcher.flush()
    assert batcher._db.execute.await_count == call_count_before


# ---------------------------------------------------------------------------
# flush() — retries up to 3 times on DBPoolUnavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_retries_on_pool_unavailable_then_increments_failures():
    try:
        from app.db import DBPoolUnavailable  # type: ignore
    except ImportError:
        pytest.skip("app.db.DBPoolUnavailable not importable")

    # All 3 attempts fail → write_failures_total must become 1
    db = _db(fail=True)
    batcher = _batcher(db=db)
    batcher._settings.audit_flush_seconds = 1  # irrelevant here

    with patch("asyncio.sleep", new=AsyncMock()):  # skip backoff delays
        await batcher.add(_frame())
        await batcher.flush()

    assert batcher.write_failures_total == 1
    assert batcher.writes_total == 0
    # execute must have been called exactly 3 times
    assert batcher._db.execute.await_count == 3


@pytest.mark.asyncio
async def test_flush_succeeds_on_second_attempt_after_pool_failure():
    try:
        from app.db import DBPoolUnavailable  # type: ignore
    except ImportError:
        pytest.skip("app.db.DBPoolUnavailable not importable")

    db = _db(fail_times=1)  # fails once then succeeds
    batcher = _batcher(db=db)

    with patch("asyncio.sleep", new=AsyncMock()):
        await batcher.add(_frame())
        await batcher.flush()

    assert batcher.writes_total == 1
    assert batcher.write_failures_total == 0
    assert batcher._db.execute.await_count == 2


# ---------------------------------------------------------------------------
# add() — size-triggered flush
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_triggers_flush_at_flush_frames_limit():
    batcher = _batcher(flush_frames=3)
    for i in range(3):
        await batcher.add(_frame(mmsi=i))
    # Flush must have been triggered by the 3rd add()
    assert batcher.writes_total == 1


@pytest.mark.asyncio
async def test_add_does_not_flush_below_limit():
    batcher = _batcher(flush_frames=10)
    for i in range(9):
        await batcher.add(_frame(mmsi=i))
    assert batcher.writes_total == 0
    batcher._db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# start() — creates timer task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_creates_timer_task():
    batcher = _batcher(flush_seconds=3600.0)  # long flush window so timer doesn't fire
    await batcher.start()
    assert batcher._timer_task is not None
    assert not batcher._timer_task.done()
    await batcher.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent():
    batcher = _batcher(flush_seconds=3600.0)
    await batcher.start()
    task_id = id(batcher._timer_task)
    await batcher.start()  # second call must not replace the running task
    assert id(batcher._timer_task) == task_id
    await batcher.stop()


# ---------------------------------------------------------------------------
# stop() — flushes remaining batch, cancels timer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_flushes_remaining_frames():
    batcher = _batcher(flush_frames=100, flush_seconds=3600.0)
    await batcher.start()
    await batcher.add(_frame())
    await batcher.stop()
    assert batcher.writes_total == 1


@pytest.mark.asyncio
async def test_stop_cancels_timer_task():
    batcher = _batcher(flush_seconds=3600.0)
    await batcher.start()
    task = batcher._timer_task
    await batcher.stop()
    assert task.done()
    assert batcher._timer_task is None


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    batcher = _batcher(flush_seconds=3600.0)
    await batcher.start()
    await batcher.stop()
    await batcher.stop()  # must not raise


# ---------------------------------------------------------------------------
# _timer_loop — time-triggered flush
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timer_loop_flushes_when_batch_age_exceeds_flush_seconds():
    """After audit_flush_seconds the timer loop must trigger a flush."""
    # Use a very short flush window and control time with a fake sleep.
    batcher = _batcher(flush_frames=1000, flush_seconds=0.05)

    await batcher.add(_frame())

    # Start the timer and wait just long enough for it to fire once.
    await batcher.start()
    await asyncio.sleep(0.2)
    await batcher.stop()

    assert batcher.writes_total >= 1

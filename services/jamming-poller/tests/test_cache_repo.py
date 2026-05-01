"""
Tests for CacheRepo — write_payload, read_latest, TTL staleness, LOB handling,
and hit/miss/stale counters.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.cache_repo import CacheRepo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(fetchone_result=None):
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetchone = AsyncMock(return_value=fetchone_result)
    return pool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_dict() -> dict:
    return {"features": [{"type": "Feature", "geometry": None}], "stats": {}}


# ---------------------------------------------------------------------------
# write_payload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_payload_calls_pool_execute():
    pool = _pool()
    repo = CacheRepo(pool=pool)

    await repo.write_payload(
        layer="jamming",
        payload=_payload_dict(),
        classification="OPEN",
        source="test",
    )

    pool.execute.assert_awaited_once()
    call_args = pool.execute.await_args
    params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("params", {})
    if isinstance(params, dict):
        assert params.get("layer") == "jamming"
        assert params.get("classification") == "OPEN"
        assert params.get("source") == "test"


@pytest.mark.asyncio
async def test_write_payload_serialises_dict_to_json_string():
    pool = _pool()
    repo = CacheRepo(pool=pool)
    p = _payload_dict()

    await repo.write_payload(layer="jamming", payload=p, classification="OPEN", source="s")

    params = pool.execute.await_args.args[1]
    assert isinstance(params["payload"], str)
    decoded = json.loads(params["payload"])
    assert decoded == p


@pytest.mark.asyncio
async def test_write_payload_uses_provided_fetched_at():
    pool = _pool()
    repo = CacheRepo(pool=pool)
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    await repo.write_payload(layer="jamming", payload=_payload_dict(),
                             classification="OPEN", source="s", fetched_at=ts)

    params = pool.execute.await_args.args[1]
    assert params["fetched_at"] == ts


# ---------------------------------------------------------------------------
# read_latest — miss (no row)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_latest_returns_none_on_cache_miss():
    repo = CacheRepo(pool=_pool(fetchone_result=None))
    result = await repo.read_latest("jamming")
    assert result is None
    assert repo.misses == 1
    assert repo.hits == 0


# ---------------------------------------------------------------------------
# read_latest — hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_latest_returns_parsed_payload():
    payload = _payload_dict()
    fetched_at = _now()
    row = (json.dumps(payload), fetched_at, "test-source")

    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming")

    assert result is not None
    assert result["features"] == payload["features"]
    assert repo.hits == 1
    assert repo.misses == 0


@pytest.mark.asyncio
async def test_read_latest_injects_fetched_at_and_source():
    payload = _payload_dict()
    fetched_at = _now()
    row = (json.dumps(payload), fetched_at, "src-123")

    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming")

    assert result["source"] == "src-123"
    assert "fetched_at" in result


# ---------------------------------------------------------------------------
# read_latest — LOB handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_latest_handles_lob_object():
    payload = _payload_dict()
    fetched_at = _now()

    lob = MagicMock()
    lob.read = MagicMock(return_value=json.dumps(payload))

    row = (lob, fetched_at, "lob-source")
    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming")

    assert result["features"] == payload["features"]
    lob.read.assert_called_once()


@pytest.mark.asyncio
async def test_read_latest_handles_bytes_payload():
    payload = _payload_dict()
    fetched_at = _now()
    row = (json.dumps(payload).encode("utf-8"), fetched_at, "bytes-source")

    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming")

    assert result is not None
    assert result["features"] == payload["features"]


# ---------------------------------------------------------------------------
# read_latest — TTL staleness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_latest_stale_row_returns_none():
    payload = _payload_dict()
    old_ts = _now() - timedelta(hours=25)
    row = (json.dumps(payload), old_ts, "s")

    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming", max_age_hours=24)

    assert result is None
    assert repo.stale_drops == 1
    assert repo.hits == 0


@pytest.mark.asyncio
async def test_read_latest_fresh_row_within_ttl_is_returned():
    payload = _payload_dict()
    recent_ts = _now() - timedelta(hours=1)
    row = (json.dumps(payload), recent_ts, "s")

    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming", max_age_hours=24)

    assert result is not None
    assert repo.stale_drops == 0
    assert repo.hits == 1


@pytest.mark.asyncio
async def test_read_latest_no_max_age_ignores_timestamp():
    payload = _payload_dict()
    very_old_ts = _now() - timedelta(days=365)
    row = (json.dumps(payload), very_old_ts, "s")

    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming")  # no max_age_hours

    assert result is not None
    assert repo.stale_drops == 0


@pytest.mark.asyncio
async def test_read_latest_naive_datetime_treated_as_utc():
    payload = _payload_dict()
    # naive datetime (no tzinfo) — older than max_age_hours
    naive_old = datetime.now() - timedelta(hours=25)
    row = (json.dumps(payload), naive_old, "s")

    repo = CacheRepo(pool=_pool(fetchone_result=row))
    result = await repo.read_latest("jamming", max_age_hours=24)

    assert result is None
    assert repo.stale_drops == 1

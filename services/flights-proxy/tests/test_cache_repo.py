"""Unit tests for CacheRepo in flights-proxy.

Note: flights-proxy uses max_age_minutes (not max_age_hours like tle-proxy).

Gaps: cold miss, TTL stale-drop (minute-granularity), fresh hit,
LOB/bytes payload deserialization, counter bookkeeping.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_pool(fetchone_return=None):
    pool = MagicMock(name="DBPool")
    pool.execute = AsyncMock(return_value=None)
    pool.fetchone = AsyncMock(return_value=fetchone_return)
    return pool


FRESH_AT = datetime.now(timezone.utc) - timedelta(minutes=2)
STALE_AT = datetime.now(timezone.utc) - timedelta(hours=3)
PAYLOAD_DICT = {"type": "FeatureCollection", "layer": "flights-civil", "features": []}


class TestWritePayload:
    def test_execute_called_with_layer(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("flights-civil", PAYLOAD_DICT, "OPEN", "opensky.network")
        )
        pool.execute.assert_called_once()
        _, binds = pool.execute.call_args.args
        assert binds["layer"] == "flights-civil"

    def test_payload_json_serialised(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("flights-civil", PAYLOAD_DICT, "OPEN", "opensky.network")
        )
        _, binds = pool.execute.call_args.args
        parsed = json.loads(binds["payload"])
        assert parsed["layer"] == "flights-civil"


class TestReadLatest:
    def test_cold_cache_returns_none_and_increments_miss(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool(fetchone_return=None)
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil")
        )
        assert result is None
        assert repo.misses == 1
        assert repo.hits == 0

    def test_fresh_hit_returns_payload_and_increments_hit(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "opensky.network"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil")
        )
        assert result is not None
        assert result["layer"] == "flights-civil"
        assert repo.hits == 1

    def test_stale_row_with_minute_ttl_returns_none(self):
        """Stale-drop uses max_age_minutes — check minute granularity."""
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, STALE_AT, "opensky.network"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil", max_age_minutes=30)
        )
        assert result is None
        assert repo.stale_drops == 1

    def test_no_max_age_returns_any_row(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, STALE_AT, "opensky.network"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil")
        )
        assert result is not None
        assert repo.stale_drops == 0

    def test_lob_payload_decoded(self):
        from app.cache_repo import CacheRepo  # type: ignore

        lob = MagicMock()
        lob.read.return_value = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(lob, FRESH_AT, "opensky.network"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil")
        )
        assert result is not None
        assert result["type"] == "FeatureCollection"

    def test_bytes_payload_decoded(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT).encode("utf-8")
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "opensky.network"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil")
        )
        assert result is not None

    def test_source_and_fetched_at_injected(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps({"type": "FeatureCollection", "features": []})
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "opensky.network"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil")
        )
        assert result is not None
        assert result.get("source") == "opensky.network"
        assert "fetched_at" in result

    def test_naive_fetched_at_treated_as_utc(self):
        from app.cache_repo import CacheRepo  # type: ignore

        naive_old = datetime.utcnow() - timedelta(hours=5)
        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, naive_old, "opensky.network"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("flights-civil", max_age_minutes=30)
        )
        assert result is None
        assert repo.stale_drops == 1

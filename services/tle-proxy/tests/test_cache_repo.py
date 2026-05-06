"""Unit tests for CacheRepo in tle-proxy.

Gaps: cold miss, TTL stale-drop, fresh hit, LOB/bytes/str payload
deserialization, counter bookkeeping.
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


FRESH_AT = datetime.now(timezone.utc) - timedelta(minutes=5)
STALE_AT = datetime.now(timezone.utc) - timedelta(hours=25)
PAYLOAD_DICT = {"type": "TleCollection", "group": "active", "count": 3, "tle": []}


class TestWritePayload:
    def test_execute_called_with_layer_and_payload(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload(
                layer="satellites-active",
                payload=PAYLOAD_DICT,
                classification="OPEN",
                source="celestrak.org",
                fetched_at=FRESH_AT,
            )
        )
        pool.execute.assert_called_once()
        _, binds = pool.execute.call_args.args
        assert binds["layer"] == "satellites-active"
        assert binds["classification"] == "OPEN"
        parsed = json.loads(binds["payload"])
        assert parsed["group"] == "active"

    def test_fetched_at_defaults_to_now_when_none(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        before = datetime.now(timezone.utc)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("satellites-active", PAYLOAD_DICT, "OPEN", "celestrak.org")
        )
        after = datetime.now(timezone.utc)
        _, binds = pool.execute.call_args.args
        ts = binds["fetched_at"]
        assert before <= ts <= after


class TestReadLatest:
    def test_cold_cache_returns_none_and_increments_miss(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool(fetchone_return=None)
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-active")
        )
        assert result is None
        assert repo.misses == 1
        assert repo.hits == 0

    def test_fresh_hit_returns_payload_and_increments_hit(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "celestrak.org"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-active")
        )
        assert result is not None
        assert result["group"] == "active"
        assert repo.hits == 1
        assert repo.misses == 0

    def test_stale_row_returns_none_and_increments_stale_drop(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, STALE_AT, "celestrak.org"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-active", max_age_hours=1)
        )
        assert result is None
        assert repo.stale_drops == 1
        assert repo.hits == 0

    def test_no_max_age_returns_stale_row(self):
        """When max_age_hours is omitted the TTL check is skipped."""
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, STALE_AT, "celestrak.org"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-active")
        )
        assert result is not None
        assert repo.stale_drops == 0

    def test_lob_payload_is_decoded(self):
        from app.cache_repo import CacheRepo  # type: ignore

        lob = MagicMock()
        lob.read.return_value = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(lob, FRESH_AT, "celestrak.org"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-active")
        )
        assert result is not None
        assert result["type"] == "TleCollection"
        lob.read.assert_called_once()

    def test_bytes_payload_is_decoded(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT).encode("utf-8")
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "celestrak.org"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-active")
        )
        assert result is not None
        assert result["count"] == 3

    def test_fetched_at_and_source_injected_into_payload(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps({"type": "TleCollection", "group": "resource"})
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "celestrak.org"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-resource")
        )
        assert result is not None
        assert result.get("source") == "celestrak.org"
        assert "fetched_at" in result

    def test_naive_fetched_at_treated_as_utc_for_ttl(self):
        """Naive datetimes (no tzinfo) must be coerced to UTC so the stale check works."""
        from app.cache_repo import CacheRepo  # type: ignore

        naive_old = datetime.utcnow() - timedelta(hours=48)
        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, naive_old, "celestrak.org"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("satellites-active", max_age_hours=1)
        )
        assert result is None
        assert repo.stale_drops == 1

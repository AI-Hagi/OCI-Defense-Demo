"""Unit tests for CacheRepo in ports-proxy.

Gap: no test file exists — audit and cache are only exercised implicitly
through test_main.py. Covers:

  - write_payload: execute called with correct layer and serialised JSON
  - read_latest: cold miss (no row), fresh hit, stale-drop (max_age_hours),
    LOB payload, bytes payload, naive timestamp treated as UTC,
    source/fetched_at injected into returned dict
  - Counter bookkeeping: hits, misses, stale_drops

Note: ports-proxy uses max_age_hours (hours), not max_age_minutes like
flights-proxy.
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


FRESH_AT = datetime.now(timezone.utc) - timedelta(minutes=30)
STALE_AT = datetime.now(timezone.utc) - timedelta(hours=25)
PAYLOAD_DICT = {"type": "FeatureCollection", "layer": "ports", "features": []}


class TestWritePayload:
    def test_execute_called_with_correct_layer(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("ports", PAYLOAD_DICT, "OPEN", "overpass-api")
        )
        pool.execute.assert_called_once()
        _, binds = pool.execute.call_args.args
        assert binds["layer"] == "ports"

    def test_payload_json_serialised(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("ports", PAYLOAD_DICT, "OPEN", "overpass-api")
        )
        _, binds = pool.execute.call_args.args
        parsed = json.loads(binds["payload"])
        assert parsed["layer"] == "ports"

    def test_classification_passed_through(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("ports", PAYLOAD_DICT, "RESTRICTED", "overpass-api")
        )
        _, binds = pool.execute.call_args.args
        assert binds["classification"] == "RESTRICTED"

    def test_source_passed_through(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("ports", PAYLOAD_DICT, "OPEN", "overpass-api")
        )
        _, binds = pool.execute.call_args.args
        assert binds["source"] == "overpass-api"

    def test_custom_fetched_at_respected(self):
        from app.cache_repo import CacheRepo  # type: ignore

        fixed_ts = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        pool = _make_pool()
        repo = CacheRepo(pool=pool)
        asyncio.get_event_loop().run_until_complete(
            repo.write_payload("ports", PAYLOAD_DICT, "OPEN", "overpass-api", fetched_at=fixed_ts)
        )
        _, binds = pool.execute.call_args.args
        assert binds["fetched_at"] == fixed_ts


class TestReadLatest:
    def test_cold_cache_returns_none_and_increments_miss(self):
        from app.cache_repo import CacheRepo  # type: ignore

        pool = _make_pool(fetchone_return=None)
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports")
        )
        assert result is None
        assert repo.misses == 1
        assert repo.hits == 0

    def test_fresh_hit_returns_payload_and_increments_hit(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports")
        )
        assert result is not None
        assert result["layer"] == "ports"
        assert repo.hits == 1
        assert repo.misses == 0

    def test_stale_row_with_hour_ttl_returns_none(self):
        """max_age_hours=24 — row fetched 25 h ago is stale."""
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, STALE_AT, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports", max_age_hours=24)
        )
        assert result is None
        assert repo.stale_drops == 1
        assert repo.hits == 0

    def test_fresh_row_within_ttl_is_returned(self):
        """Row fetched 30 min ago passes a 24h TTL."""
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports", max_age_hours=24)
        )
        assert result is not None
        assert repo.stale_drops == 0
        assert repo.hits == 1

    def test_no_max_age_returns_stale_row_without_drop(self):
        """Without a TTL constraint, any existing row should be returned."""
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, STALE_AT, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports")
        )
        assert result is not None
        assert repo.stale_drops == 0

    def test_lob_payload_decoded(self):
        """Oracle JSON LOB objects expose a .read() method."""
        from app.cache_repo import CacheRepo  # type: ignore

        lob = MagicMock()
        lob.read.return_value = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(lob, FRESH_AT, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports")
        )
        assert result is not None
        assert result["type"] == "FeatureCollection"
        lob.read.assert_called_once()

    def test_bytes_payload_decoded(self):
        """Payload returned as bytes (driver-level encoding) is decoded."""
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT).encode("utf-8")
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports")
        )
        assert result is not None
        assert result["type"] == "FeatureCollection"

    def test_source_and_fetched_at_injected_into_result(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps({"type": "FeatureCollection", "features": []})
        pool = _make_pool(fetchone_return=(raw, FRESH_AT, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports")
        )
        assert result is not None
        assert result.get("source") == "overpass-api"
        assert "fetched_at" in result

    def test_naive_fetched_at_treated_as_utc(self):
        """A timezone-naive timestamp from Oracle is treated as UTC."""
        from app.cache_repo import CacheRepo  # type: ignore

        naive_old = datetime.utcnow() - timedelta(hours=30)
        raw = json.dumps(PAYLOAD_DICT)
        pool = _make_pool(fetchone_return=(raw, naive_old, "overpass-api"))
        repo = CacheRepo(pool=pool)
        result = asyncio.get_event_loop().run_until_complete(
            repo.read_latest("ports", max_age_hours=24)
        )
        assert result is None
        assert repo.stale_drops == 1

    def test_counter_hits_and_misses_are_independent(self):
        from app.cache_repo import CacheRepo  # type: ignore

        raw = json.dumps(PAYLOAD_DICT)
        pool_hit = _make_pool(fetchone_return=(raw, FRESH_AT, "overpass-api"))
        pool_miss = _make_pool(fetchone_return=None)
        repo_h = CacheRepo(pool=pool_hit)
        repo_m = CacheRepo(pool=pool_miss)
        asyncio.get_event_loop().run_until_complete(repo_h.read_latest("ports"))
        asyncio.get_event_loop().run_until_complete(repo_m.read_latest("ports"))
        assert repo_h.hits == 1 and repo_h.misses == 0
        assert repo_m.misses == 1 and repo_m.hits == 0

"""
Tests for the GEOINT service /health endpoint.

Gaps covered:
  - GET /health returns 200 with status=ok when DB is healthy
  - GET /health returns 200 with db=ok when SELECT 1 succeeds
  - GET /health returns 200 with db=degraded when pool.acquire() raises
  - GET /health returns 200 with db=degraded when cursor.execute() raises
  - GET /health does not return 500 even when DB is completely unreachable
  - GET /health response body always contains 'service' key = 'geoint'
  - Concurrent /health calls all return without blocking each other
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient
    from app.main import app  # type: ignore
    _APP_IMPORTABLE = True
except Exception:
    _APP_IMPORTABLE = False


def _client():
    if not _APP_IMPORTABLE:
        pytest.skip("app.main not importable in CI (missing GEOINT deps)")
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers — mock connection and pool factory
# ---------------------------------------------------------------------------

def _mock_pool(select_raises: Exception | None = None, acquire_raises: Exception | None = None):
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    if select_raises:
        cursor.execute.side_effect = select_raises
    else:
        cursor.execute.return_value = None
        cursor.fetchone.return_value = (1,)

    conn = MagicMock()
    conn.cursor.return_value = cursor

    pool = MagicMock()
    if acquire_raises:
        pool.acquire.side_effect = acquire_raises
    else:
        pool.acquire.return_value = conn

    return pool


# ---------------------------------------------------------------------------
# /health — DB healthy
# ---------------------------------------------------------------------------

def test_health_returns_200_when_db_ok():
    client = _client()
    pool = _mock_pool()
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    assert resp.status_code == 200


def test_health_returns_status_ok_when_db_ok():
    client = _client()
    pool = _mock_pool()
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_health_response_contains_service_key():
    client = _client()
    pool = _mock_pool()
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    assert resp.json()["service"] == "geoint"


# ---------------------------------------------------------------------------
# /health — DB unreachable (pool.acquire raises)
# ---------------------------------------------------------------------------

def test_health_returns_200_when_pool_acquire_raises():
    """Even with a crashed DB pool, /health must return HTTP 200 (not 500)."""
    client = _client()
    pool = _mock_pool(acquire_raises=RuntimeError("ORA-12543: TNS:destination unreachable"))
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    assert resp.status_code == 200


def test_health_returns_db_degraded_when_pool_acquire_raises():
    client = _client()
    pool = _mock_pool(acquire_raises=RuntimeError("connection refused"))
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    assert resp.json()["db"] == "degraded"


# ---------------------------------------------------------------------------
# /health — DB reachable but query fails
# ---------------------------------------------------------------------------

def test_health_returns_200_when_select_raises():
    client = _client()
    pool = _mock_pool(select_raises=RuntimeError("ORA-00942: table or view does not exist"))
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    assert resp.status_code == 200


def test_health_returns_db_degraded_when_select_raises():
    client = _client()
    pool = _mock_pool(select_raises=RuntimeError("ORA-01034: ORACLE not available"))
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    assert resp.json()["db"] == "degraded"


# ---------------------------------------------------------------------------
# /health — status key is always "ok" (service-level, not DB-level)
# ---------------------------------------------------------------------------

def test_health_status_is_always_ok_regardless_of_db():
    """The top-level 'status' field is about service liveness, not DB health."""
    client = _client()
    pool = _mock_pool(acquire_raises=Exception("total failure"))
    with patch("app.main.get_pool", return_value=pool):
        resp = client.get("/health")
    # Service is alive; individual component degradation is shown in 'db' key.
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# /health — get_pool() itself raises (e.g., pool never initialised)
# ---------------------------------------------------------------------------

def test_health_survives_get_pool_raising():
    """get_pool() can raise before any connection is acquired — must not 500."""
    client = _client()
    with patch("app.main.get_pool", side_effect=RuntimeError("pool not initialised")):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "degraded"


# ---------------------------------------------------------------------------
# /health — concurrent calls do not block each other
# ---------------------------------------------------------------------------

def test_health_handles_concurrent_calls():
    """Smoke test: N simultaneous /health calls all succeed."""
    import threading

    client = _client()
    pool = _mock_pool()
    results: list[int] = []

    def call():
        with patch("app.main.get_pool", return_value=pool):
            r = client.get("/health")
        results.append(r.status_code)

    threads = [threading.Thread(target=call) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(results) == 10
    assert all(c == 200 for c in results), f"Unexpected status codes: {results}"

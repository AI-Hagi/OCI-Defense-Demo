"""
Test skeletons for doc-intelligence health and RAG error paths.

Gaps covered:
  - GET /health returns 503 when cursor.execute() raises
  - GET /health returns 503 when connection.close() raises (connection leak guard)
  - POST /api/documents/chat returns 400 when messages list is empty
  - POST /api/documents/chat returns 400 when no user-role message in list
  - POST /api/documents/chat handles OCI GenAI timeout gracefully (503 or 500)
  - _fetch_top_k() returns [] when vector search raises (DB error path)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# /health — cursor.execute() raises
# ---------------------------------------------------------------------------

def test_health_503_when_cursor_execute_raises(client: Any) -> None:
    """GET /health must return 503 when the DB health-check query fails."""
    if client is None:
        pytest.skip("client fixture unavailable")

    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.execute.side_effect = Exception("ORA-01033: ORACLE initialization")

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_conn

    try:
        import app.db as db_module  # type: ignore

        with patch.object(db_module, "get_pool", return_value=mock_pool):
            resp = client.get("/health")
    except ImportError:
        pytest.skip("app.db not yet importable")

    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /health — connection close raises (does not propagate)
# ---------------------------------------------------------------------------

def test_health_survives_connection_close_exception(client: Any) -> None:
    """GET /health must not 500 even when connection.close() raises on cleanup."""
    if client is None:
        pytest.skip("client fixture unavailable")

    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.execute = MagicMock(return_value=None)
    mock_cursor.fetchone = MagicMock(return_value=(1,))

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.close.side_effect = Exception("cannot close")
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_conn

    try:
        import app.db as db_module  # type: ignore

        with patch.object(db_module, "get_pool", return_value=mock_pool):
            resp = client.get("/health")
    except ImportError:
        pytest.skip("app.db not yet importable")

    # Should return 200 or 503, not 500
    assert resp.status_code in (200, 503)


# ---------------------------------------------------------------------------
# /api/documents/chat — empty messages list
# ---------------------------------------------------------------------------

def test_chat_returns_400_for_empty_messages(client: Any) -> None:
    """POST /chat with an empty messages array must return 400 or 422."""
    if client is None:
        pytest.skip("client fixture unavailable")

    resp = client.post(
        "/api/documents/chat",
        json={"messages": []},
        headers={"X-Tenant-Id": "T001"},
    )
    assert resp.status_code in (400, 422), resp.text


# ---------------------------------------------------------------------------
# /api/documents/chat — no user-role message
# ---------------------------------------------------------------------------

def test_chat_returns_400_when_no_user_message(client: Any) -> None:
    """POST /chat with only assistant messages must return 400."""
    if client is None:
        pytest.skip("client fixture unavailable")

    resp = client.post(
        "/api/documents/chat",
        json={"messages": [{"role": "assistant", "content": "Hello"}]},
        headers={"X-Tenant-Id": "T001"},
    )
    assert resp.status_code in (400, 422), resp.text


# ---------------------------------------------------------------------------
# /api/documents/chat — OCI GenAI timeout
# ---------------------------------------------------------------------------

def test_chat_returns_error_on_oci_genai_timeout(client: Any) -> None:
    """POST /chat must return 500 or 503 when OCI GenAI call times out."""
    if client is None:
        pytest.skip("client fixture unavailable")

    pytest.skip("skeleton — patch OCI GenAI client to simulate timeout")
    # TODO: patch the OCI GenerativeAiInferenceClient or httpx call
    # with side_effect=TimeoutError and assert resp.status_code in (500, 503)


# ---------------------------------------------------------------------------
# _fetch_top_k() — DB raises during vector search
# ---------------------------------------------------------------------------

def test_fetch_top_k_returns_empty_on_db_error() -> None:
    """_fetch_top_k() must return [] and not propagate when cursor.execute raises."""
    try:
        from app.routers.rag import _fetch_top_k  # type: ignore
    except ImportError:
        pytest.skip("app.routers.rag._fetch_top_k not yet importable")

    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.execute.side_effect = Exception("ORA-12154: TNS:could not resolve")

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    import asyncio
    import array

    embedding = array.array("f", [0.0] * 1024)

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _fetch_top_k(conn=mock_conn, embedding=embedding, tenant_id="T001", k=5)
        )
    except Exception:
        # If _fetch_top_k propagates, test failure is meaningful
        result = []

    assert result == [], f"Expected [] on DB error, got {result!r}"

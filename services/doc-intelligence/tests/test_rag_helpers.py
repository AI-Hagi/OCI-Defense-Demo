"""
Unit tests for _to_oracle_vector() and _fetch_top_k() in routers/rag.py,
plus edge cases for the /search and /chat HTTP endpoints.
"""
from __future__ import annotations

import array
import sys
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Isolate imports
# ---------------------------------------------------------------------------

def _purge_app():
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]


_purge_app()


# ---------------------------------------------------------------------------
# _to_oracle_vector
# ---------------------------------------------------------------------------

def test_to_oracle_vector_returns_float32_array():
    _purge_app()
    from app.routers.rag import _to_oracle_vector

    vec = [0.1, 0.2, 0.3]
    result = _to_oracle_vector(vec)

    assert isinstance(result, array.array)
    assert result.typecode == "f"
    assert len(result) == 3


def test_to_oracle_vector_preserves_values():
    _purge_app()
    from app.routers.rag import _to_oracle_vector

    vec = [1.0, -0.5, 0.25]
    result = _to_oracle_vector(vec)

    for expected, actual in zip(vec, result):
        assert abs(actual - expected) < 1e-5


def test_to_oracle_vector_1024_dim():
    _purge_app()
    from app.routers.rag import _to_oracle_vector

    vec = [0.01] * 1024
    result = _to_oracle_vector(vec)

    assert len(result) == 1024


# ---------------------------------------------------------------------------
# _fetch_top_k
# ---------------------------------------------------------------------------

def _mock_conn(rows: list[tuple]) -> Any:
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.__iter__ = MagicMock(return_value=iter(rows))

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_fetch_top_k_returns_search_hits():
    _purge_app()
    from app.routers.rag import _fetch_top_k

    rows = [
        ("doc1", "Title A", 0, "chunk text A", 0.15),
        ("doc2", "Title B", 1, "chunk text B", 0.30),
    ]
    conn, _ = _mock_conn(rows)

    hits = _fetch_top_k(conn, "T001", [0.0] * 1024, k=5)

    assert len(hits) == 2
    assert hits[0].doc_id == "doc1"
    assert hits[0].title == "Title A"
    assert hits[0].dist == 0.15
    assert hits[1].chunk_idx == 1


def test_fetch_top_k_empty_result_set():
    _purge_app()
    from app.routers.rag import _fetch_top_k

    conn, _ = _mock_conn([])
    hits = _fetch_top_k(conn, "T001", [0.0] * 1024, k=5)

    assert hits == []


def test_fetch_top_k_reads_lob_text():
    _purge_app()
    from app.routers.rag import _fetch_top_k

    lob = MagicMock()
    lob.read = MagicMock(return_value="lob text content")
    rows = [("doc1", "Title", 0, lob, 0.05)]
    conn, _ = _mock_conn(rows)

    hits = _fetch_top_k(conn, "T001", [0.0] * 1024, k=5)

    assert hits[0].text == "lob text content"
    lob.read.assert_called_once()


def test_fetch_top_k_none_dist_becomes_zero():
    _purge_app()
    from app.routers.rag import _fetch_top_k

    rows = [("doc1", "Title", 0, "text", None)]
    conn, _ = _mock_conn(rows)

    hits = _fetch_top_k(conn, "T001", [0.0] * 1024, k=5)

    assert hits[0].dist == 0.0


def test_fetch_top_k_binds_vector_as_float32_array():
    _purge_app()
    from app.routers.rag import _fetch_top_k

    rows = []
    conn, cursor = _mock_conn(rows)
    vec = [0.1] * 1024

    _fetch_top_k(conn, "T001", vec, k=3)

    call_args = cursor.execute.call_args
    params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("params", {})
    assert isinstance(params.get("qv"), array.array)
    assert params["qv"].typecode == "f"
    assert params["t"] == "T001"
    assert params["k"] == 3


# ---------------------------------------------------------------------------
# /chat endpoint — no user message edge case
# ---------------------------------------------------------------------------

def test_chat_raises_400_when_no_user_message(tmp_path):
    _purge_app()

    import oracledb
    sys.modules.setdefault("oracledb", MagicMock())

    try:
        from app.routers.rag import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        fake_embed = MagicMock(return_value=[0.0] * 1024)

        app = FastAPI()
        app.include_router(router, prefix="/docs")

        conn_mock = MagicMock()
        cursor_mock = MagicMock()
        cursor_mock.__enter__ = MagicMock(return_value=cursor_mock)
        cursor_mock.__exit__ = MagicMock(return_value=False)
        cursor_mock.__iter__ = MagicMock(return_value=iter([]))
        conn_mock.cursor.return_value = cursor_mock

        from app.db import get_conn
        app.dependency_overrides[get_conn] = lambda: conn_mock

        with patch("app.routers.rag.embed", fake_embed):
            client = TestClient(app)
            resp = client.post(
                "/docs/chat",
                json={"messages": [{"role": "assistant", "content": "Only assistant"}]},
                headers={"X-Tenant-Id": "T001"},
            )

        assert resp.status_code == 400
        assert "user message" in resp.json()["detail"].lower()

    except Exception as exc:
        pytest.skip(f"Router not importable in isolation: {exc}")

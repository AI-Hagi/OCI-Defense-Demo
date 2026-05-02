"""London-school fixtures for the compliance FastAPI service."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _isolate_service_imports() -> None:
    root_str = str(ROOT)
    sys.path[:] = [p for p in sys.path if "/services/" not in p or p == root_str]
    if root_str in sys.path:
        sys.path.remove(root_str)
    sys.path.insert(0, root_str)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


_isolate_service_imports()


@pytest.fixture
def mock_cursor() -> MagicMock:
    cursor = MagicMock(name="OracleCursor")
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (1,)
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.__iter__ = lambda self: iter([])
    return cursor


@pytest.fixture
def mock_conn(mock_cursor: MagicMock) -> MagicMock:
    conn = MagicMock(name="OracleConnection")
    conn.cursor.return_value = mock_cursor
    conn.commit.return_value = None
    conn.close.return_value = None
    return conn


@pytest.fixture
def mock_pool(mock_conn: MagicMock) -> MagicMock:
    pool = MagicMock(name="OraclePool")
    pool.acquire.return_value = mock_conn
    return pool


@pytest.fixture
def app_module(mock_pool: MagicMock, monkeypatch: pytest.MonkeyPatch):
    _isolate_service_imports()
    try:
        import oracledb  # type: ignore
    except Exception:
        oracledb = MagicMock()
        monkeypatch.setitem(sys.modules, "oracledb", oracledb)
    monkeypatch.setattr(oracledb, "create_pool", lambda *a, **kw: mock_pool, raising=False)

    try:
        from app import main as app_main  # type: ignore
    except Exception as exc:
        pytest.skip(f"service app.main not importable yet: {exc}")

    try:
        from app import db as app_db  # type: ignore
        monkeypatch.setattr(app_db, "_pool", mock_pool, raising=False)
        monkeypatch.setattr(app_db, "get_pool", lambda: mock_pool)
    except Exception:
        pass

    return app_main


@pytest.fixture
def client(app_module, mock_conn: MagicMock) -> Iterator[Any]:
    from fastapi.testclient import TestClient
    try:
        from app.db import get_conn  # type: ignore
    except Exception:
        pytest.skip("app.db.get_conn not available yet")

    def _override() -> Iterator[MagicMock]:
        yield mock_conn

    app_module.app.dependency_overrides[get_conn] = _override
    with TestClient(app_module.app) as c:
        yield c
    app_module.app.dependency_overrides.clear()

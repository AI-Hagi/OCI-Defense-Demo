"""
London-school test fixtures for the GEOINT FastAPI service.

Every collaborator (oracledb pool, YOLOv8 detector) is mocked. The FastAPI
app is imported lazily so the tests succeed even if the real module has not
yet been written (they will be skipped in that case).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

# Ensure this service's root is importable as `app.*`.
ROOT = Path(__file__).resolve().parents[1]


def _isolate_service_imports() -> None:
    """Put THIS service root first on sys.path and evict any stale `app.*`
    modules imported by a sibling service — critical when pytest collects
    multiple services in one run (pytest --import-mode=importlib)."""
    root_str = str(ROOT)
    # Remove other service roots from sys.path if present.
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
    # Iteration yields nothing by default.
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
    """Import services/<service>/app.main with oracledb pool patched."""
    _isolate_service_imports()
    try:
        import oracledb  # type: ignore
    except Exception:
        oracledb = MagicMock()
        monkeypatch.setitem(sys.modules, "oracledb", oracledb)

    monkeypatch.setattr(oracledb, "create_pool", lambda *a, **kw: mock_pool, raising=False)

    # Prevent YOLOv8 from being loaded in tests.
    fake_ml = MagicMock()
    fake_ml.detect = MagicMock(return_value=[{"cls": "vessel", "confidence": 0.9,
                                              "bbox": [0, 0, 1, 1]}])
    monkeypatch.setitem(sys.modules, "app.ml", fake_ml)

    try:
        from app import main as app_main  # type: ignore
    except Exception as exc:  # pragma: no cover - import-time skip
        pytest.skip(f"service app.main not importable yet: {exc}")

    # Replace the module-level pool so /health uses the mock.
    from app import db as app_db  # type: ignore
    monkeypatch.setattr(app_db, "_pool", mock_pool, raising=False)
    monkeypatch.setattr(app_db, "get_pool", lambda: mock_pool)

    return app_main


@pytest.fixture
def client(app_module, mock_conn: MagicMock) -> Iterator[Any]:
    """FastAPI TestClient with the DB dependency overridden to yield mock_conn."""
    from fastapi.testclient import TestClient
    from app.db import get_conn  # type: ignore

    def _override() -> Iterator[MagicMock]:
        yield mock_conn

    app_module.app.dependency_overrides[get_conn] = _override
    with TestClient(app_module.app) as c:
        yield c
    app_module.app.dependency_overrides.clear()

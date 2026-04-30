"""Offline test fixtures for tle-proxy."""
from __future__ import annotations

import os
import sys
import types
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

os.environ.setdefault("ORACLE_USER", "test_user")
os.environ.setdefault("ORACLE_PASSWORD", "test_password")
os.environ.setdefault("WALLET_PASSWORD", "test_wallet")
os.environ.setdefault("ORACLE_CONNECT_STRING", "test_tns")
os.environ.setdefault("X_TENANT_DEFAULT", "T001")


@pytest.fixture
def mock_db(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = MagicMock(name="MockDbState")
    state.audit_rows = []
    state.cache_rows = []
    # Tests pre-populate this dict (layer → (payload_json_str, fetched_at, source))
    # to make CacheRepo.read_latest() return canned data.
    state.cache_latest: dict[str, Any] = {}

    if "oracledb" not in sys.modules:
        oracledb_stub = types.ModuleType("oracledb")
        oracledb_stub.create_pool = lambda *a, **kw: MagicMock(name="OraclePool")
        oracledb_stub.connect = lambda *a, **kw: MagicMock(name="OracleConnection")
        oracledb_stub.DatabaseError = Exception
        oracledb_stub.init_oracle_client = lambda *a, **kw: None
        monkeypatch.setitem(sys.modules, "oracledb", oracledb_stub)

    cursor = MagicMock(name="OracleCursor")
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.__iter__ = lambda self: iter([])

    def _execute(sql: str, params: Any = None) -> None:
        sql_upper = sql.upper().strip() if isinstance(sql, str) else ""
        if "AUDIT_EVENTS" in sql_upper and "INSERT" in sql_upper:
            state.audit_rows.append(dict(params) if isinstance(params, dict) else {"raw": params})
        elif "OSINT_CACHE" in sql_upper and "INSERT" in sql_upper:
            state.cache_rows.append(dict(params) if isinstance(params, dict) else {"raw": params})
        elif "OSINT_CACHE" in sql_upper and "SELECT" in sql_upper:
            layer = (params or {}).get("layer") if isinstance(params, dict) else None
            row = state.cache_latest.get(layer)
            cursor.fetchone.return_value = row  # (payload, fetched_at, source) or None

    cursor.execute.side_effect = _execute

    conn = MagicMock(name="OracleConnection")
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    pool = MagicMock(name="OraclePool")
    pool.acquire.return_value = conn

    import oracledb  # type: ignore
    monkeypatch.setattr(oracledb, "create_pool", lambda *a, **kw: pool, raising=False)
    monkeypatch.setattr(oracledb, "connect", lambda *a, **kw: conn, raising=False)

    try:
        from app import db as app_db  # type: ignore
        for attr in ("_pool", "POOL", "pool", "_default_pool"):
            if hasattr(app_db, attr):
                monkeypatch.setattr(app_db, attr, None, raising=False)
    except Exception:
        pass

    state._pool = pool
    state._conn = conn
    state._cursor = cursor
    return state


@pytest.fixture
def app_module(mock_db: Any, monkeypatch: pytest.MonkeyPatch):
    _isolate_service_imports()
    try:
        from app import main as app_main  # type: ignore
    except Exception as exc:
        pytest.skip(f"service app.main not importable: {exc}")
    return app_main


@pytest.fixture
def client(app_module) -> Iterator[Any]:
    from fastapi.testclient import TestClient
    with TestClient(app_module.app) as c:
        yield c
    try:
        app_module.app.dependency_overrides.clear()
    except Exception:
        pass

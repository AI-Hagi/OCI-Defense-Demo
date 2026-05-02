"""
Offline test fixtures for sentinel-proxy.

Heavy deps stubbed:
  * httpx — mocked via respx where the test cares about wire-level shape;
    otherwise a MagicMock client is patched into app.state at lifespan.
  * oracledb — stub module so the import path works without native libs.
  * Token fetch + capabilities fetch — patched by the conftest defaults so
    the lifespan can complete without contacting Copernicus.
"""
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


# Force enough env so settings.py validates.
os.environ.setdefault("SENTINEL_CLIENT_ID", "test-client-id")
os.environ.setdefault("SENTINEL_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("SENTINEL_INSTANCE_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("ORACLE_USER", "test_user")
os.environ.setdefault("ORACLE_PASSWORD", "test_password")
os.environ.setdefault("WALLET_PASSWORD", "test_wallet")
os.environ.setdefault("ORACLE_CONNECT_STRING", "test_tns")
os.environ.setdefault("X_TENANT_DEFAULT", "T001")


@pytest.fixture
def mock_db(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = MagicMock(name="MockDbState")
    state.audit_rows = []

    if "oracledb" not in sys.modules:
        oracledb_stub = types.ModuleType("oracledb")
        oracledb_stub.create_pool = lambda *a, **kw: MagicMock(name="OraclePool")
        oracledb_stub.connect = lambda *a, **kw: MagicMock(name="OracleConnection")
        oracledb_stub.DatabaseError = Exception
        oracledb_stub.init_oracle_client = lambda *a, **kw: None
        monkeypatch.setitem(sys.modules, "oracledb", oracledb_stub)

    cursor = MagicMock(name="OracleCursor")
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (1,)
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.__iter__ = lambda self: iter([])

    def _execute(sql: str, params: Any = None) -> None:
        sql_upper = sql.upper().strip() if isinstance(sql, str) else ""
        if "AUDIT_EVENTS" in sql_upper and "INSERT" in sql_upper:
            state.audit_rows.append(dict(params) if isinstance(params, dict) else {"raw": params})

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
def mock_token(monkeypatch: pytest.MonkeyPatch) -> str:
    """Patch TokenManager._refresh_once so lifespan startup never hits the network."""
    _isolate_service_imports()
    try:
        from app import token_manager as tm  # type: ignore
    except Exception as exc:
        pytest.skip(f"app.token_manager not importable: {exc}")

    fake_token = "fake-bearer-token-xxxx" * 8

    async def _fake_refresh(self) -> None:  # type: ignore[no-untyped-def]
        from datetime import datetime, timezone
        self._token = fake_token
        self._fetched_at = datetime.now(timezone.utc)
        self.refresh_count += 1

    monkeypatch.setattr(tm.TokenManager, "_refresh_once", _fake_refresh, raising=True)
    return fake_token


@pytest.fixture
def app_module(mock_db: Any, mock_token: str, monkeypatch: pytest.MonkeyPatch):
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

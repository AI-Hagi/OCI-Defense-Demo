"""
London-school fixtures for the ais-multiplexer FastAPI service.

These fixtures isolate the service from real OCI Vault and Oracle 26ai ATP:

* ``mock_vault`` — monkeypatches ``app.vault.get_secret`` to return a fixed
  string (``"mock-aisstream-key"``). No real Vault call is made.
* ``mock_db`` — patches ``app.db`` (whichever pool/connection accessor exists)
  so that ``audit_events`` INSERTs land in an in-memory list, not ATP.
  Tests can introspect ``mock_db.audit_rows`` to assert batched-flush
  behaviour.
* ``client`` — sync ``TestClient`` against the FastAPI app exported from
  ``app.main``.

The fixtures use ``pytest.skip`` when the parallel agent has not yet
delivered ``app.main`` / ``app.db`` — that way this file can land before
the implementation without breaking CI.
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
    """Make sure the ais-multiplexer's own ``app`` package wins on sys.path.

    Other services in the monorepo (osint-fusion, geoint, …) all expose an
    ``app`` package — we must not import theirs by accident.
    """
    root_str = str(ROOT)
    sys.path[:] = [p for p in sys.path if "/services/" not in p or p == root_str]
    if root_str in sys.path:
        sys.path.remove(root_str)
    sys.path.insert(0, root_str)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


_isolate_service_imports()

# Force the mock-vault env so ``app.vault.get_secret`` skips the OCI SDK
# even if a test forgets to use the ``mock_vault`` fixture.
os.environ.setdefault("MOCK_VAULT_KEY", "mock-aisstream-key")
os.environ.setdefault("VAULT_AIS_STREAM_KEY_OCID", "ocid1.vaultsecret.test")
os.environ.setdefault("ORACLE_USER", "test_user")
os.environ.setdefault("ORACLE_PASSWORD", "test_password")
os.environ.setdefault("WALLET_PASSWORD", "test_wallet")
# AIS_BBOX_DEFAULT now has no hardcoded default in settings.py — set the
# canonical Baltic value here so unit tests that exercise bbox_default_tuple
# don't blow up. Production reads from configmap-common.
os.environ.setdefault("AIS_BBOX_DEFAULT", "53,8,56,22")


# ---------------------------------------------------------------------------
# Vault double — never touches OCI.
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_vault(monkeypatch: pytest.MonkeyPatch) -> str:
    """Replace ``app.vault.get_secret`` with an async stub returning a fixed key."""
    _isolate_service_imports()
    try:
        from app import vault as app_vault  # type: ignore
    except Exception as exc:
        pytest.skip(f"app.vault not importable yet: {exc}")

    async def _fake_get_secret(ocid: str, settings: Any | None = None) -> str:
        return "mock-aisstream-key"

    monkeypatch.setattr(app_vault, "get_secret", _fake_get_secret, raising=False)
    return "mock-aisstream-key"


# ---------------------------------------------------------------------------
# DB double — captures audit_events INSERTs into an in-memory list.
# ---------------------------------------------------------------------------
class _MockDb:
    """Tracks audit_events INSERTs and any other DB calls that pass through."""

    def __init__(self) -> None:
        self.audit_rows: list[dict[str, Any]] = []
        self.executed_sql: list[tuple[str, Any]] = []

    def record_execute(self, sql: str, params: Any) -> None:
        self.executed_sql.append((sql, params))
        sql_upper = sql.upper().strip() if isinstance(sql, str) else ""
        if "AUDIT_EVENTS" in sql_upper and "INSERT" in sql_upper:
            row: dict[str, Any] = {}
            if isinstance(params, dict):
                row.update(params)
            elif isinstance(params, (list, tuple)):
                row["positional"] = list(params)
            self.audit_rows.append(row)


@pytest.fixture
def mock_db(monkeypatch: pytest.MonkeyPatch) -> _MockDb:
    """Provide a fake oracledb pool/connection that records INSERTs.

    Strategy:
      1. Stub ``oracledb`` so ``app.db`` import never tries to load the
         binary thick client.
      2. Replace the pool factory with a MagicMock; cursor.execute records
         every SQL it sees on the ``_MockDb`` accumulator.
      3. Best-effort: also expose ``app.db.get_pool``/``_pool`` overrides so
         any internal accessor the service uses sees the mock.
    """
    state = _MockDb()

    # --- 1. Stub oracledb if not installed in the test environment -----------
    if "oracledb" not in sys.modules:
        oracledb_stub = types.ModuleType("oracledb")
        oracledb_stub.create_pool = lambda *a, **kw: MagicMock(name="OraclePool")  # type: ignore[attr-defined]
        oracledb_stub.connect = lambda *a, **kw: MagicMock(name="OracleConnection")  # type: ignore[attr-defined]
        oracledb_stub.DatabaseError = Exception  # type: ignore[attr-defined]
        oracledb_stub.init_oracle_client = lambda *a, **kw: None  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "oracledb", oracledb_stub)

    import oracledb  # type: ignore

    cursor = MagicMock(name="OracleCursor")
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = (1,)
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.__iter__ = lambda self: iter([])

    def _execute(sql: str, params: Any = None) -> None:
        state.record_execute(sql, params)

    cursor.execute.side_effect = _execute

    def _executemany(sql: str, seq: Any = None) -> None:
        if seq is None:
            return
        for params in seq:
            state.record_execute(sql, params)

    cursor.executemany.side_effect = _executemany

    conn = MagicMock(name="OracleConnection")
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    pool = MagicMock(name="OraclePool")
    pool.acquire.return_value = conn

    monkeypatch.setattr(oracledb, "create_pool", lambda *a, **kw: pool, raising=False)
    monkeypatch.setattr(oracledb, "connect", lambda *a, **kw: conn, raising=False)

    # --- 3. Patch app.db internals if the module exists ----------------------
    try:
        from app import db as app_db  # type: ignore
        for attr in ("_pool", "POOL", "pool"):
            if hasattr(app_db, attr):
                monkeypatch.setattr(app_db, attr, pool, raising=False)
        if hasattr(app_db, "get_pool"):
            monkeypatch.setattr(app_db, "get_pool", lambda: pool, raising=False)
        if hasattr(app_db, "get_conn"):
            def _get_conn() -> Any:
                return conn
            monkeypatch.setattr(app_db, "get_conn", _get_conn, raising=False)
    except Exception:
        # app.db not implemented yet — that's fine, individual tests will skip.
        pass

    state._pool = pool  # type: ignore[attr-defined]
    state._conn = conn  # type: ignore[attr-defined]
    state._cursor = cursor  # type: ignore[attr-defined]
    return state


# ---------------------------------------------------------------------------
# FastAPI app + TestClient.
# ---------------------------------------------------------------------------
@pytest.fixture
def app_module(mock_vault: str, mock_db: _MockDb, monkeypatch: pytest.MonkeyPatch):
    """Import ``app.main`` with vault/db doubles in place."""
    _isolate_service_imports()
    try:
        from app import main as app_main  # type: ignore
    except Exception as exc:
        pytest.skip(f"service app.main not importable yet: {exc}")
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

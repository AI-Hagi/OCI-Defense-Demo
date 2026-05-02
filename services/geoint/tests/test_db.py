"""
Tests for geoint/app/db.py — tenant_from_header() normalisation,
set_tenant_identifier() DB propagation, and get_conn() pool interaction.

Coverage gaps filled:
  - tenant_from_header(None)            → "T001"
  - tenant_from_header("")              → "T001"
  - tenant_from_header("   ")           → "T001"  (whitespace-only)
  - tenant_from_header(" T002 ")        → "T002"  (trimmed)
  - tenant_from_header("T003")          → "T003"  (unchanged)
  - set_tenant_identifier() executes correct PL/SQL with tenant_id
  - set_tenant_identifier() propagates exception from cursor.execute
  - get_conn() acquires from pool and yields the connection
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# tenant_from_header
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("header,expected", [
    (None,     "T001"),
    ("",       "T001"),
    ("   ",    "T001"),
    ("T002",   "T002"),
    (" T002 ", "T002"),
    ("T003",   "T003"),
])
def test_tenant_from_header(header, expected):
    from app.db import tenant_from_header
    assert tenant_from_header(header) == expected


# ---------------------------------------------------------------------------
# set_tenant_identifier
# ---------------------------------------------------------------------------

def _mock_conn():
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_set_tenant_identifier_executes_dbms_session():
    """set_tenant_identifier must call DBMS_SESSION.SET_IDENTIFIER with tenant_id."""
    from app.db import set_tenant_identifier

    conn, cursor = _mock_conn()
    set_tenant_identifier(conn, "T001")

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert "DBMS_SESSION" in sql
    assert "SET_IDENTIFIER" in sql
    assert params == ["T001"]


def test_set_tenant_identifier_passes_tenant_id_correctly():
    """set_tenant_identifier binds the exact tenant_id supplied."""
    from app.db import set_tenant_identifier

    conn, cursor = _mock_conn()
    set_tenant_identifier(conn, "TENANT_GOV_PRIMARY")

    _, params = cursor.execute.call_args.args
    assert "TENANT_GOV_PRIMARY" in params


def test_set_tenant_identifier_propagates_db_error():
    """set_tenant_identifier must not swallow exceptions from cursor.execute."""
    from app.db import set_tenant_identifier

    conn, cursor = _mock_conn()
    cursor.execute.side_effect = RuntimeError("ORA-00942: table or view does not exist")

    with pytest.raises(RuntimeError, match="ORA-00942"):
        set_tenant_identifier(conn, "T001")


# ---------------------------------------------------------------------------
# get_conn — pool acquire and release
# ---------------------------------------------------------------------------

def test_get_conn_yields_acquired_connection():
    """get_conn() must yield the connection returned by pool.acquire()."""
    import importlib
    import app.db as db_mod

    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.acquire.return_value = fake_conn

    with patch.object(db_mod, "get_pool", return_value=fake_pool):
        gen = db_mod.get_conn()
        yielded = next(gen)

    assert yielded is fake_conn


def test_get_conn_closes_connection_after_yield():
    """get_conn() must close the pooled connection in the finally block."""
    import app.db as db_mod

    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.acquire.return_value = fake_conn

    with patch.object(db_mod, "get_pool", return_value=fake_pool):
        gen = db_mod.get_conn()
        next(gen)
        try:
            next(gen)
        except StopIteration:
            pass

    fake_conn.close.assert_called_once()

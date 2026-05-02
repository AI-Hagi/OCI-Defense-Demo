"""
Unit tests for app.ols — header parsing, clamp behaviour, SQL helpers.

Mock-first: no real DB connection. The session-context helpers
(apply_session_label_cap / clear_session_label_cap) are exercised against
a MagicMock cursor so we can assert the BEGIN-block bind values.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ols import (
    LabelCap,
    apply_session_label_cap,
    clear_session_label_cap,
    label_cap_dependency,
    label_filter_clause,
    parse_label_cap,
)


# ---------------------------------------------------------------------------
# parse_label_cap — happy-path values pass through unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("10", LabelCap.OFFEN),
    ("30", LabelCap.INTERN),
    ("50", LabelCap.NFD),
    (10,   LabelCap.OFFEN),
    (30,   LabelCap.INTERN),
    (50,   LabelCap.NFD),
])
def test_parse_label_cap_valid_values_pass_through(value, expected):
    assert parse_label_cap(value) == expected


# ---------------------------------------------------------------------------
# parse_label_cap — GEHEIM(70) is silently clamped to NFD(50)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["70", 70])
def test_parse_label_cap_geheim_clamps_to_nfd(value):
    """Operators with GEHEIM clearance shouldn't hit a 400 — clamp instead."""
    assert parse_label_cap(value) == LabelCap.NFD


# ---------------------------------------------------------------------------
# parse_label_cap — fail-safe to OFFEN for missing / malformed / out-of-range
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    None,           # header absent
    "",             # header empty
    "   ",          # whitespace only
    "abc",          # non-numeric
    "10.5",         # decimal not allowed
    "-1",           # negative
    "0",            # below the allowed set
    "20",           # in-range but not in allowed set
    "100",          # above hard cap and not in allowed set
    "999",          # garbage
    -1,             # int negative
    20,             # int in-range but not allowed
    object(),       # wrong type
])
def test_parse_label_cap_failsafe_to_offen(value):
    """Anything not in {10,30,50,70} → OFFEN(10). Never raise."""
    assert parse_label_cap(value) == LabelCap.OFFEN


# ---------------------------------------------------------------------------
# parse_label_cap — must NOT raise on weird inputs (defence-in-depth)
# ---------------------------------------------------------------------------

def test_parse_label_cap_never_raises_on_unexpected_types():
    # Even on a wildly unexpected type, we get the failsafe — no exception
    # propagates to a request handler.
    assert parse_label_cap([1, 2, 3]) == LabelCap.OFFEN
    assert parse_label_cap({"foo": "bar"}) == LabelCap.OFFEN


# ---------------------------------------------------------------------------
# label_cap_dependency — FastAPI dependency wrapper just delegates
# ---------------------------------------------------------------------------

def test_label_cap_dependency_passes_header_through():
    assert label_cap_dependency("50") == LabelCap.NFD
    assert label_cap_dependency(None) == LabelCap.OFFEN
    assert label_cap_dependency("70") == LabelCap.NFD  # clamped


# ---------------------------------------------------------------------------
# apply_session_label_cap — calls the DB package with the integer cap
# ---------------------------------------------------------------------------

def test_apply_session_label_cap_invokes_set_procedure():
    cur = MagicMock(name="OracleCursor")
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock(name="OracleConnection")
    conn.cursor.return_value = cur

    apply_session_label_cap(conn, LabelCap.NFD)

    # SET_LABEL_CAP gets called with the integer cap as a positional bind
    cur.execute.assert_called_once()
    sql, binds = cur.execute.call_args.args
    assert "OLS_CTX_PKG.SET_LABEL_CAP" in sql.upper()
    assert binds == [50]


def test_apply_session_label_cap_coerces_int_subclass():
    """LabelCap is an IntEnum — make sure we don't accidentally pass a
    fancy enum object that the oracledb driver might mishandle. The
    helper coerces to plain int."""
    cur = MagicMock(name="OracleCursor")
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock(name="OracleConnection")
    conn.cursor.return_value = cur

    apply_session_label_cap(conn, LabelCap.INTERN)

    _, binds = cur.execute.call_args.args
    assert binds == [30]
    assert type(binds[0]) is int   # not a LabelCap subclass


# ---------------------------------------------------------------------------
# clear_session_label_cap — calls the CLEAR_LABEL_CAP procedure
# ---------------------------------------------------------------------------

def test_clear_session_label_cap_invokes_clear_procedure():
    cur = MagicMock(name="OracleCursor")
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock(name="OracleConnection")
    conn.cursor.return_value = cur

    clear_session_label_cap(conn)

    cur.execute.assert_called_once()
    sql, *_ = cur.execute.call_args.args
    assert "OLS_CTX_PKG.CLEAR_LABEL_CAP" in sql.upper()


# ---------------------------------------------------------------------------
# label_filter_clause — produces SQL fragments suitable for WHERE-injection
# ---------------------------------------------------------------------------

def test_label_filter_clause_no_alias():
    assert label_filter_clause() == " AND ols_label <= UC4_OSINT.label_cap()"


def test_label_filter_clause_with_alias():
    assert (
        label_filter_clause("sn")
        == " AND sn.ols_label <= UC4_OSINT.label_cap()"
    )


def test_label_filter_clause_strips_alias_whitespace():
    assert (
        label_filter_clause("  s  ")
        == " AND s.ols_label <= UC4_OSINT.label_cap()"
    )


def test_label_filter_clause_starts_with_space_for_concat():
    """The clause is intended to concatenate onto an existing WHERE
    expression, so it must start with a leading space."""
    assert label_filter_clause().startswith(" AND ")

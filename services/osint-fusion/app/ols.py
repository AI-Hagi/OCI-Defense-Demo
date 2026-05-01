"""
UC4_OSINT App-Level OLS Filter Helper
======================================

Why this module exists
----------------------
Native Oracle Label Security administration is gated on ATP-Shared (ORA-42911
when calling SA_SYSDBA.CREATE_POLICY — the LBAC engine runs but customer-side
admin is disabled by the cloud control plane). Until that's unblocked
(Oracle SR or migration to ATP-Dedicated), UC4 enforces classification at the
application layer:

  * `ols_label NUMBER(10) NOT NULL` is on every UC4_OSINT row (set by ingest)
  * Every read query carries  ``WHERE ols_label <= UC4_OSINT.label_cap()``
  * The `label_cap()` SQL function reads from a session-scoped Oracle
    application context, written by this module on Connection-Acquire

The defence-in-depth gap (a DBA who issues raw SQL without the WHERE clause
can bypass) is documented in
``docs/audits/uc4-ols-app-level-filter-2026-05-01.md``. Once native OLS is
unblocked, both filters run in parallel — they reinforce, not conflict.

Header contract
---------------
``X-OLS-Label-Max`` is the operator-asserted clearance ceiling for the
request. Allowed values: ``10`` (OFFEN), ``30`` (INTERN), ``50`` (NFD),
``70`` (GEHEIM). GEHEIM is clamped to NFD silently because the demo
tenancy is capped at NFD per the project rule. Values outside the set
fail-safe to OFFEN — a deliberately defensive choice: empty result sets
are preferable to leaks if the client ever sends a malformed value.

Missing header → OFFEN. The default is *intentionally* low — operators
must opt up explicitly.
"""
from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any

from fastapi import Header

logger = logging.getLogger(__name__)


class LabelCap(IntEnum):
    """Numeric clearance levels matching the OLS_DEFENCE policy levels."""

    OFFEN = 10
    INTERN = 30
    NFD = 50
    GEHEIM = 70


# Header values we accept on the wire (GEHEIM gets clamped, but it's
# semantically valid input — operators with GEHEIM clearance shouldn't
# hit a 400 just because the demo tenancy caps lower).
_VALID_HEADER_VALUES: frozenset[int] = frozenset(
    {LabelCap.OFFEN, LabelCap.INTERN, LabelCap.NFD, LabelCap.GEHEIM}
)

# Demo-tenancy hard cap. Applied after the validity check so we silently
# clamp GEHEIM rather than reject it.
_DEMO_HARD_CAP: int = LabelCap.NFD

# Failsafe value when input is missing / malformed / unrecognised.
# Public-tier OFFEN — guarantees the user sees only the lowest classification.
_FAILSAFE: int = LabelCap.OFFEN


def parse_label_cap(value: Any) -> int:
    """Parse an X-OLS-Label-Max header into a numeric cap.

    Accepts ``str``, ``int``, or ``None``. Returns one of {10, 30, 50}.
    GEHEIM (70) clamps to NFD (50). Anything else → OFFEN (10).
    Never raises — the contract is fail-safe-low, never user-error.
    """
    if value is None:
        return _FAILSAFE
    # Header values arrive as strings from FastAPI; tolerate either.
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return _FAILSAFE
        try:
            n = int(stripped)
        except ValueError:
            logger.warning(
                "X-OLS-Label-Max not numeric (%r) — failing safe to OFFEN", value,
            )
            return _FAILSAFE
    elif isinstance(value, int):
        n = value
    else:
        logger.warning(
            "X-OLS-Label-Max unexpected type %s — failing safe to OFFEN", type(value),
        )
        return _FAILSAFE

    if n not in _VALID_HEADER_VALUES:
        logger.warning(
            "X-OLS-Label-Max=%r outside allowed set %s — failing safe to OFFEN",
            n, sorted(_VALID_HEADER_VALUES),
        )
        return _FAILSAFE

    if n > _DEMO_HARD_CAP:
        logger.info(
            "X-OLS-Label-Max=%d (GEHEIM) clamped to NFD(%d) per demo-tenancy rule",
            n, _DEMO_HARD_CAP,
        )
        return _DEMO_HARD_CAP

    return n


def label_cap_dependency(
    x_ols_label_max: str | None = Header(default=None, alias="X-OLS-Label-Max"),
) -> int:
    """FastAPI dependency: parse the header into a numeric cap.

    Routers add ``cap: int = Depends(label_cap_dependency)`` and pass the
    cap on to ``apply_session_label_cap`` once they have a connection.
    """
    return parse_label_cap(x_ols_label_max)


def apply_session_label_cap(conn: Any, cap: int) -> None:
    """Push the cap into the DB session's application context.

    Subsequent SQL on the same connection sees the value via
    ``UC4_OSINT.label_cap()``. The DB-side procedure re-validates and
    re-clamps, so a malicious caller passing 70 directly to this helper
    still ends up with 50 in the context.
    """
    with conn.cursor() as cur:
        cur.execute(
            "BEGIN UC4_OSINT.OLS_CTX_PKG.SET_LABEL_CAP(:1); END;", [int(cap)],
        )


def clear_session_label_cap(conn: Any) -> None:
    """Drop the context attribute. Use on connection release in a pool
    to ensure no cap leaks to the next acquirer.
    """
    with conn.cursor() as cur:
        cur.execute("BEGIN UC4_OSINT.OLS_CTX_PKG.CLEAR_LABEL_CAP; END;")


def label_filter_clause(table_alias: str = "") -> str:
    """Return the ``AND ols_label <= UC4_OSINT.label_cap()`` SQL fragment.

    Pass ``table_alias`` when joining multiple labelled tables and you
    need to disambiguate. Returned string starts with a leading space so
    it concatenates cleanly onto an existing WHERE expression.
    """
    prefix = f"{table_alias.strip()}." if table_alias else ""
    return f" AND {prefix}ols_label <= UC4_OSINT.label_cap()"


__all__ = [
    "LabelCap",
    "parse_label_cap",
    "label_cap_dependency",
    "apply_session_label_cap",
    "clear_session_label_cap",
    "label_filter_clause",
]

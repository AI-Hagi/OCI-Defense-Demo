"""
UC4 briefings/correlations browse endpoints.

The persist_briefing ORDS tool can write briefings (gated by OAuth + OLS),
but the UI also needs to *list* recent correlation_events (so the operator
can pick a correlation_id to draft a briefing from) and *list* persisted
briefings (so the chat-style log can show what's already been written).

These endpoints are read-only browse views over UC4_OSINT.correlation_event
and UC4_OSINT.briefing, served via the osint-fusion FastAPI service so the
browser doesn't need an ORDS bearer to fetch them. Writes still go through
the OAuth-gated /api/uc4/tools/persist_briefing proxy.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
import oracledb

from ..db import get_conn

logger = logging.getLogger(__name__)

router = APIRouter(tags=["uc4-briefings"])


def _read_clob(value: Any) -> Any:
    if value is None:
        return None
    return value.read() if hasattr(value, "read") else value


def _ols_cap_from_header(label: str | None) -> int:
    """Map the X-OLS-Label-Max header value to a numeric cap."""
    return {
        "OFFEN": 10,
        "INTERN": 30,
        "NFD": 50,
        "GEHEIM": 70,
    }.get((label or "NFD").upper(), 50)


@router.get("/correlations")
def list_correlations(
    limit: int = Query(default=20, ge=1, le=100),
    x_ols_label_max: str | None = Header(default=None, alias="X-OLS-Label-Max"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """20 most recent correlation_events visible under the requested OLS cap."""
    cap = _ols_cap_from_header(x_ols_label_max)
    sql = (
        "SELECT RAWTOHEX(correlation_id), correlation_kind, summary, "
        "       detected_at, score, ols_label "
        "FROM UC4_OSINT.correlation_event "
        "WHERE ols_label <= :cap "
        "ORDER BY detected_at DESC "
        "FETCH FIRST :n ROWS ONLY"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"cap": cap, "n": limit})
        rows: list[dict[str, Any]] = []
        for cid, kind, summary, detected, score, label in cur:
            rows.append(
                {
                    "correlation_id": cid,
                    "correlation_kind": kind,
                    "summary": summary,
                    "detected_at": detected.isoformat() if detected else None,
                    "score": float(score) if score is not None else None,
                    "ols_label": int(label) if label is not None else None,
                }
            )
        return rows


@router.get("/briefings")
def list_briefings(
    limit: int = Query(default=20, ge=1, le=100),
    x_ols_label_max: str | None = Header(default=None, alias="X-OLS-Label-Max"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """20 most recent briefings visible under the requested OLS cap."""
    cap = _ols_cap_from_header(x_ols_label_max)
    sql = (
        "SELECT RAWTOHEX(briefing_id), RAWTOHEX(correlation_id), title, body, "
        "       model_id, generated_at, generated_by, review_state, ols_label "
        "FROM UC4_OSINT.briefing "
        "WHERE ols_label <= :cap "
        "ORDER BY generated_at DESC "
        "FETCH FIRST :n ROWS ONLY"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"cap": cap, "n": limit})
        rows: list[dict[str, Any]] = []
        for (
            bid,
            cid,
            title,
            body,
            model_id,
            generated_at,
            generated_by,
            review_state,
            label,
        ) in cur:
            body_text = _read_clob(body) or ""
            rows.append(
                {
                    "briefing_id": bid,
                    "correlation_id": cid,
                    "title": title,
                    "body": body_text,
                    "model_id": model_id,
                    "generated_at": generated_at.isoformat() if generated_at else None,
                    "generated_by": generated_by,
                    "review_state": review_state,
                    "ols_label": int(label) if label is not None else None,
                }
            )
        return rows

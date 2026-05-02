"""
Compliance endpoints: control catalogue, aggregate scoring, DORA open incidents.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Path
import oracledb

from ..db import get_conn, set_tenant_identifier, tenant_from_header

logger = logging.getLogger(__name__)

router = APIRouter(tags=["compliance"])

FRAMEWORKS = ("NIS2", "DORA", "GDPR", "VSNFD")

# Local cache for the live Cloud Guard penalty: avoids hammering the live
# endpoint when the score view is rendered repeatedly. 30s TTL.
_LIVE_TTL_SECONDS = 30
_live_cache_lock = threading.Lock()
_live_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _read_clob(value: Any) -> Any:
    if value is None:
        return None
    return value.read() if hasattr(value, "read") else value


def _live_base_url() -> str:
    return os.environ.get("COMPLIANCE_BASE_URL", "http://localhost:8005")


def _fetch_cloud_guard(tenant_id: str) -> dict[str, Any]:
    """Fetch the live Cloud Guard summary (cached for 30s per tenant)."""
    now = time.monotonic()
    with _live_cache_lock:
        cached = _live_cache.get(tenant_id)
        if cached and (now - cached[0]) < _LIVE_TTL_SECONDS:
            return cached[1]

    url = f"{_live_base_url()}/api/compliance/live/cloud-guard"
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(url, headers={"X-Tenant-Id": tenant_id})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.warning("live cloud-guard fetch failed; assuming 0 open problems",
                       exc_info=True)
        data = {"open_problems": 0, "high_risk": 0}

    with _live_cache_lock:
        _live_cache[tenant_id] = (now, data)
    return data


def _live_penalty_pct(open_problems: int | None) -> int:
    """Map open Cloud Guard problems to a percentage penalty (0..-25)."""
    if open_problems is None or open_problems <= 0:
        return 0
    return -min(25, 5 * int(open_problems))


@router.get("/controls/{framework}")
def list_controls(
    framework: str = Path(..., min_length=2, max_length=10),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    fw_norm = framework.upper().strip()
    if fw_norm not in FRAMEWORKS:
        raise HTTPException(
            status_code=400,
            detail=f"framework must be one of {list(FRAMEWORKS)}",
        )

    sql = (
        "SELECT control_id, code, title, description, tenant_id "
        "FROM compliance_controls "
        "WHERE framework = UPPER(:f) AND tenant_id = :t"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"f": fw_norm, "t": tenant_id})
        return [
            {
                "control_id": cid,
                "code": code,
                "title": title,
                "description": _read_clob(desc),
                "tenant_id": tid,
            }
            for cid, code, title, desc, tid in cur
        ]


@router.get("/score")
def score(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Aggregate compliance score per framework.

    Combines:
      * Total controls (DB) — ``compliance_controls`` per framework for tenant.
      * Implemented findings (DB) — ``compliance_findings`` rows whose
        ``status='IMPLEMENTED'`` per the framework of their parent control.
      * Live penalty — minus 5 percentage points per open Cloud Guard
        problem on the tenant's resources, capped at -25 percent. Pulled
        from ``/live/cloud-guard`` (cached 30s).
    """
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    totals: dict[str, int] = {fw: 0 for fw in FRAMEWORKS}
    implemented: dict[str, int] = {fw: 0 for fw in FRAMEWORKS}

    # Per-framework total controls.
    sql_totals = (
        "SELECT framework, COUNT(*) "
        "  FROM compliance_controls "
        " WHERE tenant_id = :t "
        " GROUP BY framework"
    )
    with conn.cursor() as cur:
        cur.execute(sql_totals, {"t": tenant_id})
        for fw, n in cur:
            if fw in totals:
                totals[fw] = int(n or 0)

    # Per-framework implemented findings (status='IMPLEMENTED').
    # 'mitigated' and 'closed' are the schema's "control satisfied" terminal states
    # (see ck_comp_findings_status in db/schema/02_core_tables.sql).
    sql_impl = (
        "SELECT c.framework, COUNT(*) "
        "  FROM compliance_findings f "
        "  JOIN compliance_controls c ON c.control_id = f.control_id "
        " WHERE f.status IN ('mitigated','closed') AND c.tenant_id = :t "
        " GROUP BY c.framework"
    )
    with conn.cursor() as cur:
        cur.execute(sql_impl, {"t": tenant_id})
        for fw, n in cur:
            if fw in implemented:
                implemented[fw] = int(n or 0)

    # Live Cloud Guard penalty (single source of truth: live endpoint, cached).
    cg = _fetch_cloud_guard(tenant_id)
    open_problems = cg.get("open_problems")
    # Treat the degraded sentinel (-1) as zero penalty.
    if isinstance(open_problems, int) and open_problems < 0:
        open_problems = 0
    penalty = _live_penalty_pct(open_problems)

    result: list[dict[str, Any]] = []
    for fw in FRAMEWORKS:
        total_i = totals[fw]
        impl_i = implemented[fw]
        base_pct = round((impl_i / total_i) * 100, 2) if total_i else 0.0
        score_pct = round(max(0.0, base_pct + penalty), 2)
        result.append(
            {
                "framework": fw,
                "total": total_i,
                "implemented": impl_i,
                "score_pct": score_pct,
                "live_penalty": penalty,
            }
        )
    return result


@router.get("/dora/open")
def dora_open(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    sql = (
        "SELECT incident_id, reported_at, severity, affected_service, "
        "       rto_minutes, rpo_minutes "
        "FROM dora_incidents "
        "WHERE tenant_id = :t AND rto_minutes IS NULL "
        "ORDER BY reported_at DESC"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id})
        return [
            {
                "incident_id": iid,
                "reported_at": reported_at.isoformat() if reported_at else None,
                "severity": severity,
                "affected_service": service,
                "rto_minutes": int(rto) if rto is not None else None,
                "rpo_minutes": int(rpo) if rpo is not None else None,
            }
            for iid, reported_at, severity, service, rto, rpo in cur
        ]


@router.get("/collab-shares")
def list_collab_shares(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    sql = (
        "SELECT share_id, owner_tenant, partner_tenant, artefact_type, "
        "       artefact_id, granted_at, expires_at, ols_label "
        "FROM collab_shares "
        "WHERE owner_tenant = :t OR partner_tenant = :t "
        "ORDER BY granted_at DESC "
        "FETCH FIRST 200 ROWS ONLY"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id})
        return [
            {
                "share_id": sid,
                "owner_tenant": owner,
                "partner_tenant": partner,
                "artefact_type": atype,
                "artefact_id": aid,
                "granted_at": granted.isoformat() if granted else None,
                "expires_at": expires.isoformat() if expires else None,
                "ols_label": int(label) if label is not None else None,
            }
            for sid, owner, partner, atype, aid, granted, expires, label in cur
        ]

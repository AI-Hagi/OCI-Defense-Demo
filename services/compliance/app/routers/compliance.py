"""
Compliance endpoints: control catalogue, aggregate scoring, DORA open incidents.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path
import oracledb

from ..db import get_conn, set_tenant_identifier, tenant_from_header

logger = logging.getLogger(__name__)

router = APIRouter(tags=["compliance"])

FRAMEWORKS = ("NIS2", "DORA", "GDPR", "VSNFD")


def _read_clob(value: Any) -> Any:
    if value is None:
        return None
    return value.read() if hasattr(value, "read") else value


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
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    # Per framework: total controls (for this tenant) and implemented = controls
    # whose most-recent finding is in a "good" state (mitigated, accepted,
    # false_positive, closed). Controls without findings count as "not
    # implemented". Score is implemented / total expressed as a percentage.
    sql = (
        "SELECT c.framework, "
        "       COUNT(*) AS total, "
        "       SUM(CASE WHEN f.status IN "
        "                     ('mitigated','accepted','false_positive','closed') "
        "                THEN 1 ELSE 0 END) AS implemented "
        "  FROM compliance_controls c "
        "  LEFT JOIN ( "
        "     SELECT control_id, status, "
        "            ROW_NUMBER() OVER (PARTITION BY control_id "
        "                               ORDER BY detected_at DESC) AS rn "
        "       FROM compliance_findings "
        "  ) f ON f.control_id = c.control_id AND f.rn = 1 "
        " WHERE c.tenant_id = :t "
        " GROUP BY c.framework"
    )

    seen: dict[str, dict[str, Any]] = {}
    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id})
        for fw, total, implemented in cur:
            total_i = int(total or 0)
            impl_i = int(implemented or 0)
            pct = round((impl_i / total_i) * 100, 2) if total_i else 0.0
            seen[fw] = {
                "framework": fw,
                "implemented": impl_i,
                "total": total_i,
                "score_pct": pct,
            }

    # Always return all four frameworks, even when empty, so the UI can render
    # a stable grid of score tiles.
    result: list[dict[str, Any]] = []
    for fw in FRAMEWORKS:
        result.append(
            seen.get(
                fw,
                {"framework": fw, "implemented": 0, "total": 0, "score_pct": 0.0},
            )
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

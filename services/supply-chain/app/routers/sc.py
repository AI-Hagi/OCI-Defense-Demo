"""
Supply Chain endpoints: nodes, edges, and per-node risk history.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path
import oracledb

from ..db import get_conn, set_tenant_identifier, tenant_from_header

logger = logging.getLogger(__name__)

router = APIRouter(tags=["supply-chain"])


def _read_clob(value: Any) -> Any:
    if value is None:
        return None
    return value.read() if hasattr(value, "read") else value


@router.get("/nodes")
def list_nodes(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    # Pull lat/lon out of SDO_GEOMETRY directly — frontend expects flat fields,
    # not a GeoJSON object. Latest risk score is the most recent sc_risk row.
    sql = (
        "SELECT n.node_id, n.tenant_id, n.node_type, n.display_name, "
        "       n.country_iso3, "
        "       n.location.SDO_POINT.Y AS latitude, "
        "       n.location.SDO_POINT.X AS longitude, "
        "       n.criticality, n.ols_label, "
        "       (SELECT r.risk_score FROM sc_risk r "
        "          WHERE r.node_id = n.node_id "
        "          ORDER BY r.as_of DESC FETCH FIRST 1 ROWS ONLY"
        "       ) AS latest_risk_score "
        "FROM sc_nodes n "
        "WHERE n.tenant_id = :t"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id})
        rows: list[dict[str, Any]] = []
        for (
            node_id,
            t_id,
            node_type,
            name,
            country,
            lat,
            lon,
            crit,
            ols,
            latest,
        ) in cur:
            rows.append(
                {
                    "node_id": node_id,
                    "tenant_id": t_id,
                    "node_type": node_type,
                    "display_name": name,
                    "country_iso3": country,
                    "latitude": float(lat) if lat is not None else None,
                    "longitude": float(lon) if lon is not None else None,
                    "criticality": int(crit) if crit is not None else None,
                    "ols_label": int(ols) if ols is not None else None,
                    "latest_risk_score": float(latest) if latest is not None else None,
                }
            )
        return rows


@router.get("/edges")
def list_edges(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    sql = (
        "SELECT e.edge_id, e.src_node, e.dst_node, e.edge_type, "
        "       e.lead_time_days, e.dependency_level "
        "FROM sc_edges e "
        "WHERE EXISTS ( "
        "   SELECT 1 FROM sc_nodes n "
        "   WHERE n.node_id = e.src_node AND n.tenant_id = :t "
        ")"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id})
        return [
            {
                "edge_id": eid,
                "src_node": src,
                "dst_node": dst,
                "edge_type": etype,
                "lead_time_days": int(lead) if lead is not None else None,
                "dependency_level": int(dep) if dep is not None else None,
            }
            for eid, src, dst, etype, lead, dep in cur
        ]


@router.get("/risk/{node_id}")
def get_risk(
    node_id: str = Path(..., min_length=1, max_length=36),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    # Defence in depth: confirm the node belongs to the requesting tenant before
    # returning risk history. OLS should block cross-tenant access too, but this
    # keeps error messages stable and avoids OLS "no rows" masking.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sc_nodes WHERE node_id = :n AND tenant_id = :t",
            {"n": node_id, "t": tenant_id},
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="node not found for tenant")

    # Most-recent 30 days, ordered ASC so the chart x-axis runs oldest→newest.
    sql = (
        "SELECT as_of, risk_score, risk_breakdown FROM ( "
        "  SELECT as_of, risk_score, risk_breakdown "
        "  FROM sc_risk "
        "  WHERE node_id = :n "
        "  ORDER BY as_of DESC "
        "  FETCH FIRST 30 ROWS ONLY "
        ") ORDER BY as_of ASC"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"n": node_id})
        rows: list[dict[str, Any]] = []
        for as_of, score, breakdown in cur:
            breakdown_text = _read_clob(breakdown)
            rows.append(
                {
                    "as_of": as_of.isoformat() if as_of else None,
                    "risk_score": float(score) if score is not None else None,
                    "risk_breakdown": json.loads(breakdown_text) if breakdown_text else None,
                }
            )
        return rows

"""
OSINT Fusion endpoints: entity lookup + property-graph traversal via SQL/PGQ.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
import oracledb

from ..db import get_conn, set_tenant_identifier, tenant_from_header

logger = logging.getLogger(__name__)

router = APIRouter(tags=["graph"])


class GraphQueryRequest(BaseModel):
    startEntity: str = Field(..., min_length=1, max_length=36)
    maxHops: int = Field(default=2, ge=1, le=5)


@router.get("/entities")
def search_entities(
    q: str = Query(..., min_length=1, max_length=200),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    sql = (
        "SELECT entity_id, canonical_name, kind "
        "FROM osint_entities "
        "WHERE tenant_id = :t "
        "  AND LOWER(canonical_name) LIKE LOWER(:q || '%') "
        "FETCH FIRST 50 ROWS ONLY"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id, "q": q})
        return [
            {"entity_id": eid, "canonical_name": name, "kind": kind}
            for eid, name, kind in cur
        ]


@router.post("/query-graph")
def query_graph(
    payload: GraphQueryRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> dict[str, list[dict[str, Any]]]:
    """Return nodes+edges radiating out from ``startEntity`` for D3 visualisation.

    Uses SQL/PGQ over the ``intel_fusion`` property graph. ``maxHops`` currently
    produces one-hop expansion per call; callers perform breadth-first expansion
    client-side when deeper traversal is required. The one-hop query is bounded
    to 500 rows to protect the DB.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    if not payload.startEntity.strip():
        raise HTTPException(status_code=400, detail="startEntity is required")

    sql = (
        "SELECT src_id, src_name, src_kind, rel_type, confidence, "
        "       dst_id, dst_name, dst_kind "
        "FROM GRAPH_TABLE (intel_fusion "
        "  MATCH (a IS entity) -[r IS relates_to]-> (b IS entity) "
        "  WHERE a.entity_id = :start "
        "  COLUMNS ( "
        "    a.entity_id      AS src_id, "
        "    a.canonical_name AS src_name, "
        "    a.kind           AS src_kind, "
        "    r.rel_type       AS rel_type, "
        "    r.confidence     AS confidence, "
        "    b.entity_id      AS dst_id, "
        "    b.canonical_name AS dst_name, "
        "    b.kind           AS dst_kind "
        "  ) "
        ") FETCH FIRST 500 ROWS ONLY"
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    with conn.cursor() as cur:
        cur.execute(sql, {"start": payload.startEntity})
        for src_id, src_name, src_kind, rel_type, confidence, dst_id, dst_name, dst_kind in cur:
            nodes.setdefault(
                src_id, {"id": src_id, "name": src_name, "kind": src_kind}
            )
            nodes.setdefault(
                dst_id, {"id": dst_id, "name": dst_name, "kind": dst_kind}
            )
            edges.append(
                {
                    "source": src_id,
                    "target": dst_id,
                    "rel_type": rel_type,
                    "confidence": float(confidence) if confidence is not None else None,
                }
            )

    return {"nodes": list(nodes.values()), "edges": edges, "maxHops": payload.maxHops}

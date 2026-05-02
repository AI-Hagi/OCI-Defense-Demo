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
    kind: str | None = Query(default=None, max_length=40),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Prefix-search OSINT entities, optionally filtered by ``kind``.

    Setting ``kind=ems_emission`` retrieves UC4 EMS indicators. The EMS
    payload (frequency, bandwidth, modulation, …) lives in the JSON
    ``attributes`` column so the response shape stays uniform.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    base_sql = (
        "SELECT entity_id, canonical_name, kind, attributes "
        "FROM osint_entities "
        "WHERE tenant_id = :t "
        "  AND LOWER(canonical_name) LIKE LOWER(:q || '%') "
    )
    params: dict[str, Any] = {"t": tenant_id, "q": q}
    if kind:
        base_sql += "  AND kind = :kind "
        params["kind"] = kind
    base_sql += "FETCH FIRST 50 ROWS ONLY"

    rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(base_sql, params)
        for eid, name, k, attrs in cur:
            attrs_text = attrs.read() if hasattr(attrs, "read") else attrs
            rows.append({
                "entity_id": eid,
                "canonical_name": name,
                "kind": k,
                "attributes": _parse_attrs(attrs_text),
            })
        return rows


def _parse_attrs(raw: Any) -> dict[str, Any] | None:
    """Decode the JSON attributes column into a dict (or None)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    import json

    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


@router.get("/ems/clusters")
def ems_clusters(
    band_mhz_step: float = Query(default=50.0, ge=1.0, le=10000.0),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    """Group EMS emissions into frequency buckets.

    For UC4 ("EMS-Lagebildfusion") the operator dashboard groups
    ``ems_emission`` entities by their reported ``frequency_mhz`` into
    buckets of ``band_mhz_step`` MHz so a "lit-up spectrum" panel can
    render without client-side rebucketing. Each bucket reports its
    centre frequency, the count of emitters, and a sample entity_id for
    drill-down.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    sql = (
        "SELECT FLOOR(JSON_VALUE(attributes, '$.frequency_mhz' "
        "             RETURNING NUMBER) / :step) * :step AS bucket_start, "
        "       COUNT(*) AS emitter_count, "
        "       MIN(entity_id) AS sample_entity_id "
        "FROM osint_entities "
        "WHERE tenant_id = :t "
        "  AND kind = 'ems_emission' "
        "  AND JSON_VALUE(attributes, '$.frequency_mhz') IS NOT NULL "
        "GROUP BY FLOOR(JSON_VALUE(attributes, '$.frequency_mhz' "
        "             RETURNING NUMBER) / :step) * :step "
        "ORDER BY bucket_start"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id, "step": band_mhz_step})
        return [
            {
                "bucket_mhz_start": float(start) if start is not None else None,
                "bucket_mhz_end": (float(start) + band_mhz_step)
                                  if start is not None else None,
                "emitter_count": int(count),
                "sample_entity_id": sample,
            }
            for start, count, sample in cur
        ]


@router.post("/query-graph")
def query_graph(
    payload: GraphQueryRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> dict[str, Any]:
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

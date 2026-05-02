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


def _read_lob(value: Any) -> Any:
    """Materialize a CLOB into a Python str (or pass-through for non-LOBs)."""
    return value.read() if hasattr(value, "read") else value


def _resolve_start_entity(
    conn: oracledb.Connection, tenant_id: str, start: str
) -> tuple[str | None, str | None]:
    """Map ``start`` (entity_id, canonical_name, or substring) to an entity row.

    Returns (entity_id, canonical_name) or (None, None) if nothing matches.
    """
    with conn.cursor() as cur:
        # Exact entity_id (16-byte HEX) match first.
        if len(start) == 32 and all(c in "0123456789ABCDEFabcdef" for c in start):
            cur.execute(
                "SELECT entity_id, canonical_name FROM osint_entities "
                "WHERE tenant_id = :t AND entity_id = HEXTORAW(:s)",
                {"t": tenant_id, "s": start.upper()},
            )
            row = cur.fetchone()
            if row:
                return (row[0].hex().upper() if hasattr(row[0], "hex") else row[0], row[1])

        # Exact name (case-insensitive).
        cur.execute(
            "SELECT entity_id, canonical_name FROM osint_entities "
            "WHERE tenant_id = :t AND LOWER(canonical_name) = LOWER(:s) "
            "FETCH FIRST 1 ROWS ONLY",
            {"t": tenant_id, "s": start},
        )
        row = cur.fetchone()
        if row:
            eid = row[0].hex().upper() if hasattr(row[0], "hex") else row[0]
            return (eid, row[1])

        # Prefix / substring match — picks the shortest name that contains start.
        cur.execute(
            "SELECT entity_id, canonical_name FROM osint_entities "
            "WHERE tenant_id = :t AND LOWER(canonical_name) LIKE LOWER('%' || :s || '%') "
            "ORDER BY LENGTH(canonical_name) "
            "FETCH FIRST 1 ROWS ONLY",
            {"t": tenant_id, "s": start},
        )
        row = cur.fetchone()
        if row:
            eid = row[0].hex().upper() if hasattr(row[0], "hex") else row[0]
            return (eid, row[1])

    return (None, None)


@router.get("/graph")
def graph_get(
    start: str = Query(..., min_length=1, max_length=400,
                       description="entity_id (32-hex) or canonical_name / substring"),
    hops: int = Query(default=2, ge=1, le=4),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> dict[str, Any]:
    """GET form of the property-graph traversal.

    Returns the full ``OsintGraph`` shape the React frontend expects:
    nodes carry tenant_id/attributes/ols_label/created_at; edges carry
    rel_id/confidence/evidence/ols_label/observed_at.

    The ``start`` parameter is flexible — caller may pass either an
    entity_id (32-character hex) or a canonical_name / substring; the
    server resolves to the entity_id internally.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    eid, name = _resolve_start_entity(conn, tenant_id, start.strip())
    if not eid:
        # No entity matched — return an empty graph. The frontend handles
        # this by showing an empty-state hint rather than 404.
        return {"nodes": [], "edges": []}

    # Two passes: (a) outgoing relationships, (b) incoming. Both are
    # constrained to ``hops`` levels via a recursive CTE so we don't
    # rely on GRAPH_TABLE bind-var support (which has been flaky on
    # ATP-Shared in the past).
    # CAST both legs of the recursive UNION to RAW(16) — without the cast,
    # HEXTORAW(:bind) defaults to RAW(2000) and the recursive leg returns
    # RAW(16) (the schema column type), giving ORA-01790 type mismatch.
    sql = (
        "WITH reachable (entity_id, lvl) AS ( "
        "  SELECT CAST(HEXTORAW(:start_id) AS RAW(16)) AS entity_id, "
        "         CAST(0 AS NUMBER) AS lvl FROM dual "
        "  UNION ALL "
        "  SELECT CAST(CASE WHEN r.src_id = parent.entity_id THEN r.dst_id "
        "                   ELSE r.src_id END AS RAW(16)), "
        "         parent.lvl + 1 "
        "    FROM reachable parent "
        "    JOIN osint_relationships r "
        "      ON parent.entity_id IN (r.src_id, r.dst_id) "
        "   WHERE parent.lvl < :max_hops "
        ") "
        "SELECT DISTINCT entity_id FROM reachable"
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    visited_ids: set[str] = set()

    with conn.cursor() as cur:
        cur.execute(sql, {"start_id": eid, "max_hops": hops})
        for (raw_id,) in cur:
            visited_ids.add(raw_id.hex().upper() if hasattr(raw_id, "hex") else raw_id)

    if not visited_ids:
        return {"nodes": [], "edges": []}

    # Hydrate nodes.
    placeholders = ",".join(f":id{i}" for i in range(len(visited_ids)))
    sql_nodes = (
        f"SELECT RAWTOHEX(entity_id), tenant_id, kind, canonical_name, "
        f"       attributes, ols_label, created_at "
        f"FROM osint_entities "
        f"WHERE entity_id IN ({placeholders}) AND tenant_id = :t"
    )
    params: dict[str, Any] = {"t": tenant_id}
    for i, hex_id in enumerate(visited_ids):
        params[f"id{i}"] = bytes.fromhex(hex_id)
    with conn.cursor() as cur:
        cur.execute(sql_nodes, params)
        for entity_id, tid, kind, cname, attrs, ols, created in cur:
            nodes[entity_id.upper()] = {
                "entity_id": entity_id.upper(),
                "tenant_id": tid,
                "kind": kind,
                "canonical_name": cname,
                "attributes": _read_lob(attrs),
                "ols_label": int(ols) if ols is not None else None,
                "created_at": created.isoformat() if created else None,
            }

    # Hydrate edges (any rel where both endpoints are in the visited set).
    sql_edges = (
        f"SELECT RAWTOHEX(rel_id), RAWTOHEX(src_id), RAWTOHEX(dst_id), "
        f"       rel_type, confidence, evidence, ols_label, observed_at "
        f"FROM osint_relationships "
        f"WHERE src_id IN ({placeholders}) AND dst_id IN ({placeholders})"
    )
    params2: dict[str, Any] = {}
    for i, hex_id in enumerate(visited_ids):
        params2[f"id{i}"] = bytes.fromhex(hex_id)
    # Re-bind the same set twice with stable param names.
    with conn.cursor() as cur:
        cur.execute(sql_edges, params2)
        for rid, src, dst, rtype, conf, evid, ols, observed in cur:
            edges.append({
                "rel_id": rid.upper(),
                "src_id": src.upper(),
                "dst_id": dst.upper(),
                "rel_type": rtype,
                "confidence": float(conf) if conf is not None else None,
                "evidence": _read_lob(evid),
                "ols_label": int(ols) if ols is not None else None,
                "observed_at": observed.isoformat() if observed else None,
            })

    logger.info(
        "GET /graph start=%r resolved=%r tenant=%s hops=%d -> %d nodes, %d edges",
        start, name, tenant_id, hops, len(nodes), len(edges),
    )
    return {"nodes": list(nodes.values()), "edges": edges}


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

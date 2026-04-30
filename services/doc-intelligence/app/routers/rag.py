"""
Document Intelligence /search and /chat endpoints backed by 26ai Vector Search.
"""
from __future__ import annotations

import array
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
import oracledb

from ..db import get_conn, set_tenant_identifier, tenant_from_header
from ..ml import embed
from ..models import (
    ChatRequest,
    ChatResponse,
    Citation,
    SearchHit,
    SearchRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])


def _to_oracle_vector(vec: list[float]) -> array.ArrayType:
    """oracledb binds VECTOR from an ``array.array('f', ...)`` Float32 buffer."""
    return array.array("f", vec)


def _fetch_top_k(
    conn: oracledb.Connection, tenant_id: str, query_vec: list[float], k: int
) -> list[SearchHit]:
    sql = (
        "SELECT d.doc_id, d.title, dc.chunk_idx, dc.text, "
        "VECTOR_DISTANCE(de.embedding, :qv, COSINE) AS dist "
        "FROM document_embeddings de "
        "JOIN document_chunks dc ON dc.chunk_id = de.chunk_id "
        "JOIN documents d        ON d.doc_id    = dc.doc_id "
        "WHERE d.tenant_id = :t "
        "ORDER BY dist "
        "FETCH APPROX FIRST :k ROWS ONLY"
    )
    with conn.cursor() as cur:
        cur.execute(sql, {"qv": _to_oracle_vector(query_vec), "t": tenant_id, "k": k})
        hits: list[SearchHit] = []
        for doc_id, title, chunk_idx, text, dist in cur:
            text_val = text.read() if hasattr(text, "read") else text
            hits.append(
                SearchHit(
                    doc_id=doc_id,
                    title=title,
                    chunk_idx=int(chunk_idx),
                    text=text_val or "",
                    dist=float(dist) if dist is not None else 0.0,
                )
            )
        return hits


@router.post("/search", response_model=list[SearchHit])
def search(
    payload: SearchRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[SearchHit]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    try:
        query_vec = embed(payload.q)
    except Exception as exc:  # pragma: no cover
        logger.exception("Embedding failed")
        raise HTTPException(status_code=500, detail=f"embedding failed: {exc}") from exc

    return _fetch_top_k(conn, tenant_id, query_vec, payload.k)


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> ChatResponse:
    """MVP stub: retrieves top-5 relevant chunks and returns a templated answer.

    No external LLM is invoked. The response echoes the user question, lists
    the retrieved citations, and surfaces the first citation's text so the
    frontend can render a meaningful response. Swap in an LLM call later.
    """
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    last_user = next(
        (m.content for m in reversed(payload.messages) if m.role == "user"),
        None,
    )
    if not last_user:
        raise HTTPException(status_code=400, detail="No user message in conversation")

    try:
        query_vec = embed(last_user)
    except Exception as exc:  # pragma: no cover
        logger.exception("Embedding failed")
        raise HTTPException(status_code=500, detail=f"embedding failed: {exc}") from exc

    hits = _fetch_top_k(conn, tenant_id, query_vec, k=5)
    citations = [Citation(doc_id=h.doc_id, chunk_idx=h.chunk_idx) for h in hits]

    if not hits:
        answer = (
            "No classified documents matched your question. "
            "Ingest or share documents with this tenant and try again."
        )
    else:
        bullet_lines = [
            f"- [{i + 1}] {h.title} (chunk {h.chunk_idx}): {h.text[:240].strip()}"
            for i, h in enumerate(hits[:3])
        ]
        answer = (
            "Based on the classified document corpus, the most relevant excerpts "
            "for your question are:\n" + "\n".join(bullet_lines) + "\n\n"
            "(MVP stub response — integrate a sovereign LLM to generate a "
            "synthesized answer grounded in these citations.)"
        )

    return ChatResponse(role="assistant", content=answer, answer=answer, citations=citations)

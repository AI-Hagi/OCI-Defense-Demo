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
from ..llm import synthesise_rag_answer
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
    x_ols_label_max: str | None = Header(default=None, alias="X-OLS-Label-Max"),
    conn: oracledb.Connection = Depends(get_conn),
) -> ChatResponse:
    """RAG chat — retrieves top-5 chunks via 26ai Vector Search, then asks
    Cohere Command R+ (OnDemand, eu-frankfurt-1) to synthesise a German
    answer grounded in numbered citations.

    Falls back to a deterministic bullet-list answer (the MVP shape) when
    the LLM call fails — auth, missing compartment OCID, OCI 4xx/5xx,
    empty response. The frontend always gets a usable response.
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
            "Es wurden keine klassifizierten Dokumente gefunden, die zu Ihrer "
            "Frage passen. Indizieren Sie Dokumente für diesen Tenant und "
            "versuchen Sie es erneut."
        )
        return ChatResponse(role="assistant", content=answer, answer=answer, citations=citations)

    # Deterministic fallback used when the LLM call fails — keeps the demo
    # alive even if the OCI signer or generative-ai-family policy is missing.
    fallback_lines = [
        f"- [{i + 1}] {h.title} (chunk {h.chunk_idx}): {h.text[:240].strip()}"
        for i, h in enumerate(hits[:3])
    ]
    fallback_answer = (
        "Auf Basis des klassifizierten Dokumenten-Korpus wurden folgende "
        "Auszüge gefunden:\n" + "\n".join(fallback_lines) + "\n\n"
        "(Fallback-Antwort — die LLM-Synthese ist gerade nicht verfügbar.)"
    )

    answer = synthesise_rag_answer(
        question=last_user,
        hits=[
            {
                "title": h.title,
                "chunk_idx": h.chunk_idx,
                "text": h.text,
                "doc_id": h.doc_id,
            }
            for h in hits
        ],
        ols_cap=(x_ols_label_max or "OFFEN").upper(),
        fallback_text=fallback_answer,
    )

    return ChatResponse(role="assistant", content=answer, answer=answer, citations=citations)

"""
Document upload endpoint — chunks the file, embeds each chunk, and persists
into the 26ai documents / document_chunks / document_embeddings tables.

Scope:
  * Text-like files only for now: text/plain, text/markdown, application/json,
    text/csv. PDF/DOCX support is a follow-up (needs pypdf / python-docx and
    a docker base-image change).
  * Chunking is a simple sliding window over whitespace-tokenized text:
    ~CHUNK_TOKENS tokens per chunk with CHUNK_OVERLAP tokens of overlap.
    Good enough for the demo corpus; the production path would call
    OCI Document Understanding for layout-aware chunking.
  * Embeddings come from the existing `ml.embed` (Sentence-Transformers
    MiniLM-L6 zero-padded to 1024 dims). Same code path as /search and /chat
    so retrieval stays consistent.
  * Classification field is required and stored on documents.classification.
    The UC2 schema also has an `ols_label` column on document_chunks; we
    populate it from the document's classification mapped through the
    OLS_LEVELS dictionary so persona-based filtering keeps working.
"""
from __future__ import annotations

import array
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
import oracledb

from ..db import get_conn, set_tenant_identifier, tenant_from_header
from ..ml import embed
from ..models import Citation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])

# Conservative chunking: ~500 tokens per chunk, 50-token overlap.
CHUNK_TOKENS = 500
CHUNK_OVERLAP = 50

# Mirrors db/schema/01_tenants_and_security.sql — server-side mapping so the
# numeric ols_label on document_chunks aligns with the front-end persona.
OLS_LEVELS: dict[str, int] = {
    "OFFEN": 10,
    "INTERN": 30,
    "NFD": 50,
    "GEHEIM": 70,
    # Legacy aliases (UC2 originally used U/R/C/S — keep both working).
    "U": 10,
    "R": 30,
    "C": 50,
    "S": 70,
    "VS-NFD": 50,
}

# documents.classification has a CHECK constraint that only accepts the
# legacy short codes (db/schema/02_core_tables.sql:89). Map the German
# personas to those codes when persisting; the numeric ols_label on
# document_chunks keeps the granular OLS level for retrieval-side filtering.
DB_CLASSIFICATION_CODE: dict[str, str] = {
    "OFFEN": "U",
    "INTERN": "R",
    "NFD": "VS-NFD",
    "GEHEIM": "S",
    "U": "U",
    "R": "R",
    "C": "C",
    "S": "S",
    "VS-NFD": "VS-NFD",
}

ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/octet-stream",  # browsers sometimes send .md as octet-stream
}

MAX_BYTES = 5 * 1024 * 1024  # 5 MB hard cap; tune later if you need bigger


def _to_oracle_vector(vec: list[float]) -> array.ArrayType:
    return array.array("f", vec)


def _chunk_text(text: str, chunk_tokens: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into chunks of ~chunk_tokens whitespace-tokens with overlap."""
    tokens = re.split(r"\s+", text.strip())
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    chunks: list[str] = []
    step = chunk_tokens - overlap
    for start in range(0, len(tokens), step):
        end = min(start + chunk_tokens, len(tokens))
        chunks.append(" ".join(tokens[start:end]))
        if end == len(tokens):
            break
    return chunks


@router.post("/upload", response_model=dict)
async def upload_document(
    file: Annotated[UploadFile, File(description="Document file (text/markdown/csv/json, up to 5 MB)")],
    title: Annotated[str, Form(min_length=1, max_length=400)],
    classification: Annotated[str, Form(min_length=1, max_length=10)] = "INTERN",
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> dict:
    """Persist an uploaded text-like document and embed its chunks.

    Returns: {doc_id, title, classification, chunk_count, ols_label}
    """
    classification = classification.upper().replace(" ", "-")
    if classification not in OLS_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"classification must be one of {sorted(set(OLS_LEVELS))}",
        )
    ols_label = OLS_LEVELS[classification]
    db_class_code = DB_CLASSIFICATION_CODE[classification]

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported content-type {content_type!r}. "
                f"Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
            ),
        )

    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty document")

    chunks = _chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="No tokens after whitespace-split")

    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    # Persist documents → document_chunks → document_embeddings in one
    # transaction. Cleanup on failure relies on the FK CASCADE wired up
    # in db/schema/02_core_tables.sql.
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO documents (tenant_id, title, classification, source_uri) "
                "VALUES (:t, :title, :cls, :src) "
                "RETURNING doc_id INTO :doc_id",
                {
                    "t": tenant_id,
                    "title": title,
                    "cls": db_class_code,
                    "src": f"upload://{file.filename}",
                    "doc_id": cur.var(oracledb.STRING),
                },
            )
            doc_id = cur.bindvars["doc_id"].getvalue()[0]

            for idx, chunk in enumerate(chunks):
                cur.execute(
                    "INSERT INTO document_chunks (doc_id, chunk_idx, text, ols_label) "
                    "VALUES (:doc_id, :idx, :text, :ols) "
                    "RETURNING chunk_id INTO :chunk_id",
                    {
                        "doc_id": doc_id,
                        "idx": idx,
                        "text": chunk,
                        "ols": ols_label,
                        "chunk_id": cur.var(oracledb.STRING),
                    },
                )
                chunk_id = cur.bindvars["chunk_id"].getvalue()[0]

                vec = embed(chunk)
                cur.execute(
                    "INSERT INTO document_embeddings (chunk_id, embedding) "
                    "VALUES (:chunk_id, :embedding)",
                    {"chunk_id": chunk_id, "embedding": _to_oracle_vector(vec)},
                )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.exception("Upload persistence failed")
        raise HTTPException(status_code=500, detail=f"Persist failed: {exc}") from exc

    logger.info(
        "Document uploaded: doc_id=%s tenant=%s title=%r chunks=%d cls=%s",
        doc_id, tenant_id, title, len(chunks), classification,
    )
    return {
        "doc_id": doc_id,
        "title": title,
        "classification": classification,
        "ols_label": ols_label,
        "chunk_count": len(chunks),
        "first_chunk_preview": chunks[0][:200] if chunks else "",
        "citations_hint": [Citation(doc_id=doc_id, chunk_idx=i).model_dump() for i in range(min(3, len(chunks)))],
    }

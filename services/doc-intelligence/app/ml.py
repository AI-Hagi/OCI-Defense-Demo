"""
Lazy Sentence-Transformers embedder singleton for the Document Intelligence RAG.

NOTE ON DIMENSION MISMATCH (MVP stub):
The DB column ``document_embeddings.embedding`` is declared ``VECTOR(1024, FLOAT32)``
(bge-large-en-v1.5 native), but for a small, self-contained MVP we use
``all-MiniLM-L6-v2`` which produces 384-dim vectors. To keep inserts and
``VECTOR_DISTANCE`` queries schema-compatible, every vector is zero-padded from
384 to 1024 dimensions before being bound into Oracle. This preserves nearest-
neighbour ordering among vectors produced by the same model (the extra zero
coordinates are identical across rows, so they contribute a constant term to
cosine distance). Swap in bge-large-en-v1.5 for production-grade quality.
"""
from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

TARGET_DIM = 1024  # matches document_embeddings.embedding VECTOR(1024, FLOAT32)

_MODEL: Any | None = None
_LOCK = Lock()


def _load_model() -> Any:
    from sentence_transformers import SentenceTransformer

    name = os.environ.get("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    logger.info("Loading sentence-transformers model %s", name)
    return SentenceTransformer(name)


def get_model() -> Any:
    global _MODEL
    if _MODEL is None:
        with _LOCK:
            if _MODEL is None:
                _MODEL = _load_model()
    return _MODEL


def embed(text: str) -> list[float]:
    """Return a ``TARGET_DIM``-length float vector (zero-padded if needed)."""
    model = get_model()
    raw = model.encode([text], normalize_embeddings=True)[0]
    vec = np.asarray(raw, dtype=np.float32)
    if vec.shape[0] < TARGET_DIM:
        pad = np.zeros(TARGET_DIM - vec.shape[0], dtype=np.float32)
        vec = np.concatenate([vec, pad])
    elif vec.shape[0] > TARGET_DIM:
        vec = vec[:TARGET_DIM]
    return vec.tolist()

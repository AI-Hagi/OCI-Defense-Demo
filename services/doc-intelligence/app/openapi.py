"""OpenAPI metadata customization for the Document Intelligence service.

Contract for peer agents implementing ``services/doc-intelligence/app/main.py``:

    from fastapi import FastAPI
    from app.openapi import customize_openapi

    app = FastAPI()
    customize_openapi(app)  # MUST be called before any router is attached
    # ...include routers...

``customize_openapi`` sets ``app.title``, ``app.description``, ``app.version``,
``app.contact``, ``app.license_info``, ``app.servers`` and replaces
``app.openapi`` with a wrapper that injects an ``X-Tenant-Id`` header parameter
into every path for multi-tenant OLS binding.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


SERVICE_NAME = "doc-intelligence"
SERVICE_PORT = 8002
BASE_PATH = "/api/documents"

tags_metadata: List[Dict[str, Any]] = [
    {
        "name": "documents",
        "description": (
            "Dokumenten-Upload und Klassifizierungs-Management. Documents are "
            "stored in OCI Object Storage; metadata + Label-Security tags go "
            "to Oracle 26ai."
        ),
    },
    {
        "name": "chunks",
        "description": (
            "Chunking- und Embedding-Pipeline. Splits documents, generates "
            "1536-dim embeddings (Cohere/OpenAI via OCI Generative AI), "
            "persists them into ``DOC_CHUNK.EMBEDDING`` with DiskANN index."
        ),
    },
    {
        "name": "rag",
        "description": (
            "Retrieval-Augmented Generation ueber klassifizierte Dokumente. "
            "Hybrid search (vector + keyword) with VS-NfD/NATO RESTRICTED "
            "label enforcement at query time."
        ),
    },
    {
        "name": "health",
        "description": "Liveness/Readiness probes for OKE.",
    },
]


def customize_openapi(app: FastAPI) -> None:
    """Attach Document Intelligence-specific OpenAPI metadata."""

    app.title = "Sovereign Defence — Document Intelligence Service"
    app.version = "0.1.0"
    app.description = (
        "## Document Intelligence — RAG ueber klassifizierte Dokumente\n\n"
        "Dieser Service indiziert klassifizierte Dokumente (VS-NfD, NATO "
        "RESTRICTED, EU RESTRICTED) und ermoeglicht semantische Suche sowie "
        "generative Antworten mit nachweisbarer Quellenangabe. Die "
        "Klassifizierungs-Labels werden vom Oracle-Label-Security-Layer "
        "durchgesetzt — Nutzer sehen nur Chunks, fuer die sie freigegeben "
        "sind.\n\n"
        "### Technical\n\n"
        "Chunking pipeline writes into ``DOC_CHUNK`` with 1536-dimensional "
        "embeddings from OCI Generative AI. Hybrid retrieval combines "
        "``VECTOR_DISTANCE(..., COSINE)`` with Oracle Text keyword search. "
        "Generation is delegated to OCI Generative AI (Cohere Command R+) "
        "and cited chunks are returned alongside the answer. Every request "
        "requires ``X-Tenant-Id`` to bind the OLS session label.\n\n"
        "### Consumed by\n\n"
        "Frontend view `DocIntelView` (document list + RAG chat) and the "
        "compliance service for policy retrieval."
    )
    app.contact = {
        "name": "Sovereign Defence Ops",
        "email": "ops@sovdefence.example.eu",
    }
    app.license_info = {
        "name": "Proprietary — Sovereign Defence Partners",
        "identifier": "LicenseRef-SovDef-0.1",
    }
    app.servers = [
        {"url": f"http://localhost:{SERVICE_PORT}", "description": "Local dev"},
        {
            "url": f"https://api-{SERVICE_NAME}.sovdefence.example.eu",
            "description": "Production (OKE, EU-sovereign)",
        },
    ]
    app.openapi_tags = tags_metadata

    def _custom_openapi() -> Dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=tags_metadata,
            servers=app.servers,
            contact=app.contact,
            license_info=app.license_info,
        )
        tenant_header = {
            "name": "X-Tenant-Id",
            "in": "header",
            "required": True,
            "description": (
                "Mandant-ID (z.B. ``T001``). Bindet die Oracle-Label-Security-"
                "Session-Label. Ohne diesen Header antwortet der Service mit "
                "HTTP 400."
            ),
            "schema": {"type": "string", "example": "T001"},
        }
        for path_item in schema.get("paths", {}).values():
            for method, operation in path_item.items():
                if method.lower() not in {
                    "get", "post", "put", "patch", "delete", "head", "options",
                }:
                    continue
                params = operation.setdefault("parameters", [])
                if not any(
                    p.get("name") == "X-Tenant-Id" and p.get("in") == "header"
                    for p in params
                ):
                    params.append(tenant_header)
        schema["x-tenant-header"] = {
            "name": "X-Tenant-Id",
            "required": True,
            "description": "Mandatory on every path — binds OLS session label.",
        }
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi  # type: ignore[assignment]

"""OpenAPI metadata customization for the GEOINT service.

Contract for peer agents implementing ``services/geoint/app/main.py``:

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


SERVICE_NAME = "geoint"
SERVICE_PORT = 8001
BASE_PATH = "/api/geoint"

tags_metadata: List[Dict[str, Any]] = [
    {
        "name": "scenes",
        "description": (
            "Satellitenszenen-Katalog — Upload, Metadaten, Kachelung. "
            "Scene catalogue backed by Oracle 26ai Spatial (SDO_GEOMETRY) "
            "and Object Storage for raster payloads."
        ),
    },
    {
        "name": "ml-inference",
        "description": (
            "YOLOv8-Objekterkennung und Vektor-Ähnlichkeitssuche. "
            "Runs YOLOv8 detection over uploaded scenes, persists detections "
            "as 1536-dim embeddings in Oracle 26ai AI Vector Search."
        ),
    },
    {
        "name": "detections",
        "description": (
            "Erkennungsobjekte (Fahrzeuge, Schiffe, Infrastruktur) mit "
            "Geokoordinaten. Detection records with bounding boxes, class "
            "labels, confidence scores and georeferenced centroids."
        ),
    },
    {
        "name": "health",
        "description": "Liveness/Readiness probes for OKE.",
    },
]


def customize_openapi(app: FastAPI) -> None:
    """Attach GEOINT-specific OpenAPI metadata to the given FastAPI app."""

    app.title = "Sovereign Defence — GEOINT Service"
    app.version = "0.1.0"
    app.description = (
        "## GEOINT — Satellitenaufklärung mit Oracle 26ai\n\n"
        "Dieser Service verwaltet Satellitenszenen, fuehrt YOLOv8-basierte "
        "Objekterkennung aus und indiziert Detektionen als Vektor-Embeddings "
        "in Oracle 26ai. Er ist Teil der souveraenen Verteidigungsplattform "
        "und laeuft ausschliesslich in EU-OCI-Regionen (Frankfurt/Amsterdam) "
        "mit Label-Security-Mandantentrennung.\n\n"
        "### Technical\n\n"
        "FastAPI service exposing synchronous detection endpoints backed by "
        "Oracle 26ai Autonomous Transaction Processing (``sovdef26_tp``). "
        "Rasters live in OCI Object Storage and are referenced by signed URL. "
        "Vector similarity search uses ``VECTOR_DISTANCE(..., COSINE)`` with "
        "a DiskANN index on ``DETECTION.EMBEDDING``. Every request must carry "
        "an ``X-Tenant-Id`` header which binds the Oracle Label Security "
        "session label for row-level visibility.\n\n"
        "### Consumed by\n\n"
        "Frontend view `GeointView` (map + detection overlay) and the OSINT "
        "fusion service (geo-correlation)."
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

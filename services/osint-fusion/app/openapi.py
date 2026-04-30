"""OpenAPI metadata customization for the OSINT Fusion service.

Contract for peer agents implementing ``services/osint-fusion/app/main.py``:

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


SERVICE_NAME = "osint-fusion"
SERVICE_PORT = 8003
BASE_PATH = "/api/osint"

tags_metadata: List[Dict[str, Any]] = [
    {
        "name": "sources",
        "description": (
            "OSINT-Quellen-Katalog (Social Media, News-Feeds, Telegram, "
            "RSS). Source registry with ingest cadence and trust score."
        ),
    },
    {
        "name": "entities",
        "description": (
            "Extrahierte Entitaeten (Personen, Orte, Organisationen, "
            "Ereignisse). Entities persisted in Oracle 26ai with "
            "NER-derived attributes."
        ),
    },
    {
        "name": "graph",
        "description": (
            "Property-Graph-Abfragen (PGQL). Uses Oracle 26ai Property "
            "Graph to correlate entities across sources and time windows."
        ),
    },
    {
        "name": "threats",
        "description": (
            "Threat-Fusion und Indikator-Aggregation. Combines graph "
            "signals with GEOINT detections and supply-chain alerts."
        ),
    },
    {
        "name": "health",
        "description": "Liveness/Readiness probes for OKE.",
    },
]


def customize_openapi(app: FastAPI) -> None:
    """Attach OSINT Fusion-specific OpenAPI metadata."""

    app.title = "Sovereign Defence — OSINT & Threat Fusion Service"
    app.version = "0.1.0"
    app.description = (
        "## OSINT & Threat Fusion — Graph Analytics auf Oracle 26ai\n\n"
        "Dieser Service aggregiert offen-quellige Informationen aus Social "
        "Media, News-Feeds und Telegram-Kanaelen, extrahiert Entitaeten via "
        "NER und persistiert sie als Property Graph in Oracle 26ai. Ziel ist "
        "die Fusion heterogener Signale zu einer einheitlichen Lagekarte mit "
        "nachvollziehbaren Beweisketten.\n\n"
        "### Technical\n\n"
        "Sources are ingested asynchronously via OCI Streaming. Entity "
        "extraction uses spaCy + a domain-tuned transformer. The graph "
        "layer is Oracle 26ai Property Graph queried through PGQL. Threat "
        "fusion correlates graph paths with GEOINT detections (via spatial "
        "join) and supply-chain alerts. All responses enforce OLS labels "
        "bound to the ``X-Tenant-Id`` header.\n\n"
        "### Consumed by\n\n"
        "Frontend view `OsintView` (graph explorer + timeline) and the "
        "compliance service (incident reporting)."
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

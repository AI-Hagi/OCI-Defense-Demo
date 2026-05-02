"""OpenAPI metadata customization for the Supply Chain service.

Contract for peer agents implementing ``services/supply-chain/app/main.py``:

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


SERVICE_NAME = "supply-chain"
SERVICE_PORT = 8004
BASE_PATH = "/api/sc"

tags_metadata: List[Dict[str, Any]] = [
    {
        "name": "suppliers",
        "description": (
            "Lieferanten-Stammdaten inklusive Sanktions- und Jurisdiktions-"
            "Flags. Supplier master data with sanctions/jurisdiction flags."
        ),
    },
    {
        "name": "components",
        "description": (
            "Komponenten und Stuecklisten (BoM). Components and "
            "bill-of-material relationships stored as a property graph."
        ),
    },
    {
        "name": "graph",
        "description": (
            "Knowledge-Graph-Traversal entlang Lieferketten. PGQL queries "
            "on the Oracle 26ai Property Graph for multi-hop dependency "
            "analysis."
        ),
    },
    {
        "name": "risk",
        "description": (
            "Risiko-Scoring und Schwachstellen-Erkennung. Computes exposure "
            "to single-source components, sanctioned jurisdictions and "
            "criticality-weighted chokepoints."
        ),
    },
    {
        "name": "health",
        "description": "Liveness/Readiness probes for OKE.",
    },
]


def customize_openapi(app: FastAPI) -> None:
    """Attach Supply Chain-specific OpenAPI metadata."""

    app.title = "Sovereign Defence — Supply Chain Knowledge Graph"
    app.version = "0.1.0"
    app.description = (
        "## Supply Chain — Lieferketten-Graph auf Oracle 26ai\n\n"
        "Dieser Service modelliert Ruestungs- und Dual-Use-Lieferketten als "
        "Property Graph in Oracle 26ai. Er beantwortet Fragen wie 'Welche "
        "meiner Waffensysteme haengen von einer sanktionierten Jurisdiktion "
        "ab?' und bewertet Single-Source-Risiken entlang Mehrebenen-BoMs.\n\n"
        "### Technical\n\n"
        "Suppliers, components and products are stored as vertices in an "
        "Oracle 26ai Property Graph. Edges model ``SUPPLIES``, ``CONTAINS`` "
        "and ``OPERATES_IN`` (jurisdiction). Risk scoring runs PGQL "
        "traversals over multi-level BoMs and joins sanctions lists held in "
        "relational tables. Every request is OLS-scoped via ``X-Tenant-Id``.\n\n"
        "### Consumed by\n\n"
        "Frontend view `SupplyChainView` (graph explorer + risk heatmap) "
        "and the compliance service (NIS2 supply-chain reporting)."
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

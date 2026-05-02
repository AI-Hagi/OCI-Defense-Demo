"""OpenAPI metadata customization for the Compliance service.

Contract for peer agents implementing ``services/compliance/app/main.py``:

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


SERVICE_NAME = "compliance"
SERVICE_PORT = 8005
BASE_PATH = "/api/compliance"

tags_metadata: List[Dict[str, Any]] = [
    {
        "name": "controls",
        "description": (
            "Kontroll-Katalog fuer NIS2, DORA, GDPR und VS-NfD. Control "
            "catalogue mapped to regulatory frameworks."
        ),
    },
    {
        "name": "evidence",
        "description": (
            "Nachweise und Audit-Artefakte. Evidence items (log excerpts, "
            "screenshots, policy exports) anchored to Oracle 26ai "
            "Blockchain Tables for tamper-evidence."
        ),
    },
    {
        "name": "assessments",
        "description": (
            "Audit-Durchlaeufe und Reife-Bewertungen. Assessment runs "
            "aggregating control status across tenants and time windows."
        ),
    },
    {
        "name": "reports",
        "description": (
            "Regulatorische Berichte (NIS2-Incident-Report, DORA-ICT-"
            "Register, GDPR Art.30). Report generation via templating "
            "over the control+evidence graph."
        ),
    },
    {
        "name": "health",
        "description": "Liveness/Readiness probes for OKE.",
    },
]


def customize_openapi(app: FastAPI) -> None:
    """Attach Compliance-specific OpenAPI metadata."""

    app.title = "Sovereign Defence — Compliance Automation Service"
    app.version = "0.1.0"
    app.description = (
        "## Compliance Automation — NIS2, DORA, GDPR, VS-NfD\n\n"
        "Dieser Service automatisiert Compliance-Nachweise fuer die "
        "europaeischen Verteidigungs- und Kritis-Regelwerke. Kontrollen "
        "werden an Nachweise gebunden, diese wiederum an manipulations-"
        "sichere Blockchain-Tabellen in Oracle 26ai. Berichte (NIS2 "
        "Incident Report, DORA ICT Register, GDPR Art.30) werden aus dem "
        "Kontroll-Graphen generiert.\n\n"
        "### Technical\n\n"
        "Controls and evidence live in Oracle 26ai with cryptographic "
        "anchoring via Blockchain Tables. Assessments aggregate status "
        "across tenants (multi-tenant via OLS) and time windows. Report "
        "generation uses Jinja2 templates and pulls from ORDS-exposed "
        "views. Integration with the other four services is through "
        "their respective REST APIs; cross-service queries are joined at "
        "the compliance layer.\n\n"
        "### Consumed by\n\n"
        "Frontend view `ComplianceView` (control matrix + report wizard)."
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

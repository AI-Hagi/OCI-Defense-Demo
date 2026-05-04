"""
graph_query — POSTs to osint-fusion's UC4 ORDS reverse-proxy.

The chat service does not hold OAuth credentials itself. Instead it calls
the existing `/api/uc4/tools/graph_query` route on osint-fusion, which
attaches the bearer + forwards X-OLS-Label-Max. That keeps OLS enforcement
in exactly one place (the ORDS handler) and avoids a second OAuth client.

The LLM gets the entity list trimmed to ≤15 rows so the next-hop prompt
stays small. The full list (and request_id / duration_ms) is preserved in
the trace via the orchestrator for the UI.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

from ..audit import AuditWriter, ols_label_to_int

logger = structlog.get_logger(__name__)

_ALLOWED_PATTERNS = {
    "multi_source_entity",
    "vessel_correlations",
    "actor_correlations",
}


class GraphQueryTool:
    name = "graph_query"
    description = (
        "Fragt den UC4 Property-Graph (Oracle 26ai SQL/PGQ) via ORDS-Tool ab. "
        "Liefert Entitäten, die in mehreren Quellen erwähnt werden — ideal "
        "um Korrelationen zwischen AIS-/Flight-/Doc-Quellen zu finden. "
        "Pattern 'multi_source_entity' liefert kanonische Entitäten mit "
        "≥ min_correlations Quellen-Treffern in den letzten N Stunden. "
        "Antworten sind durch den OLS-Cap der Sitzung begrenzt — Inhalte "
        "über dem Cap sind nicht sichtbar."
    )
    parameters = {
        "pattern": {
            "type": "str",
            "description": (
                "Abfragemuster. Aktuell: 'multi_source_entity' | "
                "'vessel_correlations' | 'actor_correlations'. "
                "Default 'multi_source_entity'."
            ),
            "required": False,
        },
        "hours": {
            "type": "int",
            "description": "Zeitfenster rückwärts in Stunden. Default 72.",
            "required": False,
        },
        "min_correlations": {
            "type": "int",
            "description": "Mindestanzahl Korrelationen pro Entity. Default 2.",
            "required": False,
        },
        "entity_kind": {
            "type": "str",
            "description": (
                "Optionaler Filter auf entity_kind: 'vessel' | 'aircraft' | "
                "'actor' | 'location' | 'satellite' | 'emitter'."
            ),
            "required": False,
        },
    }

    def __init__(
        self,
        http: httpx.AsyncClient,
        proxy_base_url: str,
        audit: AuditWriter,
        ols_cap: str,
    ) -> None:
        self._http = http
        self._proxy_base_url = proxy_base_url.rstrip("/")
        self._audit = audit
        self._ols_cap = ols_cap

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = (args.get("pattern") or "multi_source_entity").lower()
        if pattern not in _ALLOWED_PATTERNS:
            return {"error": f"unknown pattern: {pattern}"}

        body = {
            "pattern": pattern,
            "args": {
                "hours": int(args.get("hours") or 72),
                "min_correlations": int(args.get("min_correlations") or 2),
            },
        }
        if args.get("entity_kind"):
            body["args"]["entity_kind"] = str(args["entity_kind"]).lower()

        url = f"{self._proxy_base_url}/api/uc4/tools/graph_query"
        headers = {
            "Content-Type": "application/json",
            "X-OLS-Label-Max": self._ols_cap,
        }

        out: dict[str, Any] = {"pattern": pattern, "args": body["args"]}
        try:
            resp = await self._http.post(url, json=body, headers=headers)
            payload = resp.json() if resp.headers.get("content-type", "").startswith("application/") else None
            if resp.status_code >= 400:
                out["error"] = f"upstream {resp.status_code}"
                if isinstance(payload, dict):
                    out["detail"] = payload.get("detail") or payload.get("title")
            else:
                # ORDS tool envelope: { request_id, duration_ms, data, ols_cap_applied, ols_cap_label }
                data = payload.get("data") if isinstance(payload, dict) else None
                entities = self._extract_entities(data, kind_filter=args.get("entity_kind"))
                out["count"] = len(entities)
                out["samples"] = entities[:15]
                if isinstance(payload, dict):
                    out["ols_cap_applied"] = payload.get("ols_cap_applied")
                    out["ols_cap_label"] = payload.get("ols_cap_label")
                    out["request_id"] = payload.get("request_id")
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"

        await self._audit.record(
            action="chat_tool_call",
            resource_type="graph_query",
            resource_id=pattern,
            ols_label=ols_label_to_int(self._ols_cap),
            payload={"args": args, "count": out.get("count", 0)},
        )
        return out

    @staticmethod
    def _extract_entities(
        data: Any, kind_filter: Optional[str]
    ) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        raw = data.get("entities")
        if not isinstance(raw, list):
            return []
        kind = kind_filter.lower() if isinstance(kind_filter, str) else None
        out: list[dict[str, Any]] = []
        for e in raw:
            if not isinstance(e, dict):
                continue
            if kind and (e.get("entity_kind") or "").lower() != kind:
                continue
            out.append(
                {
                    "entity_kind": e.get("entity_kind"),
                    "canonical_id": e.get("canonical_id"),
                    "display_name": e.get("display_name"),
                    "corr_count": e.get("corr_count"),
                }
            )
        return out

"""
map_action — purely a relay tool.

The LLM emits structured map-control intents that the frontend executes
locally. This tool does NOT make an upstream call. It validates the action
shape and returns the canonical payload so the orchestrator can:

  1. record an audit row (`chat_tool_call` action='map_action')
  2. forward the payload to the frontend as a dedicated `map_action`
     event (in addition to the standard tool_call/tool_result frames).

Allowed actions (mirrors CLAUDE.md UC4 contract):

  * flyto              { lat, lon, zoom_km? }
  * enable_layer       { layer }
  * disable_layer      { layer }
  * highlight_entities { entity_ids: [str, ...] }

Defensive boundaries:

  * lat/lon range checks
  * layer-name allow-list (sub-set of LayerRegistry, kept here as a constant
    so the backend isn't dependent on the frontend bundle to validate)
  * entity_ids capped at 50

If validation fails, the tool returns `{action: null, error: "..."}` so
the LLM can recover gracefully rather than crashing the loop.
"""
from __future__ import annotations

from typing import Any

import structlog

from ..audit import AuditWriter, ols_label_to_int

logger = structlog.get_logger(__name__)

# Mirrors LayerRegistry names. Keep this in sync with frontend/src/layers.
ALLOWED_LAYERS: frozenset[str] = frozenset(
    {
        "maritime",
        "flights-civil",
        "flights-mil",
        "jamming",
        "ports",
        "tle",
        "sentinel",
        "graph-fusion",
        "doctrine-pins",
    }
)

ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {"flyto", "enable_layer", "disable_layer", "highlight_entities"}
)

MAX_HIGHLIGHT_ENTITIES = 50

# Common LLM mis-names → canonical layer id. Cohere likes to add German
# suffixes like "-Layer" / "-Schicht" or capitalise the first letter; the
# Frontend's LayerRegistry only accepts the lowercase canonical form, so
# we normalise here before validating.
_LAYER_ALIASES: dict[str, str] = {
    "maritim": "maritime",
    "ais": "maritime",
    "ais-stream": "maritime",
    "civil-flights": "flights-civil",
    "mil-flights": "flights-mil",
    "military-flights": "flights-mil",
    "satellites": "tle",
    "satellite": "tle",
    "satelliten": "tle",
    "weather": "sentinel",
    "imagery": "sentinel",
    "doctrine": "doctrine-pins",
    "fusion": "graph-fusion",
}


def _normalize_layer_name(raw: str) -> str:
    """Lowercase + strip common operator/LLM suffixes before allow-list check."""
    s = raw.strip().lower()
    # German + English suffix aliases the operator/LLM might tack on
    for suffix in ("-layer", "_layer", "-schicht", " layer", "-pattern"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return _LAYER_ALIASES.get(s, s)


class MapActionTool:
    name = "map_action"
    description = (
        "Steuert das UC4-Lagebild im Browser des Operators. Wird ausgeführt, "
        "indem der Frontend-Client die Aktion ausführt — der Backend-Aufruf "
        "trägt nur ein Audit-Event ein. Erlaubte Aktionen: 'flyto' (lat, lon, "
        "optional zoom_km), 'enable_layer' / 'disable_layer' (layer-Name), "
        "'highlight_entities' (entity_ids). Ungültige Aktionen werden als "
        "Fehler zurückgegeben — das LLM darf es dann erneut versuchen oder "
        "in der Antwort darauf hinweisen."
    )
    parameters = {
        "action": {
            "type": "str",
            "description": "Aktionstyp: 'flyto' | 'enable_layer' | 'disable_layer' | 'highlight_entities'.",
            "required": True,
        },
        "lat": {"type": "float", "description": "Lat für flyto", "required": False},
        "lon": {"type": "float", "description": "Lon für flyto", "required": False},
        "zoom_km": {
            "type": "float",
            "description": "Optionaler Zoom-Radius in km für flyto (default 200).",
            "required": False,
        },
        "layer": {
            "type": "str",
            "description": (
                "Exakter Layer-Identifier für enable_layer / disable_layer. "
                "Erlaubte Werte (alle lowercase, ohne Suffix): 'maritime', "
                "'flights-civil', 'flights-mil', 'jamming', 'ports', 'tle', "
                "'sentinel', 'graph-fusion', 'doctrine-pins'. Beispiel: "
                "wenn der Operator 'Maritime-Layer' sagt, sende 'maritime'."
            ),
            "required": False,
        },
        "entity_ids": {
            "type": "list",
            "description": "Liste kanonischer IDs für highlight_entities (max 50).",
            "required": False,
        },
    }

    def __init__(self, audit: AuditWriter, ols_cap: str) -> None:
        self._audit = audit
        self._ols_cap = ols_cap

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        action = (args.get("action") or "").lower()
        result = self._validate(action, args)

        await self._audit.record(
            action="chat_tool_call",
            resource_type="map_action",
            resource_id=action or None,
            ols_label=ols_label_to_int(self._ols_cap),
            payload={"args": args, "valid": result.get("error") is None},
        )
        return result

    @staticmethod
    def _validate(action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            return {
                "action": None,
                "error": f"unknown action: {action!r} (allowed: {sorted(ALLOWED_ACTIONS)})",
            }
        if action == "flyto":
            try:
                lat = float(args["lat"])
                lon = float(args["lon"])
            except (KeyError, TypeError, ValueError):
                return {"action": None, "error": "flyto requires numeric lat + lon"}
            if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
                return {"action": None, "error": "flyto: lat/lon out of range"}
            payload: dict[str, Any] = {"action": "flyto", "lat": lat, "lon": lon}
            if args.get("zoom_km") is not None:
                try:
                    z = float(args["zoom_km"])
                    if not (1.0 <= z <= 5000.0):
                        raise ValueError
                    payload["zoom_km"] = z
                except (TypeError, ValueError):
                    return {"action": None, "error": "zoom_km must be 1..5000"}
            return payload

        if action in ("enable_layer", "disable_layer"):
            raw_layer = args.get("layer")
            if not isinstance(raw_layer, str) or not raw_layer:
                return {"action": None, "error": f"{action} requires 'layer'"}
            layer = _normalize_layer_name(raw_layer)
            if layer not in ALLOWED_LAYERS:
                return {
                    "action": None,
                    "error": (
                        f"unknown layer: {raw_layer!r} "
                        f"(allowed: {sorted(ALLOWED_LAYERS)})"
                    ),
                }
            return {"action": action, "layer": layer}

        # highlight_entities
        ids = args.get("entity_ids")
        if not isinstance(ids, list) or not ids:
            return {"action": None, "error": "highlight_entities requires non-empty entity_ids list"}
        cleaned = [str(x) for x in ids if x is not None][:MAX_HIGHLIGHT_ENTITIES]
        if not cleaned:
            return {"action": None, "error": "highlight_entities: no usable ids after cleanup"}
        return {"action": "highlight_entities", "entity_ids": cleaned}

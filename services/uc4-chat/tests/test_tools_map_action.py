"""Validation tests for MapActionTool + integration with the orchestrator."""
from __future__ import annotations

import pytest

from app.audit import AuditWriter
from app.db import DBPool
from app.llm import LlmClient, LlmResponse, LlmToolCall, MockLlmDriver
from app.orchestrator import ChatOrchestrator
from app.settings import Settings
from app.tools.map_action import ALLOWED_ACTIONS, ALLOWED_LAYERS, MapActionTool


class _NoopPool(DBPool):
    def is_available(self) -> bool:  # type: ignore[override]
        return False


def _audit() -> AuditWriter:
    return AuditWriter(tenant_id="T001", pool=_NoopPool())


def _tool() -> MapActionTool:
    return MapActionTool(audit=_audit(), ols_cap="OFFEN")


@pytest.mark.asyncio
async def test_flyto_returns_canonical_payload() -> None:
    out = await _tool().run({"action": "flyto", "lat": 50.1109, "lon": 8.6821})
    assert out == {"action": "flyto", "lat": 50.1109, "lon": 8.6821}


@pytest.mark.asyncio
async def test_flyto_with_zoom_km() -> None:
    out = await _tool().run(
        {"action": "flyto", "lat": 52.5, "lon": 13.4, "zoom_km": 50.0}
    )
    assert out["zoom_km"] == 50.0


@pytest.mark.asyncio
async def test_flyto_rejects_out_of_range_lat() -> None:
    out = await _tool().run({"action": "flyto", "lat": 95.0, "lon": 8.0})
    assert out["action"] is None
    assert "out of range" in out["error"]


@pytest.mark.asyncio
async def test_flyto_rejects_invalid_zoom() -> None:
    out = await _tool().run(
        {"action": "flyto", "lat": 52.0, "lon": 13.0, "zoom_km": 999999.0}
    )
    assert out["action"] is None
    assert "zoom_km" in out["error"]


@pytest.mark.asyncio
async def test_enable_layer_validates_layer_name() -> None:
    ok = await _tool().run({"action": "enable_layer", "layer": "maritime"})
    assert ok == {"action": "enable_layer", "layer": "maritime"}

    bad = await _tool().run({"action": "enable_layer", "layer": "ghost"})
    assert bad["action"] is None
    assert "unknown layer" in bad["error"]

    missing = await _tool().run({"action": "enable_layer"})
    assert missing["action"] is None
    assert "requires 'layer'" in missing["error"]


@pytest.mark.asyncio
async def test_disable_layer_uses_same_allow_list() -> None:
    out = await _tool().run({"action": "disable_layer", "layer": "jamming"})
    assert out == {"action": "disable_layer", "layer": "jamming"}


@pytest.mark.asyncio
async def test_layer_name_normalization_strips_suffix_and_aliases() -> None:
    """LLMs often emit human-display variants like 'Maritime-Layer' or
    'Satellites'. Normalise these to the canonical LayerRegistry id."""
    cases = [
        ("Maritime-Layer", "maritime"),
        ("MARITIM", "maritime"),
        ("ais", "maritime"),
        ("Satellites", "tle"),
        ("Civil-Flights", "flights-civil"),
        ("military-flights", "flights-mil"),
        ("doctrine", "doctrine-pins"),
        ("fusion-Layer", "graph-fusion"),
        ("jamming Layer", "jamming"),
    ]
    for raw, expected in cases:
        out = await _tool().run({"action": "enable_layer", "layer": raw})
        assert out == {"action": "enable_layer", "layer": expected}, f"{raw} → {out}"


@pytest.mark.asyncio
async def test_highlight_entities_caps_at_50_and_strips_none() -> None:
    big = [f"V{i}" for i in range(80)] + [None, None]
    out = await _tool().run({"action": "highlight_entities", "entity_ids": big})
    assert out["action"] == "highlight_entities"
    assert len(out["entity_ids"]) == 50


@pytest.mark.asyncio
async def test_highlight_entities_rejects_empty_list() -> None:
    out = await _tool().run({"action": "highlight_entities", "entity_ids": []})
    assert out["action"] is None
    assert "non-empty" in out["error"]


@pytest.mark.asyncio
async def test_unknown_action_returns_error() -> None:
    out = await _tool().run({"action": "drop_payload"})
    assert out["action"] is None
    assert "unknown action" in out["error"]


def test_allow_lists_are_immutable_frozensets() -> None:
    # Defensive: layer/action allow-lists must not be mutated at runtime.
    assert isinstance(ALLOWED_ACTIONS, frozenset)
    assert isinstance(ALLOWED_LAYERS, frozenset)


# ---------------------------------------------------------------------------
# Orchestrator integration — emits the dedicated `map_action` event.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_orchestrator_emits_map_action_event_on_success() -> None:
    events: list[dict] = []

    async def sink(evt: dict) -> None:
        events.append(evt)

    driver = MockLlmDriver(
        scripted=[
            LlmResponse(
                text=None,
                tool_calls=[
                    LlmToolCall(
                        name="map_action",
                        parameters={"action": "flyto", "lat": 50.1, "lon": 8.7},
                    )
                ],
                model="cohere.command-r-plus",
            ),
            LlmResponse(text="Kamera fliegt nach Frankfurt.", tool_calls=[], model="cohere.command-r-plus"),
        ]
    )
    client = LlmClient(Settings(CHAT_LLM_MODE="mock"), driver=driver)
    orch = ChatOrchestrator(
        llm=client,
        tools={"map_action": _tool()},
        max_hops=5,
        ols_cap="OFFEN",
        tenant_id="T001",
    )
    await orch.run("Zoom auf Frankfurt", [], event_sink=sink)

    types = [e["type"] for e in events]
    assert "map_action" in types
    map_evt = next(e for e in events if e["type"] == "map_action")
    assert map_evt["action"] == "flyto"
    assert map_evt["lat"] == 50.1
    assert map_evt["lon"] == 8.7


@pytest.mark.asyncio
async def test_orchestrator_omits_map_action_event_on_validation_error() -> None:
    """When the tool rejects an action, no map_action frame is emitted —
    the LLM gets the error in the standard tool_result and can recover."""
    events: list[dict] = []

    async def sink(evt: dict) -> None:
        events.append(evt)

    driver = MockLlmDriver(
        scripted=[
            LlmResponse(
                text=None,
                tool_calls=[
                    LlmToolCall(
                        name="map_action",
                        parameters={"action": "flyto", "lat": 999, "lon": 0},
                    )
                ],
                model="cohere.command-r-plus",
            ),
            LlmResponse(text="Konnte Aktion nicht ausführen.", tool_calls=[], model="cohere.command-r-plus"),
        ]
    )
    client = LlmClient(Settings(CHAT_LLM_MODE="mock"), driver=driver)
    orch = ChatOrchestrator(
        llm=client,
        tools={"map_action": _tool()},
        max_hops=5,
        ols_cap="OFFEN",
        tenant_id="T001",
    )
    await orch.run("test", [], event_sink=sink)

    types = [e["type"] for e in events]
    assert "map_action" not in types
    # tool_result is still emitted so the LLM saw the error
    assert types.count("tool_result") == 1

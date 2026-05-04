"""Tool-loop tests for ChatOrchestrator.

Three scenarios:
  1. LLM answers directly, no tool call.
  2. LLM emits one tool call, then answers using its output.
  3. LLM keeps emitting tool calls past max_hops — orchestrator forces a
     final no-tools answer rather than spinning forever.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.llm import LlmClient, LlmResponse, LlmToolCall, LlmToolResult, MockLlmDriver
from app.orchestrator import ChatOrchestrator
from app.settings import Settings


class _StubTool:
    name = "flights_query"
    description = "stub"
    parameters: dict[str, dict[str, Any]] = {
        "kind": {"type": "str", "description": "civil|mil|both", "required": False}
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(args)
        return {"counts": {"civil": 12, "mil": 3}, "kind": args.get("kind", "both")}


def _settings() -> Settings:
    return Settings(CHAT_LLM_MODE="mock", CHAT_MODEL="cohere.command-r-plus")


def _client(scripted: list[LlmResponse]) -> tuple[LlmClient, MockLlmDriver]:
    driver = MockLlmDriver(scripted=scripted)
    return LlmClient(_settings(), driver=driver), driver


@pytest.mark.asyncio
async def test_direct_answer_no_tools() -> None:
    client, driver = _client(
        [LlmResponse(text="Es fliegen aktuell viele zivile Maschinen.", tool_calls=[], model="cohere.command-r-plus")]
    )
    orch = ChatOrchestrator(
        llm=client,
        tools={"flights_query": _StubTool()},
        max_hops=5,
        ols_cap="OFFEN",
        tenant_id="T001",
    )
    result = await orch.run("Wie ist die Lage?", [])
    assert result.answer.startswith("Es fliegen")
    assert result.hops == 0
    assert result.trace == []
    assert len(driver.calls) == 1


@pytest.mark.asyncio
async def test_one_tool_call_then_answer() -> None:
    tool = _StubTool()
    client, driver = _client(
        [
            LlmResponse(
                text=None,
                tool_calls=[LlmToolCall(name="flights_query", parameters={"kind": "mil", "region": "germany"})],
                model="cohere.command-r-plus",
            ),
            LlmResponse(
                text="Aktuell sind 3 militärische Maschinen über Deutschland erfasst.",
                tool_calls=[],
                model="cohere.command-r-plus",
            ),
        ]
    )
    orch = ChatOrchestrator(
        llm=client,
        tools={"flights_query": tool},
        max_hops=5,
        ols_cap="NFD",
        tenant_id="T001",
    )
    result = await orch.run("Welche militärischen Flugzeuge fliegen über Deutschland?", [])
    assert "3 militärische" in result.answer
    assert result.hops == 1
    assert len(result.trace) == 1
    assert result.trace[0].tool == "flights_query"
    assert result.trace[0].args == {"kind": "mil", "region": "germany"}
    assert result.trace[0].error is None
    assert tool.calls == [{"kind": "mil", "region": "germany"}]
    # Second LLM call must include the tool result
    assert driver.calls[1]["tool_results_len"] == 1


@pytest.mark.asyncio
async def test_max_hops_forces_final_answer() -> None:
    """If the LLM keeps calling tools forever, we force a no-tools final."""
    looping_call = LlmResponse(
        text=None,
        tool_calls=[LlmToolCall(name="flights_query", parameters={"kind": "both"})],
        model="cohere.command-r-plus",
    )
    forced_final = LlmResponse(
        text="(zusammengefasst nach max_hops)",
        tool_calls=[],
        model="cohere.command-r-plus",
    )
    client, driver = _client([looping_call, looping_call, forced_final])
    orch = ChatOrchestrator(
        llm=client,
        tools={"flights_query": _StubTool()},
        max_hops=2,
        ols_cap="OFFEN",
        tenant_id="T001",
    )
    result = await orch.run("Lage?", [])
    assert result.hops == 2
    assert result.answer.startswith("(zusammengefasst")
    # Forced call must have force_no_tools=True
    assert driver.calls[-1]["force_no_tools"] is True
    assert len(result.trace) == 2


@pytest.mark.asyncio
async def test_followup_reminder_injected_after_tool_call() -> None:
    """On iter >= 1, the orchestrator must append the original question +
    a SYSTEM reminder to chat_history so Cohere stays focused on the
    current turn instead of drifting into earlier topics or English."""
    tool = _StubTool()
    client, driver = _client(
        [
            LlmResponse(
                text=None,
                tool_calls=[LlmToolCall(name="flights_query", parameters={"kind": "mil"})],
                model="cohere.command-r-plus",
            ),
            LlmResponse(text="6 militärische Maschinen.", tool_calls=[], model="cohere.command-r-plus"),
        ]
    )
    orch = ChatOrchestrator(
        llm=client,
        tools={"flights_query": tool},
        max_hops=5,
        ols_cap="NFD",
        tenant_id="T001",
    )
    await orch.run("Welche militärischen Flugzeuge?", [])

    # First LLM call: bare history (just SYSTEM_PROMPT).
    assert driver.calls[0]["history_len"] == 1
    # Second LLM call: bare history + USER reminder + SYSTEM reminder = 3.
    assert driver.calls[1]["history_len"] == 3


@pytest.mark.asyncio
async def test_unknown_tool_recorded_as_error() -> None:
    client, _ = _client(
        [
            LlmResponse(
                text=None,
                tool_calls=[LlmToolCall(name="ghost_tool", parameters={})],
                model="cohere.command-r-plus",
            ),
            LlmResponse(text="Ohne Tool keine Antwort.", tool_calls=[], model="cohere.command-r-plus"),
        ]
    )
    orch = ChatOrchestrator(
        llm=client,
        tools={"flights_query": _StubTool()},
        max_hops=5,
        ols_cap="OFFEN",
        tenant_id="T001",
    )
    result = await orch.run("Test?", [])
    assert result.hops == 1
    assert len(result.trace) == 1
    assert result.trace[0].error is not None
    assert "unknown tool" in result.trace[0].error

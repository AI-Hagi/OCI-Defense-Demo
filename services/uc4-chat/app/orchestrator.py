"""
Chat orchestrator — runs the Cohere R+ tool-calling loop.

Contract:
  * Caller provides a question + chat history
  * Orchestrator queries the LLM with the registered tools
  * If the LLM emits tool_calls, the orchestrator dispatches them, records
    one audit row per call, then re-queries with the tool outputs attached
  * Hard cap at `max_hops`; on overflow we issue one final no-tools call so
    the LLM is forced to summarise rather than loop forever
  * Returns the final text plus the full trace
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from .llm import LlmClient, LlmResponse, LlmToolCall, LlmToolResult
from .tools.base import Tool, cohere_tool_spec

# Event sink for streaming. Each event is a JSON-serialisable dict —
# the WebSocket endpoint serialises and forwards. None = silent run.
EventSink = Optional[Callable[[dict[str, Any]], Awaitable[None]]]

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
Du bist der UC4-Lagebild-Assistent der Sovereign Defence Plattform.

Sprache (HART):
  - Antworte AUSSCHLIESSLICH auf Deutsch. Auch wenn frühere Antworten in der
    Konversation auf Englisch waren — die nächste Antwort ist auf Deutsch.
  - Vermeide englische Floskeln in der Endantwort.

Fokus (HART):
  - Beantworte AUSSCHLIESSLICH die letzte Frage des Operators (USER:).
  - Verwende ausschließlich die in dieser Runde aufgerufenen Tools und deren
    Ergebnisse. Bezüge zu früheren Konversations-Turns sind nur erlaubt,
    wenn der Operator sie ausdrücklich anfordert ("und welche davon …",
    "wie eben gefragt …").
  - Wenn ein Tool eine leere Liste oder einen Fehler zurückgibt, sage das
    deutlich. Erfinde keine Flugzeuge, Schiffe, Korrelationen oder Quellen.

Aufgabe:
  - Themenbereiche: Luftlage, Maritime Lage, EMS-/Jamming-Lage, Korrelationen
    und Lagebild-Steuerung.
  - Nenne Counts/Sample-Anzahlen aus Tool-Ergebnissen wörtlich.
  - Nenne Quellen und Zeitstempel, wo verfügbar.

Plattform-Disziplin (HART, nicht verhandelbar):
  - Diese Plattform ist ein Daten-, KI- und Compliance-Layer.
  - Du gibst KEINE kinetischen Empfehlungen, KEINE C2-Anweisungen, KEINE
    Feuerleit-Hinweise. Wenn der Operator danach fragt, weise höflich auf
    den Plattform-Scope hin und biete an, stattdessen Lage-/Korrelations-
    fragen zu beantworten.

Klassifizierung:
  - Aktueller OLS-Cap der Sitzung: {ols_cap}.
  - Du siehst nur Daten bis zu diesem Cap. Markiere keine Inhalte als höher
    klassifiziert als der Cap.
"""

# Reminder injected as an extra SYSTEM turn right before each follow-up
# iteration (after tool results are available). Keeps the model focused on
# the current question and on German output even when the prior chat
# history contained other topics or English answers.
_FOLLOWUP_REMINDER = (
    "Antworte jetzt auf Deutsch und beziehe dich AUSSCHLIESSLICH auf die "
    "letzte Operator-Frage und die direkt darauf folgenden Tool-Ergebnisse. "
    "Frühere Konversations-Turns sind irrelevant, falls der Operator sie "
    "nicht ausdrücklich anspricht."
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(USER|CHATBOT|SYSTEM)$")
    message: str


@dataclass
class ToolTraceEntry:
    tool: str
    args: dict[str, Any]
    duration_ms: float
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class OrchestratorResult:
    answer: str
    model: str
    hops: int
    trace: list[ToolTraceEntry]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class ChatOrchestrator:
    def __init__(
        self,
        *,
        llm: LlmClient,
        tools: dict[str, Tool],
        max_hops: int,
        ols_cap: str,
        tenant_id: str,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._max_hops = max_hops
        self._ols_cap = ols_cap
        self._tenant_id = tenant_id

    async def run(
        self,
        question: str,
        history: list[ChatTurn],
        event_sink: EventSink = None,
    ) -> OrchestratorResult:
        chat_history = self._build_history(history)
        tool_specs = [cohere_tool_spec(t) for t in self._tools.values()]
        trace: list[ToolTraceEntry] = []

        message = question
        tool_results: list[LlmToolResult] = []
        last_model = self._llm._settings.chat_model  # noqa: SLF001 — tracking only

        await _emit(event_sink, {"type": "started", "ols_cap": self._ols_cap})

        for hop in range(self._max_hops):
            # Iter 1+: Cohere convention is `message=""` + tool_results in
            # the body. To prevent the model from drifting into earlier
            # conversation turns or English, append the original question
            # to history as the latest USER turn AND inject a SYSTEM
            # reminder right before the model decides.
            iter_history = chat_history
            if hop > 0:
                iter_history = list(chat_history) + [
                    {"role": "USER", "message": question},
                    {"role": "SYSTEM", "message": _FOLLOWUP_REMINDER},
                ]
            response = await self._llm.chat(
                message=message,
                history=iter_history,
                tools=tool_specs,
                tool_results=tool_results,
            )
            last_model = response.model
            if not response.tool_calls:
                await _emit(
                    event_sink,
                    {
                        "type": "answer",
                        "text": response.text or "",
                        "model": response.model,
                        "hops": hop,
                    },
                )
                return OrchestratorResult(
                    answer=response.text or "",
                    model=response.model,
                    hops=hop,
                    trace=trace,
                )

            tool_results = []
            for call in response.tool_calls:
                await _emit(
                    event_sink,
                    {
                        "type": "tool_call",
                        "tool": call.name,
                        "args": call.parameters,
                        "hop": hop,
                    },
                )
                entry, result = await self._dispatch(call)
                trace.append(entry)
                tool_results.append(result)
                await _emit(
                    event_sink,
                    {
                        "type": "tool_result",
                        "tool": entry.tool,
                        "ok": entry.error is None,
                        "duration_ms": entry.duration_ms,
                        "error": entry.error,
                        "summary": _summarise_output(entry.output),
                    },
                )
                # map_action results carry a frontend-executable payload —
                # forward it as a dedicated event so the UI doesn't have to
                # reverse-engineer it from the generic tool_result shape.
                if (
                    entry.tool == "map_action"
                    and entry.error is None
                    and isinstance(entry.output, dict)
                    and entry.output.get("action")
                ):
                    await _emit(
                        event_sink,
                        {"type": "map_action", **entry.output},
                    )

            # On the next hop the LLM gets only tool_results, not a fresh user
            # message. Cohere's contract: keep `message` empty when forwarding
            # tool outputs.
            message = ""

        # Hard cap — force a final no-tools answer so we never return an empty
        # body to the caller. Inject the same focus-reminder so the forced
        # answer is also in German and on-topic.
        forced_history = list(chat_history) + [
            {"role": "USER", "message": question},
            {"role": "SYSTEM", "message": _FOLLOWUP_REMINDER},
        ]
        forced = await self._force_final_answer(
            forced_history, tool_specs, tool_results
        )
        answer = forced.text or "(keine Antwort generiert)"
        await _emit(
            event_sink,
            {
                "type": "answer",
                "text": answer,
                "model": forced.model or last_model,
                "hops": self._max_hops,
                "forced": True,
            },
        )
        return OrchestratorResult(
            answer=answer,
            model=forced.model or last_model,
            hops=self._max_hops,
            trace=trace,
        )

    # ------------------------------------------------------------------
    async def _dispatch(
        self, call: LlmToolCall
    ) -> tuple[ToolTraceEntry, LlmToolResult]:
        tool = self._tools.get(call.name)
        started = time.perf_counter()
        if tool is None:
            error = f"unknown tool: {call.name}"
            entry = ToolTraceEntry(
                tool=call.name,
                args=call.parameters,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error=error,
            )
            return entry, LlmToolResult(call=call, output={"error": error})

        try:
            output = await tool.run(call.parameters)
            entry = ToolTraceEntry(
                tool=call.name,
                args=call.parameters,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                output=output,
            )
            return entry, LlmToolResult(call=call, output=output)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("orchestrator.tool_failed name=%s", call.name)
            err = f"{type(exc).__name__}: {exc}"
            entry = ToolTraceEntry(
                tool=call.name,
                args=call.parameters,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error=err,
            )
            return entry, LlmToolResult(call=call, output={"error": err})

    async def _force_final_answer(
        self,
        chat_history: list[dict[str, Any]],
        tool_specs: list[dict[str, Any]],
        tool_results: list[LlmToolResult],
    ) -> LlmResponse:
        return await self._llm.chat(
            message="",
            history=chat_history,
            tools=tool_specs,
            tool_results=tool_results,
            force_no_tools=True,
        )

    def _build_history(self, history: list[ChatTurn]) -> list[dict[str, Any]]:
        system = _SYSTEM_PROMPT.format(ols_cap=self._ols_cap)
        chat: list[dict[str, Any]] = [{"role": "SYSTEM", "message": system}]
        for turn in history:
            chat.append({"role": turn.role, "message": turn.message})
        return chat


async def _emit(sink: EventSink, event: dict[str, Any]) -> None:
    if sink is None:
        return
    try:
        await sink(event)
    except Exception:  # pragma: no cover — never let the sink crash the loop
        logger.exception("orchestrator.event_sink_failed event_type=%s", event.get("type"))


def _summarise_output(output: dict[str, Any]) -> dict[str, Any]:
    """Trim tool output to a UI-friendly shape: counts + short keys only.

    Each tool may use slightly different shape names (`counts` vs `buckets`
    vs `count`) — forward whatever's relevant so the frontend's tool-card
    has something concrete to show.
    """
    if not isinstance(output, dict):
        return {"value": str(output)[:200]}
    summary: dict[str, Any] = {}
    for key in (
        "counts", "buckets", "count", "total", "kind", "pattern",
        "bbox", "window_seconds", "errors", "error", "request_id",
        "ols_cap_label",
    ):
        if key in output:
            summary[key] = output[key]
    samples = output.get("samples")
    if isinstance(samples, list):
        summary["sample_count"] = len(samples)
    return summary

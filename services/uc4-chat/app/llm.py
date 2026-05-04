"""
LLM client wrapper.

Three modes:
  * 'oci'   — OCI Generative AI Inference. Two providers wired:
                - Cohere Command R+ family   → CohereChatRequest
                - Meta Llama 3.x family      → GenericChatRequest
              Model is selected per-call from the model_id prefix.
              Falls back to CHAT_FALLBACK_MODEL on transient errors.
  * 'mock'  — deterministic scripted responses for tests.

The wrapper hides the OCI SDK shape behind a tiny `chat()` API so unit tests
don't need the SDK installed.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .settings import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public LLM exchange shape
# ---------------------------------------------------------------------------
@dataclass
class LlmToolCall:
    name: str
    parameters: dict[str, Any]
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class LlmResponse:
    text: Optional[str]
    tool_calls: list[LlmToolCall]
    model: str


@dataclass
class LlmToolResult:
    call: LlmToolCall
    output: dict[str, Any]


# ---------------------------------------------------------------------------
# Mock driver — used in tests via CHAT_LLM_MODE=mock
# ---------------------------------------------------------------------------
class MockLlmDriver:
    """Yields scripted responses in order. After the script runs out, returns
    a canned final-text response so loops always terminate.
    """

    def __init__(
        self,
        scripted: Optional[list[LlmResponse]] = None,
        fallback_text: str = "(mock) keine weiteren Aktionen.",
    ) -> None:
        self._scripted = list(scripted or [])
        self._fallback_text = fallback_text
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_results: list[LlmToolResult],
        model: str,
        force_no_tools: bool,
    ) -> LlmResponse:
        self.calls.append(
            {
                "message": message,
                "history_len": len(history),
                "tool_results_len": len(tool_results),
                "force_no_tools": force_no_tools,
                "model": model,
            }
        )
        if self._scripted:
            return self._scripted.pop(0)
        return LlmResponse(text=self._fallback_text, tool_calls=[], model=model)


LlmDriver = Callable[..., LlmResponse]


# ---------------------------------------------------------------------------
# OCI auth + client — shared between Cohere and Llama drivers.
# ---------------------------------------------------------------------------
def _build_oci_client(settings: Settings):  # type: ignore[no-untyped-def]
    import oci  # type: ignore
    from oci.generative_ai_inference import GenerativeAiInferenceClient

    # Three-tier auth fallback so the same image runs in OKE, on Container
    # Instances / Functions, and on a developer laptop:
    #   1) OKE Workload Identity — pods authenticated via the SA-mounted
    #      projected token at /var/run/secrets/oci.oraclecloud.com/...
    #   2) Resource Principal — Container Instances + Functions, picks up
    #      OCI_RESOURCE_PRINCIPAL_* env vars
    #   3) Local ~/.oci/config — last-resort dev-laptop path
    signer = None
    last_exc: Exception | None = None
    try:
        signer = oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
    except Exception as exc:
        last_exc = exc
    if signer is None:
        try:
            signer = oci.auth.signers.get_resource_principals_signer()
        except Exception as exc:
            last_exc = exc
    if signer is not None:
        return GenerativeAiInferenceClient(
            config={"region": settings.oci_region}, signer=signer
        )
    try:
        return GenerativeAiInferenceClient(config=oci.config.from_file())
    except Exception as cfg_exc:
        raise RuntimeError(
            "uc4-chat: no OCI auth available — "
            f"workload-identity/resource-principal failed ({last_exc!r}); "
            f"~/.oci/config fallback failed ({cfg_exc!r})"
        ) from cfg_exc


# ---------------------------------------------------------------------------
# Cohere R+ driver — uses CohereChatRequest with native tool-calling support.
# Used when model_id starts with `cohere.`. Requires either OnDemand support
# in the tenancy or a Dedicated AI Cluster + endpoint OCID (not wired today).
# ---------------------------------------------------------------------------
def _build_cohere_driver(client, compartment_id: str) -> LlmDriver:  # type: ignore[no-untyped-def]
    from oci.generative_ai_inference.models import (
        ChatDetails,
        CohereChatRequest,
        CohereTool,
        CohereParameterDefinition,
        CohereToolResult,
        CohereToolCall,
        OnDemandServingMode,
    )

    def _to_cohere_tool(spec: dict[str, Any]) -> CohereTool:
        params = {
            pname: CohereParameterDefinition(
                description=p.get("description", ""),
                type=p.get("type", "str"),
                is_required=bool(p.get("required", False)),
            )
            for pname, p in spec.get("parameter_definitions", {}).items()
        }
        return CohereTool(
            name=spec["name"],
            description=spec["description"],
            parameter_definitions=params,
        )

    def driver(
        *,
        message: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_results: list[LlmToolResult],
        model: str,
        force_no_tools: bool,
    ) -> LlmResponse:
        cohere_tools = [] if force_no_tools else [_to_cohere_tool(t) for t in tools]
        cohere_tool_results = [
            CohereToolResult(
                call=CohereToolCall(name=tr.call.name, parameters=tr.call.parameters),
                outputs=[tr.output],
            )
            for tr in tool_results
        ]
        chat_request = CohereChatRequest(
            message=message,
            chat_history=history,
            tools=cohere_tools or None,
            tool_results=cohere_tool_results or None,
            max_tokens=1500,
            temperature=0.2,
        )
        details = ChatDetails(
            compartment_id=compartment_id,
            serving_mode=OnDemandServingMode(model_id=model),
            chat_request=chat_request,
        )
        resp = client.chat(details)
        cohere_resp = getattr(resp.data, "chat_response", None) or resp.data
        text = getattr(cohere_resp, "text", None)
        raw_calls = getattr(cohere_resp, "tool_calls", None) or []
        tool_calls = [
            LlmToolCall(name=tc.name, parameters=dict(tc.parameters or {}))
            for tc in raw_calls
        ]
        return LlmResponse(text=text, tool_calls=tool_calls, model=model)

    return driver


# ---------------------------------------------------------------------------
# Llama driver — uses GenericChatRequest with OpenAI-style tools/messages.
# Used when model_id starts with `meta.` (Llama 3.x in eu-frankfurt-1 is the
# default OnDemand path for this tenancy until the Cohere R+ Dedicated
# Cluster's LARGE_COHERE-Limit-SR is approved).
#
# The OCI tool-call shape is OpenAI-compatible: each `Message` has an optional
# `tool_calls` list; tool outputs are sent back as Messages with role='tool'.
# ---------------------------------------------------------------------------
def _build_llama_driver(client, compartment_id: str) -> LlmDriver:  # type: ignore[no-untyped-def]
    import json

    from oci.generative_ai_inference.models import (
        ChatDetails,
        GenericChatRequest,
        OnDemandServingMode,
    )
    # The exact class names for the message/tool-call/function-definition
    # vary across SDK minor versions. We probe a handful of plausible names
    # and fall back to dict literals if none of them are exposed; OCI's
    # serialiser accepts plain dicts for these polymorphic shapes.
    try:
        from oci.generative_ai_inference.models import (
            UserMessage, AssistantMessage, SystemMessage, ToolMessage,
        )
        _has_typed_messages = True
    except ImportError:  # pragma: no cover — SDK fallback path
        UserMessage = AssistantMessage = SystemMessage = ToolMessage = None  # type: ignore
        _has_typed_messages = False

    def _to_llama_tool(spec: dict[str, Any]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for pname, p in spec.get("parameter_definitions", {}).items():
            properties[pname] = {
                "type": _llama_type(p.get("type", "str")),
                "description": p.get("description", ""),
            }
            if p.get("required"):
                required.append(pname)
        return {
            "type": "FUNCTION",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _build_messages(
        message: str,
        history: list[dict[str, Any]],
        tool_results: list[LlmToolResult],
    ) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        # Convert orchestrator's Cohere-style history (role: SYSTEM/USER/CHATBOT)
        # into Llama messages (system/user/assistant).
        for turn in history:
            role = (turn.get("role") or "").upper()
            content = turn.get("message") or ""
            if role == "SYSTEM":
                msgs.append({"role": "SYSTEM", "content": [{"type": "TEXT", "text": content}]})
            elif role == "USER":
                msgs.append({"role": "USER", "content": [{"type": "TEXT", "text": content}]})
            elif role == "CHATBOT" or role == "ASSISTANT":
                msgs.append({"role": "ASSISTANT", "content": [{"type": "TEXT", "text": content}]})
        if tool_results:
            # Replay the prior assistant turn that issued these tool calls,
            # then emit one TOOL message per result.
            assistant_calls = [
                {
                    "id": tr.call.call_id,
                    "type": "FUNCTION",
                    "function": {
                        "name": tr.call.name,
                        "arguments": json.dumps(tr.call.parameters),
                    },
                }
                for tr in tool_results
            ]
            msgs.append(
                {
                    "role": "ASSISTANT",
                    "content": [],
                    "tool_calls": assistant_calls,
                }
            )
            for tr in tool_results:
                msgs.append(
                    {
                        "role": "TOOL",
                        "tool_call_id": tr.call.call_id,
                        "content": [
                            {"type": "TEXT", "text": json.dumps(tr.output, default=str)}
                        ],
                    }
                )
        if message:
            msgs.append({"role": "USER", "content": [{"type": "TEXT", "text": message}]})
        return msgs

    def driver(
        *,
        message: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_results: list[LlmToolResult],
        model: str,
        force_no_tools: bool,
    ) -> LlmResponse:
        llama_tools = [] if force_no_tools else [_to_llama_tool(t) for t in tools]
        msgs = _build_messages(message, history, tool_results)
        chat_request = GenericChatRequest(
            messages=msgs,
            tools=llama_tools or None,
            max_tokens=1500,
            temperature=0.2,
            top_p=0.9,
        )
        details = ChatDetails(
            compartment_id=compartment_id,
            serving_mode=OnDemandServingMode(model_id=model),
            chat_request=chat_request,
        )
        resp = client.chat(details)
        return _parse_llama_response(resp, model)

    return driver


def _llama_type(t: str) -> str:
    """Map our internal type vocabulary to JSON-schema types for Llama tools."""
    return {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "object": "object",
    }.get(t, "string")


def _parse_llama_response(resp: Any, model: str) -> LlmResponse:
    """Extract text + tool_calls from an OCI Generative AI Llama response.

    The exact response shape varies across SDK minor versions. We poke at the
    common attribute paths and fall back to nothing rather than raising —
    that lets the orchestrator emit an empty answer instead of a 500.
    """
    import json

    chat_response = getattr(resp.data, "chat_response", None) or resp.data
    choices = getattr(chat_response, "choices", None) or []
    if not choices:
        return LlmResponse(text=None, tool_calls=[], model=model)

    msg = getattr(choices[0], "message", None)
    if msg is None:
        return LlmResponse(text=None, tool_calls=[], model=model)

    text: Optional[str] = None
    contents = getattr(msg, "content", None) or []
    for block in contents:
        block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        block_text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if (block_type or "").upper() in {"TEXT", "STRING"} and block_text:
            text = (text or "") + block_text

    tool_calls: list[LlmToolCall] = []
    raw_calls = getattr(msg, "tool_calls", None) or []
    for tc in raw_calls:
        fn = getattr(tc, "function", None)
        if fn is None and isinstance(tc, dict):
            fn = tc.get("function")
        if fn is None:
            continue
        name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
        args_raw = getattr(fn, "arguments", None) or (fn.get("arguments") if isinstance(fn, dict) else None)
        if not name:
            continue
        try:
            params = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except (TypeError, ValueError):
            params = {}
        call_id = (
            getattr(tc, "id", None)
            or (tc.get("id") if isinstance(tc, dict) else None)
            or uuid.uuid4().hex[:12]
        )
        tool_calls.append(LlmToolCall(name=name, parameters=dict(params), call_id=call_id))

    return LlmResponse(text=text, tool_calls=tool_calls, model=model)


# ---------------------------------------------------------------------------
# Provider selection — picks the driver based on model_id prefix.
# ---------------------------------------------------------------------------
def _provider_for_model(model: str) -> str:
    if model.startswith("cohere."):
        return "cohere"
    return "llama"  # meta.* and anything else routes to the generic Llama driver


def _build_oci_drivers(settings: Settings) -> dict[str, LlmDriver]:
    """Build one driver per provider, sharing a single auth'd client."""
    if not settings.oci_compartment_ocid:
        raise RuntimeError(
            "OCI_COMPARTMENT_OCID must be set when CHAT_LLM_MODE=oci"
        )
    client = _build_oci_client(settings)
    return {
        "cohere": _build_cohere_driver(client, settings.oci_compartment_ocid),
        "llama": _build_llama_driver(client, settings.oci_compartment_ocid),
    }


# ---------------------------------------------------------------------------
# Public client — the orchestrator's only entry point.
# ---------------------------------------------------------------------------
class LlmClient:
    def __init__(
        self,
        settings: Settings,
        driver: Optional[LlmDriver] = None,
        fallback_driver: Optional[LlmDriver] = None,
    ) -> None:
        self._settings = settings
        # Test-injected drivers bypass provider selection entirely.
        self._test_driver = driver
        self._test_fallback_driver = fallback_driver
        self._oci_drivers: Optional[dict[str, LlmDriver]] = None

    def _driver_for(self, model: str) -> LlmDriver:
        if self._test_driver is not None:
            return self._test_driver
        if self._settings.chat_llm_mode == "mock":
            self._test_driver = MockLlmDriver()
            return self._test_driver
        if self._oci_drivers is None:
            self._oci_drivers = _build_oci_drivers(self._settings)
        return self._oci_drivers[_provider_for_model(model)]

    async def chat(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_results: list[LlmToolResult],
        force_no_tools: bool = False,
    ) -> LlmResponse:
        primary_model = self._settings.chat_model
        try:
            return self._driver_for(primary_model)(
                message=message,
                history=history,
                tools=tools,
                tool_results=tool_results,
                model=primary_model,
                force_no_tools=force_no_tools,
            )
        except Exception:
            logger.exception(
                "llm.primary_failed model=%s — trying fallback", primary_model
            )
            fallback_model = self._settings.chat_fallback_model
            if self._test_fallback_driver is not None:
                fb = self._test_fallback_driver
            else:
                try:
                    fb = self._driver_for(fallback_model)
                except Exception:
                    raise
            return fb(
                message=message,
                history=history,
                tools=tools,
                tool_results=tool_results,
                model=fallback_model,
                force_no_tools=force_no_tools,
            )

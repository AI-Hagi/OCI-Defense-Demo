"""
LLM client wrapper.

Three modes:
  * 'oci'   — OCI Generative AI Inference, Cohere Command R+ tool-calling.
              Falls back to CHAT_FALLBACK_MODEL on transient 5xx.
  * 'mock'  — deterministic scripted responses for tests. The orchestrator
              treats both modes identically.

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
            }
        )
        if self._scripted:
            return self._scripted.pop(0)
        return LlmResponse(text=self._fallback_text, tool_calls=[], model=model)


# Type for a swappable driver — used by tests. Real OCI calls are also
# wrapped through this signature so the orchestrator code-path is identical.
LlmDriver = Callable[..., LlmResponse]


# ---------------------------------------------------------------------------
# OCI driver — built lazily so importing the module works without oci-sdk.
# ---------------------------------------------------------------------------
def _build_oci_driver(settings: Settings) -> LlmDriver:
    """Return a closure that talks to OCI Generative AI Inference."""
    import oci  # type: ignore
    from oci.generative_ai_inference import GenerativeAiInferenceClient
    from oci.generative_ai_inference.models import (
        ChatDetails,
        CohereChatRequest,
        CohereTool,
        CohereParameterDefinition,
        CohereToolResult,
        CohereToolCall,
        OnDemandServingMode,
    )

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
    except Exception as exc:  # OCI_RESOURCE_PRINCIPAL_VERSION-style errors
        last_exc = exc
    if signer is None:
        try:
            signer = oci.auth.signers.get_resource_principals_signer()
        except Exception as exc:
            last_exc = exc
    if signer is not None:
        client = GenerativeAiInferenceClient(
            config={"region": settings.oci_region}, signer=signer
        )
    else:
        try:
            client = GenerativeAiInferenceClient(config=oci.config.from_file())
        except Exception as cfg_exc:
            raise RuntimeError(
                "uc4-chat: no OCI auth available — "
                f"workload-identity/resource-principal failed ({last_exc!r}); "
                f"~/.oci/config fallback failed ({cfg_exc!r})"
            ) from cfg_exc

    if not settings.oci_compartment_ocid:
        raise RuntimeError(
            "OCI_COMPARTMENT_OCID must be set when CHAT_LLM_MODE=oci"
        )
    compartment_id = settings.oci_compartment_ocid

    def _to_cohere_tool(spec: dict[str, Any]) -> CohereTool:
        params = {
            pname: CohereParameterDefinition(
                description=p.get("description", ""),
                type=p.get("type", "str"),
                is_required=bool(p.get("required", False)),
            )
            for pname, p in spec["parameter_definitions"].items()
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
        self._driver = driver
        self._fallback_driver = fallback_driver

    def _get_driver(self) -> LlmDriver:
        if self._driver is not None:
            return self._driver
        if self._settings.chat_llm_mode == "mock":
            self._driver = MockLlmDriver()
            return self._driver
        self._driver = _build_oci_driver(self._settings)
        return self._driver

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
            return self._get_driver()(
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
            if self._fallback_driver is None and self._settings.chat_llm_mode == "oci":
                # Reuse the same OCI client; only model_id changes.
                self._fallback_driver = self._get_driver()
            if self._fallback_driver is None:
                raise
            return self._fallback_driver(
                message=message,
                history=history,
                tools=tools,
                tool_results=tool_results,
                model=fallback_model,
                force_no_tools=force_no_tools,
            )

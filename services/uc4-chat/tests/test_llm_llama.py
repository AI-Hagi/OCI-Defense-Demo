"""Tests for the Llama driver path in app/llm.py.

Covers the two non-trivial pieces:
  * _parse_llama_response  — extract text + tool_calls from a synthesized
    OCI Generative AI response object that mirrors the SDK shape.
  * _provider_for_model    — model_id → driver routing.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.llm import (
    LlmToolCall,
    _llama_type,
    _parse_llama_response,
    _provider_for_model,
)


def test_provider_for_model_routes_cohere_and_llama() -> None:
    assert _provider_for_model("cohere.command-r-plus") == "cohere"
    assert _provider_for_model("cohere.command-r-08-2024") == "cohere"
    assert _provider_for_model("meta.llama-3.3-70b-instruct") == "llama"
    assert _provider_for_model("meta.llama-3.1-70b-instruct") == "llama"
    # Unknown / future models default to llama (generic OpenAI-style)
    assert _provider_for_model("xai.grok-2") == "llama"
    assert _provider_for_model("") == "llama"


def test_llama_type_maps_internal_vocabulary() -> None:
    assert _llama_type("str") == "string"
    assert _llama_type("int") == "integer"
    assert _llama_type("float") == "number"
    assert _llama_type("bool") == "boolean"
    assert _llama_type("list") == "array"
    assert _llama_type("object") == "object"
    # Unknown type degrades to string rather than raising
    assert _llama_type("ufo") == "string"


# ---------------------------------------------------------------------------
# _parse_llama_response — synthesize the OCI SDK shape.
# ---------------------------------------------------------------------------
def _wrap(chat_response: SimpleNamespace) -> SimpleNamespace:
    """Mirror the OCI SDK return value: response.data.chat_response.choices[...]"""
    return SimpleNamespace(data=SimpleNamespace(chat_response=chat_response))


def test_parse_text_only_response() -> None:
    chat = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[SimpleNamespace(type="TEXT", text="Drei militärische Maschinen.")],
                    tool_calls=None,
                )
            )
        ]
    )
    out = _parse_llama_response(_wrap(chat), "meta.llama-3.3-70b-instruct")
    assert out.text == "Drei militärische Maschinen."
    assert out.tool_calls == []
    assert out.model == "meta.llama-3.3-70b-instruct"


def test_parse_response_with_one_tool_call() -> None:
    chat = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[],
                    tool_calls=[
                        SimpleNamespace(
                            id="call-001",
                            function=SimpleNamespace(
                                name="flights_query",
                                arguments=json.dumps({"kind": "mil", "region": "germany"}),
                            ),
                        )
                    ],
                )
            )
        ]
    )
    out = _parse_llama_response(_wrap(chat), "meta.llama-3.3-70b-instruct")
    assert out.text is None
    assert len(out.tool_calls) == 1
    call = out.tool_calls[0]
    assert call.name == "flights_query"
    assert call.parameters == {"kind": "mil", "region": "germany"}
    assert call.call_id == "call-001"


def test_parse_response_with_multiple_tool_calls_and_dict_function() -> None:
    """Some SDK builds expose `function` as a dict instead of a typed object —
    the parser must accept both shapes."""
    chat = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[SimpleNamespace(type="TEXT", text="OK")],
                    tool_calls=[
                        {"id": "c-A", "function": {"name": "ais_query", "arguments": "{}"}},
                        SimpleNamespace(
                            id="c-B",
                            function={"name": "jamming_query", "arguments": json.dumps({"region": "baltic"})},
                        ),
                    ],
                )
            )
        ]
    )
    out = _parse_llama_response(_wrap(chat), "meta.llama-3.3-70b-instruct")
    assert out.text == "OK"
    names = [c.name for c in out.tool_calls]
    assert names == ["ais_query", "jamming_query"]
    assert out.tool_calls[1].parameters == {"region": "baltic"}


def test_parse_handles_missing_choices_gracefully() -> None:
    out = _parse_llama_response(
        _wrap(SimpleNamespace(choices=None)), "meta.llama-3.3-70b-instruct"
    )
    assert out.text is None
    assert out.tool_calls == []


def test_parse_skips_tool_calls_with_garbage_arguments() -> None:
    chat = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=[],
                    tool_calls=[
                        SimpleNamespace(
                            id="bad",
                            function=SimpleNamespace(
                                name="flights_query",
                                arguments="not-json",
                            ),
                        ),
                        SimpleNamespace(
                            id="missing-name",
                            function=SimpleNamespace(name=None, arguments="{}"),
                        ),
                    ],
                )
            )
        ]
    )
    out = _parse_llama_response(_wrap(chat), "meta.llama-3.3-70b-instruct")
    # First call survives with empty params; second is dropped (no name).
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "flights_query"
    assert out.tool_calls[0].parameters == {}


def test_llm_tool_call_round_trip_dataclass() -> None:
    """Sanity: the LlmToolCall dataclass auto-generates a call_id when omitted."""
    a = LlmToolCall(name="x", parameters={})
    b = LlmToolCall(name="x", parameters={})
    assert a.call_id != b.call_id
    assert len(a.call_id) == 12

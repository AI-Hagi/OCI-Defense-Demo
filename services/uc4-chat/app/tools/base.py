"""
Tool protocol + parameter schemas.

A Tool exposes:
  * `name` / `description` / `parameters` → for the Cohere R+ tool spec
  * `run(args)` → executes the upstream call, returns a dict the LLM consumes

The orchestrator wraps every `run` call with timing + audit so individual
tools don't need to repeat that boilerplate.
"""
from __future__ import annotations

from typing import Any, Protocol


class ToolParameter(Protocol):
    name: str
    type: str  # 'str' | 'float' | 'int' | 'bool' | 'object'
    description: str
    required: bool


class Tool(Protocol):
    """Run-style tool that the chat orchestrator can dispatch."""

    name: str
    description: str
    # JSON-schema-ish parameter map: {param_name: {"type": "...", "description": "...", "required": bool}}
    parameters: dict[str, dict[str, Any]]

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool. May raise — orchestrator catches + records."""
        ...


def cohere_tool_spec(tool: Tool) -> dict[str, Any]:
    """Render a Tool as a Cohere R+ tool definition (parameter_definitions)."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameter_definitions": {
            pname: {
                "description": pspec.get("description", ""),
                "type": pspec.get("type", "str"),
                "required": pspec.get("required", False),
            }
            for pname, pspec in tool.parameters.items()
        },
    }

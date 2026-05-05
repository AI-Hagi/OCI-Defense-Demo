"""Tool registry — assembled per-request so each chat call gets fresh
upstream-context (httpx client, OLS cap, audit writer).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from .ais import AisQueryTool
from .base import Tool
from .flights import FlightsQueryTool
from .graph import GraphQueryTool
from .jamming import JammingQueryTool
from .map_action import MapActionTool

if TYPE_CHECKING:  # pragma: no cover
    from ..audit import AuditWriter
    from ..settings import Settings


def build_tool_registry(
    *,
    http: httpx.AsyncClient,
    settings: "Settings",
    audit: "AuditWriter",
    ols_cap: str,
) -> dict[str, Tool]:
    """Step 4: five tools wired (flights/jamming via HTTP, ais via WS,
    graph via the osint-fusion ORDS reverse-proxy, map_action as a frontend
    relay).
    """
    flights = FlightsQueryTool(
        http=http,
        base_url=settings.flights_proxy_url,
        audit=audit,
        ols_cap=ols_cap,
    )
    jamming = JammingQueryTool(
        http=http,
        base_url=settings.jamming_poller_url,
        audit=audit,
        ols_cap=ols_cap,
    )
    ais = AisQueryTool(
        base_url=settings.ais_multiplexer_url,
        audit=audit,
        ols_cap=ols_cap,
    )
    graph = GraphQueryTool(
        http=http,
        proxy_base_url=settings.osint_fusion_url,
        audit=audit,
        ols_cap=ols_cap,
    )
    map_action = MapActionTool(audit=audit, ols_cap=ols_cap)
    return {t.name: t for t in (flights, jamming, ais, graph, map_action)}


__all__ = ["Tool", "build_tool_registry"]

"""
ais_query — opens a short-lived WebSocket subscription to ais-multiplexer
and returns the first batch of vessel updates.

ais-multiplexer doesn't expose an HTTP snapshot, so the chat service mirrors
the frontend pattern: connect to /ws/maritime?bbox=..., collect for a small
time-window or until N messages arrive, close. The response shape matches
the other tools (counts + samples).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional, Protocol

import structlog

from ..audit import AuditWriter, ols_label_to_int

logger = structlog.get_logger(__name__)

_BALTIC_BBOX = {"bbox_s": 53.0, "bbox_w": 13.0, "bbox_n": 60.0, "bbox_e": 30.0}
_NORTH_SEA_BBOX = {"bbox_s": 51.0, "bbox_w": 0.0, "bbox_n": 60.0, "bbox_e": 9.0}


class WsConnection(Protocol):
    async def __aenter__(self) -> "WsConnection": ...
    async def __aexit__(self, *exc) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


WsConnector = Callable[[str], Awaitable[WsConnection]]


def _default_connect(url: str) -> Awaitable[WsConnection]:
    """Imported lazily so the tool module loads without `websockets`."""
    import websockets  # type: ignore

    return websockets.connect(url, open_timeout=5, close_timeout=2)


class AisQueryTool:
    name = "ais_query"
    description = (
        "Liefert eine kurze Live-Stichprobe der maritimen Lage (AIS) über "
        "den Sovereign Maritime-Multiplexer. Der Tool-Aufruf öffnet ein "
        "WebSocket-Fenster von wenigen Sekunden, sammelt eintreffende "
        "Vessel-Updates und gibt Anzahl + bis zu 12 Schiffe (mmsi, name, "
        "lat/lon, sog, cog, type) zurück. Region-Shortcuts: 'baltic', "
        "'north_sea'. Daten sind Open-Source-AIS, keine taktische Bewertung."
    )
    parameters = {
        "region": {
            "type": "str",
            "description": "Region-Shortcut: 'baltic' | 'north_sea'. Optional.",
            "required": False,
        },
        "bbox_s": {"type": "float", "description": "Süd-Lat", "required": False},
        "bbox_w": {"type": "float", "description": "West-Lon", "required": False},
        "bbox_n": {"type": "float", "description": "Nord-Lat", "required": False},
        "bbox_e": {"type": "float", "description": "Ost-Lon", "required": False},
        "window_seconds": {
            "type": "float",
            "description": "Sammel-Fenster in Sekunden. Default 2.0, max 5.0.",
            "required": False,
        },
    }

    # Hard cap so a chatty upstream can't exhaust the chat-service timeout.
    DEFAULT_WINDOW_S = 2.0
    MAX_WINDOW_S = 5.0
    MAX_MESSAGES = 200

    def __init__(
        self,
        base_url: str,
        audit: AuditWriter,
        ols_cap: str,
        connector: WsConnector = _default_connect,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._audit = audit
        self._ols_cap = ols_cap
        self._connect = connector

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        bbox = self._resolve_bbox(args)
        try:
            window = min(self.MAX_WINDOW_S, max(0.2, float(args.get("window_seconds") or self.DEFAULT_WINDOW_S)))
        except (TypeError, ValueError):
            window = self.DEFAULT_WINDOW_S

        url = self._build_ws_url(bbox)
        out: dict[str, Any] = {"bbox": bbox, "window_seconds": window, "vessels": [], "samples": []}
        try:
            messages = await self._collect(url, window)
            vessels = self._dedupe_vessels(messages)
            out["count"] = len(vessels)
            out["samples"] = self._summarise(vessels, limit=12)
        except asyncio.TimeoutError:
            out["error"] = "ws_timeout"
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"

        await self._audit.record(
            action="chat_tool_call",
            resource_type="ais_query",
            resource_id=None,
            ols_label=ols_label_to_int(self._ols_cap),
            payload={"args": args, "bbox": bbox, "count": out.get("count", 0)},
        )
        return out

    # ------------------------------------------------------------------
    async def _collect(self, url: str, window: float) -> list[dict[str, Any]]:
        deadline = asyncio.get_running_loop().time() + window
        messages: list[dict[str, Any]] = []
        ws_ctx = self._connect(url)
        ws = await ws_ctx if not hasattr(ws_ctx, "__aenter__") else None
        try:
            if ws is None:
                ws = await ws_ctx.__aenter__()  # type: ignore[union-attr]
            while len(messages) < self.MAX_MESSAGES:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                try:
                    parsed = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(parsed, dict):
                    messages.append(parsed)
                elif isinstance(parsed, list):
                    messages.extend(m for m in parsed if isinstance(m, dict))
        finally:
            try:
                if hasattr(ws_ctx, "__aexit__"):
                    await ws_ctx.__aexit__(None, None, None)
                elif ws is not None:
                    await ws.close()
            except Exception:
                logger.debug("ais.close_failed", url=url)
        return messages

    @staticmethod
    def _dedupe_vessels(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Each AIS message keys on mmsi; later messages override earlier ones.
        latest: dict[str, dict[str, Any]] = {}
        for msg in messages:
            mmsi = msg.get("mmsi") or msg.get("MMSI") or msg.get("id")
            if mmsi is None:
                continue
            latest[str(mmsi)] = msg
        return list(latest.values())

    @staticmethod
    def _summarise(vessels: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for v in vessels[:limit]:
            out.append(
                {
                    "mmsi": v.get("mmsi") or v.get("MMSI") or v.get("id"),
                    "name": v.get("name") or v.get("ship_name"),
                    "lat": v.get("lat") or v.get("latitude"),
                    "lon": v.get("lon") or v.get("longitude"),
                    "sog": v.get("sog") or v.get("speed_kt"),
                    "cog": v.get("cog") or v.get("course"),
                    "type": v.get("ship_type") or v.get("type"),
                    "flag": v.get("flag") or v.get("country"),
                }
            )
        return out

    @staticmethod
    def _resolve_bbox(args: dict[str, Any]) -> Optional[dict[str, float]]:
        region = (args.get("region") or "").lower()
        if region == "baltic":
            return dict(_BALTIC_BBOX)
        if region == "north_sea":
            return dict(_NORTH_SEA_BBOX)
        keys = ("bbox_s", "bbox_w", "bbox_n", "bbox_e")
        if all(args.get(k) is not None for k in keys):
            try:
                return {k: float(args[k]) for k in keys}
            except (TypeError, ValueError):
                return None
        return None

    def _build_ws_url(self, bbox: Optional[dict[str, float]]) -> str:
        path = self._base_url.rstrip("/") + "/ws/maritime"
        # http -> ws upgrade so callers can pass an http base URL.
        if path.startswith("http://"):
            path = "ws://" + path[len("http://") :]
        elif path.startswith("https://"):
            path = "wss://" + path[len("https://") :]
        if bbox:
            qs = "&".join(f"{k}={v}" for k, v in bbox.items())
            path += "?" + qs
        return path

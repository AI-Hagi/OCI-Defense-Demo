"""
Fan-out multiplexer — one upstream → N browser WebSocket clients.

Per-client bbox filter is enforced server-side: the multiplexer reads
the upstream feed (bounded by upstream subscribe-bbox), then per client
checks lat/lon against the client's effective bbox before sending.

Send strategy:
* Each client has a bounded queue.
* On full queue, the slow client is dropped (back-pressure protection).
* No locks on the hot path — just a copy of the connections-set per broadcast.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = structlog.get_logger(__name__)


# Per-client queue cap. AIS bursts can hit a few hundred frames/sec on busy
# bboxes; 256 gives ~5–10 s of buffering before we drop a slow client.
_CLIENT_QUEUE_MAX = 256


@dataclass(eq=False)  # identity-based hash + equality (fits set[_Client] usage)
class _Client:
    websocket: WebSocket
    bbox: tuple[float, float, float, float]  # (south, west, north, east)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(_CLIENT_QUEUE_MAX))
    sender_task: Optional[asyncio.Task] = None


class Multiplexer:
    """
    Holds the set of connected clients and broadcasts AIS frames into their
    per-client queues. Each client has its own sender task so that a slow
    socket cannot block the broadcast loop.
    """

    def __init__(self) -> None:
        self._clients: set[_Client] = set()
        self._lock = asyncio.Lock()
        self._frames_forwarded = 0
        self._slow_client_drops = 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def frames_forwarded(self) -> int:
        return self._frames_forwarded

    @property
    def slow_client_drops(self) -> int:
        return self._slow_client_drops

    async def add_client(
        self,
        websocket: WebSocket,
        bbox: tuple[float, float, float, float],
    ) -> _Client:
        client = _Client(websocket=websocket, bbox=bbox)
        client.sender_task = asyncio.create_task(
            self._sender_loop(client), name=f"ais-sender-{id(client)}"
        )
        async with self._lock:
            self._clients.add(client)
        logger.info(
            "mux.client_added",
            bbox=list(bbox),
            client_count=len(self._clients),
        )
        return client

    async def remove_client(self, client: _Client) -> None:
        async with self._lock:
            self._clients.discard(client)
        if client.sender_task is not None:
            client.sender_task.cancel()
            try:
                await client.sender_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        logger.info("mux.client_removed", client_count=len(self._clients))

    async def broadcast(self, frame: dict) -> None:
        """Push frame to each matching client's queue."""
        # Snapshot to avoid holding the lock while we iterate / put_nowait.
        async with self._lock:
            clients = list(self._clients)

        lat = frame.get("lat")
        lon = frame.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return

        for client in clients:
            s, w, n, e = client.bbox
            if not (s <= lat <= n and w <= lon <= e):
                continue
            try:
                client.queue.put_nowait(frame)
                self._frames_forwarded += 1
            except asyncio.QueueFull:
                self._slow_client_drops += 1
                logger.warning("mux.client_slow_drop", bbox=list(client.bbox))
                # Schedule the slow client for removal — don't block broadcast.
                asyncio.create_task(self._kick_slow_client(client))

    async def _kick_slow_client(self, client: _Client) -> None:
        try:
            if client.websocket.application_state == WebSocketState.CONNECTED:
                await client.websocket.close(code=1013)  # try-again-later
        except Exception:  # noqa: BLE001
            pass
        await self.remove_client(client)

    async def _sender_loop(self, client: _Client) -> None:
        try:
            while True:
                frame = await client.queue.get()
                if client.websocket.application_state != WebSocketState.CONNECTED:
                    return
                try:
                    await client.websocket.send_json(frame)
                except Exception as exc:  # noqa: BLE001
                    logger.info("mux.client_send_failed", error=str(exc))
                    return
        except asyncio.CancelledError:
            return

    async def shutdown(self) -> None:
        async with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            if client.sender_task is not None:
                client.sender_task.cancel()
            try:
                if client.websocket.application_state == WebSocketState.CONNECTED:
                    await client.websocket.close(code=1001)
            except Exception:  # noqa: BLE001
                pass
        logger.info("mux.shutdown", removed=len(clients))

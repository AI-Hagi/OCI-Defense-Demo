"""
Upstream connection to wss://stream.aisstream.io/v0/stream.

* Single persistent connection per Multiplexer instance.
* Subscribe message includes the bbox filter and message-type filter.
* Exponential backoff (1, 2, 4, ..., max 60 s) on disconnect.
* Yields normalised AIS frames as plain dicts; the multiplexer fans out to clients.

Subscribe message format (aisstream.io v0, free tier):

  {
    "APIKey": "<key>",
    "BoundingBoxes": [[[south, west], [north, east]]],
    "FilterMessageTypes": ["PositionReport"]
  }

Reference: https://aisstream.io/documentation
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import structlog
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .settings import Settings, get_settings

logger = structlog.get_logger(__name__)


class UpstreamConnection:
    """Manages the single AIS Stream upstream WebSocket."""

    def __init__(
        self,
        api_key: str,
        bbox: tuple[float, float, float, float],
        settings: Optional[Settings] = None,
    ) -> None:
        if not api_key:
            raise ValueError("UpstreamConnection requires a non-empty api_key")
        self._api_key = api_key
        self._bbox = bbox  # (south, west, north, east)
        self._settings = settings or get_settings()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._stop = asyncio.Event()
        self._reconnects = 0
        self._frames_received = 0

    @property
    def reconnects(self) -> int:
        return self._reconnects

    @property
    def frames_received(self) -> int:
        return self._frames_received

    @property
    def url(self) -> str:
        return self._settings.upstream_url

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    def _subscribe_payload(self) -> str:
        s, w, n, e = self._bbox
        # aisstream.io expects [[lat, lon], [lat, lon]] — south-west then north-east.
        return json.dumps(
            {
                "APIKey": self._api_key,
                "BoundingBoxes": [[[s, w], [n, e]]],
                "FilterMessageTypes": ["PositionReport"],
            }
        )

    async def iter_frames(self) -> AsyncIterator[dict]:
        """
        Yield normalised AIS frames forever (until stop()).

        Each yielded dict has the downstream-broadcast shape:
          {type, mmsi, lat, lon, heading_deg, speed_kn, vessel_name, classification, ts}
        """
        backoff = 1.0
        max_backoff = self._settings.upstream_max_backoff_seconds

        while not self._stop.is_set():
            try:
                logger.info(
                    "upstream.connect",
                    url=self.url,
                    bbox=list(self._bbox),
                )
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    self._ws = ws
                    await ws.send(self._subscribe_payload())
                    logger.info("upstream.subscribed", bbox=list(self._bbox))
                    backoff = 1.0  # reset on successful connect

                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        frame = self._normalise(raw)
                        if frame is None:
                            continue
                        self._frames_received += 1
                        yield frame
            except ConnectionClosed as exc:
                logger.warning(
                    "upstream.closed",
                    code=getattr(exc, "code", None),
                    reason=getattr(exc, "reason", None),
                )
            except WebSocketException as exc:
                logger.warning("upstream.ws_error", error=str(exc))
            except OSError as exc:
                logger.warning("upstream.network_error", error=str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("upstream.unexpected_error", error=str(exc))
            finally:
                self._ws = None

            if self._stop.is_set():
                break

            self._reconnects += 1
            logger.info("upstream.reconnect", delay_s=backoff, attempt=self._reconnects)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                # stop fired during sleep
                break
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2.0, max_backoff)

    @staticmethod
    def _normalise(raw: str | bytes) -> Optional[dict]:
        """
        Translate an aisstream.io PositionReport into the downstream frame shape.

        Returns None for non-PositionReport messages or malformed payloads;
        callers should skip Nones rather than treat them as errors.
        """
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            msg = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

        msg_type = msg.get("MessageType")
        if msg_type != "PositionReport":
            return None

        meta = msg.get("MetaData") or {}
        body = (msg.get("Message") or {}).get("PositionReport") or {}

        try:
            mmsi = int(meta.get("MMSI") or body.get("UserID"))
            lat = float(body.get("Latitude"))
            lon = float(body.get("Longitude"))
        except (TypeError, ValueError):
            return None

        # Heading: 511 means "not available" per ITU-R M.1371.
        heading_raw = body.get("TrueHeading")
        heading_deg: Optional[float] = None
        if isinstance(heading_raw, (int, float)) and 0 <= heading_raw <= 359:
            heading_deg = float(heading_raw)

        speed_raw = body.get("Sog")
        speed_kn: Optional[float] = None
        if isinstance(speed_raw, (int, float)) and speed_raw < 102.3:
            speed_kn = float(speed_raw)

        vessel_name = meta.get("ShipName")
        if isinstance(vessel_name, str):
            vessel_name = vessel_name.strip() or None

        ts = meta.get("time_utc") or datetime.now(timezone.utc).isoformat()

        return {
            "type": "ais_frame",
            "mmsi": mmsi,
            "lat": lat,
            "lon": lon,
            "heading_deg": heading_deg,
            "speed_kn": speed_kn,
            "vessel_name": vessel_name,
            "classification": 100,  # OPEN — public AIS
            "ts": ts,
        }

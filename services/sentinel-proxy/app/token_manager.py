"""
OAuth2 client-credentials token cache for Copernicus Dataspace.

State is in-process. The token is fetched at startup; a background task
refreshes it every TOKEN_REFRESH_MINUTES (default 25 — Copernicus tokens
live 30 min). A refresh failure does NOT crash the service — counters go
up, the next tick retries; in-flight tile requests use the (about to
expire) token until refresh succeeds.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from .settings import Settings

logger = structlog.get_logger(__name__)


class TokenError(RuntimeError):
    """Raised when no token has ever been acquired (cold start failure)."""


class TokenManager:
    """Holds a single OAuth2 access_token; refreshes on a fixed interval."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: Optional[str] = None
        self._fetched_at: Optional[datetime] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.refresh_count = 0
        self.refresh_failures = 0

    @property
    def has_token(self) -> bool:
        return self._token is not None

    @property
    def token_age_seconds(self) -> Optional[float]:
        if self._fetched_at is None:
            return None
        return (datetime.now(timezone.utc) - self._fetched_at).total_seconds()

    def get_token(self) -> str:
        """Return the cached token. Raises TokenError if cold-start failed."""
        if self._token is None:
            raise TokenError("no Sentinel Hub token available — cold start failed")
        return self._token

    async def start(self) -> None:
        """Acquire initial token + spawn the refresh loop."""
        await self._refresh_once()
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(), name="sentinel-token-refresh"
        )

    async def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._refresh_task = None

    async def _refresh_loop(self) -> None:
        interval = self._settings.token_refresh_minutes * 60
        while True:
            try:
                await asyncio.sleep(interval)
                await self._refresh_once()
            except asyncio.CancelledError:
                return
            except Exception:
                # Already counted in _refresh_once. Keep the loop alive.
                logger.exception("token.refresh_loop_iteration_error")

    async def _refresh_once(self) -> None:
        async with self._lock:
            client_id = self._settings.sentinel_client_id
            client_secret = self._settings.sentinel_client_secret
            if not client_id or not client_secret:
                self.refresh_failures += 1
                logger.error(
                    "token.missing_credentials",
                    has_client_id=bool(client_id),
                    has_client_secret=bool(client_secret),
                )
                return
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        self._settings.sentinel_token_url,
                        data={
                            "grant_type": "client_credentials",
                            "client_id": client_id,
                            "client_secret": client_secret,
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
            except httpx.HTTPError as exc:
                self.refresh_failures += 1
                logger.warning("token.network_error", error=str(exc))
                return

            if resp.status_code != 200:
                self.refresh_failures += 1
                logger.warning(
                    "token.upstream_status",
                    status_code=resp.status_code,
                    body_prefix=resp.text[:200],
                )
                return

            try:
                body = resp.json()
            except ValueError:
                self.refresh_failures += 1
                logger.warning("token.upstream_non_json")
                return

            access = body.get("access_token")
            if not access or not isinstance(access, str):
                self.refresh_failures += 1
                logger.warning("token.no_access_token", keys=list(body.keys()))
                return

            self._token = access
            self._fetched_at = datetime.now(timezone.utc)
            self.refresh_count += 1
            logger.info(
                "token.refreshed",
                expires_in=body.get("expires_in"),
                token_length=len(access),
                refresh_count=self.refresh_count,
            )

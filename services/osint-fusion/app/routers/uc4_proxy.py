"""
UC4 ORDS reverse-proxy.

The browser cannot hold the OAuth2 client_secret (CLAUDE.md: "NEVER write API
keys ... into frontend/src/config.ts or other browser-reachable files. OCI
Vault only."), so this router sits in front of the four UC4_OSINT ORDS tools:

    /api/uc4/tools/graph_query        -> POST  ORDS /uc4_osint/api/v1/tools/graph_query
    /api/uc4/tools/spatial_aggregate  -> POST  ORDS /uc4_osint/api/v1/tools/spatial_aggregate
    /api/uc4/tools/persist_briefing   -> POST  ORDS /uc4_osint/api/v1/tools/persist_briefing
    /api/uc4/tools/vector_hybrid_search -> POST ORDS /uc4_osint/api/v1/tools/vector_hybrid_search

Responsibilities:
  * Resolve OAuth client credentials at first use:
      - prefer plain env (UC4_OAUTH_CLIENT_ID / _SECRET) for local dev,
      - else fetch the two secrets by Vault OCID using the Resource Principal /
        Workload Identity bound to the OKE pod.
  * Maintain a single in-process bearer token, refreshed when expires_at < now+60s.
  * Forward the request body and the X-OLS-Label-Max header verbatim.
  * Return ORDS's status code and body unmodified — including 401/403/503
    so callers see the real ORDS contract.

This is a *minimal* proxy. It does NOT validate the request body shape — that
is ORDS's job (see 05_ords_tools.sql). It also does NOT mediate user identity:
the browser sends X-OLS-Label-Max, the proxy forwards it. The trust boundary
that determines what cap the user is *allowed* to request lives in the
Sovereign Defence frontend's tenant/persona switcher (UC3 collaboration model).
For procurement-grade deployments, drop a JWT-validating middleware between
the browser and this router.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["uc4-proxy"])


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UC4_ORDS_BASE_URL = os.environ.get(
    "UC4_ORDS_BASE_URL",
    "https://G8CC3767E64A14A-SOVDEF26.adb.eu-frankfurt-1.oraclecloudapps.com/ords",
)
UC4_TOOLS_BASE = f"{UC4_ORDS_BASE_URL}/uc4_osint/api/v1/tools"
UC4_TOKEN_URL = os.environ.get(
    "UC4_ORDS_OAUTH_TOKEN_URL",
    f"{UC4_ORDS_BASE_URL}/uc4_osint/oauth/token",
)

# 60s safety margin against ORDS's 3600s default token lifetime.
TOKEN_REFRESH_MARGIN_SEC = 60

ALLOWED_TOOLS = {
    "graph_query",
    "spatial_aggregate",
    "persist_briefing",
    "vector_hybrid_search",
}


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def _resolve_oauth_credentials() -> tuple[str, str]:
    """Resolve (client_id, client_secret) from env or OCI Vault.

    Plain env wins so local dev doesn't need OCI auth. In OKE the Vault path
    runs through the pod's Workload Identity.
    """
    cid = os.environ.get("UC4_OAUTH_CLIENT_ID")
    secret = os.environ.get("UC4_OAUTH_CLIENT_SECRET")
    if cid and secret:
        return cid, secret

    cid_ocid = os.environ.get("UC4_OAUTH_CLIENT_ID_VAULT_OCID")
    secret_ocid = os.environ.get("UC4_OAUTH_CLIENT_SECRET_VAULT_OCID")
    if not cid_ocid or not secret_ocid:
        raise RuntimeError(
            "UC4 proxy: set UC4_OAUTH_CLIENT_ID + _SECRET (dev) "
            "or UC4_OAUTH_CLIENT_ID_VAULT_OCID + _SECRET_VAULT_OCID (prod)."
        )

    # Lazy import: oci is heavy and unused in unit tests that monkey-patch
    # _resolve_oauth_credentials directly.
    import oci  # type: ignore

    signer = oci.auth.signers.get_resource_principals_signer()
    client = oci.secrets.SecretsClient(config={}, signer=signer)

    def _read(ocid: str) -> str:
        bundle = client.get_secret_bundle(ocid).data
        # secret_bundle_content has 'content_type' and 'content' (base64)
        content = bundle.secret_bundle_content.content
        return base64.b64decode(content).decode("utf-8")

    return _read(cid_ocid), _read(secret_ocid)


# ---------------------------------------------------------------------------
# Bearer token cache
# ---------------------------------------------------------------------------


class _TokenCache:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_fresh(self, now: float) -> bool:
        return self._token is not None and (now + TOKEN_REFRESH_MARGIN_SEC) < self._expires_at

    async def get(self, http_client: httpx.AsyncClient) -> str:
        now = time.monotonic()
        if self._is_fresh(now):
            return self._token  # type: ignore[return-value]

        async with self._lock:
            now = time.monotonic()
            if self._is_fresh(now):
                return self._token  # type: ignore[return-value]
            cid, secret = _resolve_oauth_credentials()
            resp = await http_client.post(
                UC4_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(cid, secret),
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.error("UC4 token fetch failed: %s %s", resp.status_code, resp.text[:300])
                raise HTTPException(
                    status_code=502,
                    detail=f"UC4 OAuth token endpoint returned {resp.status_code}",
                )
            payload = resp.json()
            token = payload.get("access_token")
            expires_in = int(payload.get("expires_in", 3600))
            if not token:
                raise HTTPException(status_code=502, detail="UC4 token response missing access_token")
            self._token = token
            self._expires_at = now + expires_in
            logger.info("UC4 bearer refreshed (ttl=%ss)", expires_in)
            return token

    def clear(self) -> None:
        """Drop the cached token. Called on 401 from ORDS to force refresh."""
        self._token = None
        self._expires_at = 0.0


_token_cache = _TokenCache()


# ---------------------------------------------------------------------------
# HTTP client (singleton)
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    return _http_client


async def aclose_http_client() -> None:
    """Call from FastAPI shutdown to release sockets."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


# ---------------------------------------------------------------------------
# Proxy handler
# ---------------------------------------------------------------------------


async def _proxy(tool: str, body_bytes: bytes, ols_cap: str) -> Response:
    if tool not in ALLOWED_TOOLS:
        raise HTTPException(status_code=404, detail=f"Unknown UC4 tool: {tool}")

    client = _get_http_client()
    target_url = f"{UC4_TOOLS_BASE}/{tool}"

    async def _send_with(token: str) -> httpx.Response:
        return await client.post(
            target_url,
            content=body_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-OLS-Label-Max": ols_cap,
            },
        )

    token = await _token_cache.get(client)
    upstream = await _send_with(token)
    if upstream.status_code == 401:
        # Token may have been revoked / expired faster than expected.
        logger.info("UC4 ORDS returned 401, refreshing bearer once and retrying")
        _token_cache.clear()
        token = await _token_cache.get(client)
        upstream = await _send_with(token)

    media_type = upstream.headers.get("content-type", "application/json")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=media_type,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/tools/{tool}")
async def proxy_tool(
    tool: str,
    request: Request,
    x_ols_label_max: str = Header(default="OFFEN", alias="X-OLS-Label-Max"),
) -> Response:
    body = await request.body()
    return await _proxy(tool, body, x_ols_label_max)


@router.get("/health")
async def proxy_health() -> dict[str, Any]:
    """Lightweight: only confirms env wiring, doesn't burn an ORDS round-trip."""
    using_env = bool(
        os.environ.get("UC4_OAUTH_CLIENT_ID")
        and os.environ.get("UC4_OAUTH_CLIENT_SECRET")
    )
    using_vault = bool(
        os.environ.get("UC4_OAUTH_CLIENT_ID_VAULT_OCID")
        and os.environ.get("UC4_OAUTH_CLIENT_SECRET_VAULT_OCID")
    )
    return {
        "service": "uc4-proxy",
        "ords_base": UC4_ORDS_BASE_URL,
        "credentials_source": (
            "env" if using_env else "vault" if using_vault else "unconfigured"
        ),
        "token_cached": _token_cache._token is not None,
    }

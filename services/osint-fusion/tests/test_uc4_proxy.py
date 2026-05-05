"""
Tests for the UC4 ORDS reverse-proxy router.

The proxy holds the OAuth client_secret and brokers ORDS calls so the
browser never sees credentials. These tests stub the upstream ORDS by
patching the module-level httpx client; we don't make real network calls.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Pin env so credential resolution doesn't try to reach OCI Vault.
    monkeypatch.setenv("UC4_OAUTH_CLIENT_ID", "test-client")
    monkeypatch.setenv("UC4_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("UC4_ORDS_BASE_URL", "https://ords.test/ords")
    # ORACLE_USER/PASSWORD are read by db.py at first DB call; we don't hit DB.
    monkeypatch.setenv("ORACLE_USER", "x")
    monkeypatch.setenv("ORACLE_PASSWORD", "x")

    # Reset module state so cached token / http client don't leak between tests.
    from app.routers import uc4_proxy

    uc4_proxy._token_cache = uc4_proxy._TokenCache()
    uc4_proxy._http_client = None
    # Reload the configuration constants since they read os.environ at import.
    uc4_proxy.UC4_ORDS_BASE_URL = os.environ["UC4_ORDS_BASE_URL"]
    uc4_proxy.UC4_TOOLS_BASE = f"{uc4_proxy.UC4_ORDS_BASE_URL}/uc4_osint/api/v1/tools"
    uc4_proxy.UC4_TOKEN_URL = f"{uc4_proxy.UC4_ORDS_BASE_URL}/uc4_osint/oauth/token"

    from app.main import app

    return TestClient(app)


def _mock_transport(routes: dict[str, tuple[int, dict | bytes]]) -> httpx.MockTransport:
    """Tiny dispatcher mapping URL → (status, json_body|bytes)."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key not in routes:
            return httpx.Response(404, json={"error": f"unmocked: {key}"})
        status, payload = routes[key]
        if isinstance(payload, dict):
            return httpx.Response(status, json=payload)
        return httpx.Response(status, content=payload)

    return httpx.MockTransport(handler)


def _install_mock_client(transport: httpx.MockTransport) -> None:
    from app.routers import uc4_proxy

    uc4_proxy._http_client = httpx.AsyncClient(transport=transport, timeout=5.0)


def test_health_reports_credentials_source(app_client: TestClient) -> None:
    resp = app_client.get("/api/uc4/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "uc4-proxy"
    assert body["credentials_source"] == "env"
    assert body["ords_base"] == "https://ords.test/ords"


def test_unknown_tool_returns_404(app_client: TestClient) -> None:
    transport = _mock_transport({})
    _install_mock_client(transport)
    resp = app_client.post("/api/uc4/tools/banana", json={})
    assert resp.status_code == 404


def test_proxy_forwards_body_token_and_ols_header(app_client: TestClient) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        if request.url.path.endswith("/api/v1/tools/graph_query"):
            captured["url"] = str(request.url)
            captured["body"] = request.content
            captured["auth"] = request.headers.get("authorization")
            captured["x_ols"] = request.headers.get("x-ols-label-max")
            return httpx.Response(
                200,
                json={
                    "request_id": "fake",
                    "duration_ms": 1.0,
                    "data": {"entities": []},
                    "ols_cap_applied": 50,
                    "ols_cap_label": "NFD",
                },
            )
        return httpx.Response(404)

    _install_mock_client(httpx.MockTransport(handler))

    resp = app_client.post(
        "/api/uc4/tools/graph_query",
        headers={"X-OLS-Label-Max": "NFD"},
        json={"pattern": "multi_source_entity", "args": {"hours": 72, "min_correlations": 2}},
    )
    assert resp.status_code == 200
    assert resp.json()["ols_cap_label"] == "NFD"
    assert captured["auth"] == "Bearer tok-123"
    assert captured["x_ols"] == "NFD"
    assert b'"multi_source_entity"' in captured["body"]
    assert b'"pattern"' in captured["body"]


def test_proxy_returns_upstream_error_codes_unchanged(app_client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        # Mimic vector_hybrid_search 503 (embeddings still NULL)
        return httpx.Response(
            503,
            json={
                "type": "https://uc4.cloudebility.com/errors/vector-not-ready",
                "title": "Embeddings not ready",
                "status": 503,
            },
        )

    _install_mock_client(httpx.MockTransport(handler))

    resp = app_client.post(
        "/api/uc4/tools/vector_hybrid_search",
        headers={"X-OLS-Label-Max": "INTERN"},
        json={"query": "anything", "top_k": 5},
    )
    assert resp.status_code == 503
    assert resp.json()["title"] == "Embeddings not ready"


def test_proxy_refreshes_bearer_on_401_then_retries(app_client: TestClient) -> None:
    state = {"token_calls": 0, "tool_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            state["token_calls"] += 1
            return httpx.Response(
                200, json={"access_token": f"tok-{state['token_calls']}", "expires_in": 3600}
            )
        # First tool call: 401. Second: 200.
        state["tool_calls"] += 1
        if state["tool_calls"] == 1:
            return httpx.Response(401, json={"code": "Unauthorized"})
        return httpx.Response(
            200,
            json={
                "request_id": "fake",
                "duration_ms": 1.0,
                "data": {"entities": []},
                "ols_cap_applied": 10,
                "ols_cap_label": "OFFEN",
            },
        )

    _install_mock_client(httpx.MockTransport(handler))

    resp = app_client.post(
        "/api/uc4/tools/graph_query",
        headers={"X-OLS-Label-Max": "OFFEN"},
        json={"pattern": "multi_source_entity", "args": {"hours": 1, "min_correlations": 1}},
    )
    assert resp.status_code == 200
    assert state["token_calls"] == 2  # initial + refresh after 401
    assert state["tool_calls"] == 2  # 401 + retry


def test_resolve_credentials_raises_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "UC4_OAUTH_CLIENT_ID",
        "UC4_OAUTH_CLIENT_SECRET",
        "UC4_OAUTH_CLIENT_ID_VAULT_OCID",
        "UC4_OAUTH_CLIENT_SECRET_VAULT_OCID",
    ):
        monkeypatch.delenv(k, raising=False)
    from app.routers.uc4_proxy import _resolve_oauth_credentials

    with pytest.raises(RuntimeError, match="UC4 proxy"):
        _resolve_oauth_credentials()

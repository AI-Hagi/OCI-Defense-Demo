"""End-to-end smoke against the FastAPI app in mock LLM mode.

Uses httpx.MockTransport for the upstream flights-proxy so no real network
traffic happens. Verifies the round-trip:
  POST /api/uc4-chat/ask  → orchestrator → flights_query (mocked) → LLM (mock)
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.llm import LlmClient, LlmResponse, LlmToolCall, MockLlmDriver
from app.settings import Settings


@pytest.fixture
def client() -> TestClient:
    settings = Settings(CHAT_LLM_MODE="mock", FLIGHTS_PROXY_URL="http://flights-mock")

    def handler(request: httpx.Request) -> httpx.Response:
        if "mil" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
                            "properties": {
                                "callsign": "GAF071",
                                "is_mil": True,
                                "alt_baro": 28000,
                                "gs": 380,
                            },
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://flights-mock")

    driver = MockLlmDriver(
        scripted=[
            LlmResponse(
                text=None,
                tool_calls=[
                    LlmToolCall(
                        name="flights_query",
                        parameters={"kind": "mil", "region": "germany"},
                    )
                ],
                model="cohere.command-r-plus",
            ),
            LlmResponse(
                text="Aktuell ist 1 militärische Maschine über DE erfasst.",
                tool_calls=[],
                model="cohere.command-r-plus",
            ),
        ]
    )

    # Skip @app.on_event startup; inject manually.
    main_module.app.state.settings = settings
    main_module.app.state.http = http
    main_module.app.state.llm = LlmClient(settings, driver=driver)

    test_client = TestClient(main_module.app)
    test_client.headers.update({"X-OLS-Label-Max": "NFD", "X-Tenant-Id": "T001"})
    yield test_client

    import asyncio

    asyncio.get_event_loop().run_until_complete(http.aclose())


def test_ask_returns_answer_and_trace(client: TestClient) -> None:
    resp = client.post(
        "/api/uc4-chat/ask",
        json={"question": "Welche militärischen Flugzeuge fliegen über DE?", "history": []},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "1 militärische" in body["answer"]
    assert body["model"] == "cohere.command-r-plus"
    assert body["hops"] == 1
    assert len(body["trace"]) == 1
    assert body["trace"][0]["tool"] == "flights_query"
    assert body["trace"][0]["error"] is None


def test_ask_rejects_invalid_ols_cap(client: TestClient) -> None:
    resp = client.post(
        "/api/uc4-chat/ask",
        json={"question": "test", "history": []},
        headers={"X-OLS-Label-Max": "ULTRA"},
    )
    assert resp.status_code == 400
    assert "invalid X-OLS-Label-Max" in resp.json()["detail"]


def test_health_endpoint() -> None:
    test_client = TestClient(main_module.app)
    resp = test_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "uc4-chat"

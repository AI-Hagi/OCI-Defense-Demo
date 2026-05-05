"""WebSocket streaming smoke test against /ws/uc4-chat.

Uses fastapi.testclient (sync WebSocket helper) plus an httpx MockTransport
for the upstream flights-proxy and a scripted MockLlmDriver.
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
                            "properties": {"callsign": "GAF071", "is_mil": True},
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
                text="1 militärische Maschine erfasst.",
                tool_calls=[],
                model="cohere.command-r-plus",
            ),
        ]
    )

    main_module.app.state.settings = settings
    main_module.app.state.http = http
    main_module.app.state.llm = LlmClient(settings, driver=driver)
    yield TestClient(main_module.app)


def test_ws_streams_full_event_sequence(client: TestClient) -> None:
    with client.websocket_connect("/ws/uc4-chat") as ws:
        ws.send_json(
            {
                "type": "ask",
                "question": "Welche militärischen Flugzeuge fliegen über DE?",
                "ols_cap": "NFD",
            }
        )
        events: list[dict] = []
        # Server closes the socket after the answer; collect until disconnect.
        try:
            while True:
                events.append(ws.receive_json())
        except Exception:
            pass

    types = [e["type"] for e in events]
    # Expected order: started → tool_call → tool_result → answer
    assert types == ["started", "tool_call", "tool_result", "answer"]

    assert events[0]["ols_cap"] == "NFD"
    assert events[1]["tool"] == "flights_query"
    assert events[1]["args"] == {"kind": "mil", "region": "germany"}
    assert events[2]["ok"] is True
    assert events[2]["error"] is None
    assert "counts" in events[2]["summary"]
    assert events[3]["text"] == "1 militärische Maschine erfasst."
    assert events[3]["hops"] == 1


def test_ws_rejects_invalid_ols_cap(client: TestClient) -> None:
    with client.websocket_connect("/ws/uc4-chat") as ws:
        ws.send_json({"type": "ask", "question": "test", "ols_cap": "ULTRA"})
        evt = ws.receive_json()
    assert evt["type"] == "error"
    assert "invalid frame" in evt["message"].lower() or "ols_cap" in evt["message"].lower()


def test_ws_rejects_wrong_frame_type(client: TestClient) -> None:
    with client.websocket_connect("/ws/uc4-chat") as ws:
        ws.send_json({"type": "tool_call", "question": "test"})
        evt = ws.receive_json()
    assert evt["type"] == "error"

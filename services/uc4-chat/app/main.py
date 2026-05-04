"""
UC4 Chat Service — FastAPI entrypoint (Step 1: HTTP request/response).

WebSocket streaming arrives in Step 2. For now a single POST /api/uc4-chat/ask
runs the orchestrator end-to-end and returns the trace + final answer so we
can curl it before the frontend lands.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from .audit import AuditWriter, ols_label_to_int
from .llm import LlmClient
from .orchestrator import ChatOrchestrator, ChatTurn
from .settings import get_settings
from .tools import build_tool_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("uc4-chat")

app = FastAPI(title="Sovereign Defence UC4 Chat", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Lifespan: shared httpx client for tool fan-out
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _startup() -> None:
    settings = get_settings()
    app.state.settings = settings
    app.state.http = httpx.AsyncClient(timeout=settings.upstream_timeout_seconds)
    app.state.llm = LlmClient(settings)
    logger.info(
        "uc4-chat.startup model=%s fallback=%s mode=%s",
        settings.chat_model,
        settings.chat_fallback_model,
        settings.chat_llm_mode,
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    http: Optional[httpx.AsyncClient] = getattr(app.state, "http", None)
    if http is not None:
        await http.aclose()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list)


class ToolTrace(BaseModel):
    tool: str
    args: dict
    duration_ms: float
    error: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    model: str
    hops: int
    trace: list[ToolTrace]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "uc4-chat"}


@app.post("/api/uc4-chat/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    x_ols_label_max: str = Header(default="OFFEN", alias="X-OLS-Label-Max"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
) -> AskResponse:
    settings = app.state.settings
    tenant = x_tenant_id or settings.x_tenant_default
    cap = x_ols_label_max.upper()
    if cap not in {"OFFEN", "INTERN", "NFD", "GEHEIM"}:
        raise HTTPException(status_code=400, detail=f"invalid X-OLS-Label-Max: {cap}")

    audit = AuditWriter(tenant_id=tenant)
    tools = build_tool_registry(http=app.state.http, settings=settings, audit=audit, ols_cap=cap)
    orchestrator = ChatOrchestrator(
        llm=app.state.llm,
        tools=tools,
        max_hops=settings.chat_max_tool_hops,
        ols_cap=cap,
        tenant_id=tenant,
    )

    await audit.record(
        action="chat_request",
        resource_type="chat_session",
        resource_id=None,
        ols_label=ols_label_to_int(cap),
        payload={"question": body.question, "history_len": len(body.history)},
    )

    result = await orchestrator.run(body.question, body.history)

    await audit.record(
        action="chat_response",
        resource_type="chat_session",
        resource_id=None,
        ols_label=ols_label_to_int(cap),
        payload={
            "model": result.model,
            "hops": result.hops,
            "answer_chars": len(result.answer),
            "tools_called": [t.tool for t in result.trace],
        },
    )

    return AskResponse(
        answer=result.answer,
        model=result.model,
        hops=result.hops,
        trace=[
            ToolTrace(
                tool=t.tool, args=t.args, duration_ms=t.duration_ms, error=t.error
            )
            for t in result.trace
        ],
    )


# ---------------------------------------------------------------------------
# WebSocket — streaming variant
# ---------------------------------------------------------------------------
class WsAskFrame(BaseModel):
    """First (and so far only) client frame: the user question."""

    type: str = Field(..., pattern="^ask$")
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list)
    ols_cap: str = Field(default="OFFEN", pattern="^(OFFEN|INTERN|NFD|GEHEIM)$")
    tenant_id: Optional[str] = None


@app.websocket("/ws/uc4-chat")
async def ws_chat(ws: WebSocket) -> None:
    """Streaming chat. Frames sent to client:

      * {type: "started",      ols_cap: "..."}
      * {type: "tool_call",    tool, args, hop}
      * {type: "tool_result",  tool, ok, duration_ms, error?, summary}
      * {type: "answer",       text, model, hops, forced?: true}
      * {type: "error",        message}

    The server closes the socket after one full chat turn so the contract
    stays simple — the frontend opens a fresh connection per question.
    """
    await ws.accept()
    settings = app.state.settings
    try:
        raw = await ws.receive_json()
        try:
            frame = WsAskFrame(**raw)
        except ValidationError as exc:
            await ws.send_json({"type": "error", "message": f"invalid frame: {exc.errors()[0]['msg']}"})
            await ws.close(code=1003)
            return

        tenant = frame.tenant_id or settings.x_tenant_default
        cap = frame.ols_cap.upper()
        audit = AuditWriter(tenant_id=tenant)
        tools = build_tool_registry(http=app.state.http, settings=settings, audit=audit, ols_cap=cap)
        orchestrator = ChatOrchestrator(
            llm=app.state.llm,
            tools=tools,
            max_hops=settings.chat_max_tool_hops,
            ols_cap=cap,
            tenant_id=tenant,
        )

        await audit.record(
            action="chat_request",
            resource_type="chat_session",
            resource_id="ws",
            ols_label=ols_label_to_int(cap),
            payload={"question": frame.question, "history_len": len(frame.history)},
        )

        async def sink(event: dict) -> None:
            await ws.send_json(event)

        result = await orchestrator.run(frame.question, frame.history, event_sink=sink)

        await audit.record(
            action="chat_response",
            resource_type="chat_session",
            resource_id="ws",
            ols_label=ols_label_to_int(cap),
            payload={
                "model": result.model,
                "hops": result.hops,
                "answer_chars": len(result.answer),
                "tools_called": [t.tool for t in result.trace],
            },
        )
        await ws.close(code=1000)
    except WebSocketDisconnect:
        logger.info("ws_chat client disconnected")
    except Exception as exc:
        logger.exception("ws_chat failed")
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.close(code=1011)
        except Exception:
            pass

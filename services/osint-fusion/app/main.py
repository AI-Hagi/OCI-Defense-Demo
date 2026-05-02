"""
FastAPI entrypoint for the OSINT Fusion service (port 8003).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import get_pool
from .routers import graph, uc4_proxy
from .openapi import customize_openapi

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("osint-fusion")

app = FastAPI(title="Sovereign Defence OSINT Fusion", version="1.0.0")
customize_openapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graph.router, prefix="/api/osint")
app.include_router(uc4_proxy.router, prefix="/api/uc4")


@app.on_event("shutdown")
async def _shutdown_uc4_proxy() -> None:
    await uc4_proxy.aclose_http_client()


@app.get("/health")
def health() -> dict[str, str]:
    db_state = "degraded"
    try:
        pool = get_pool()
        conn = pool.acquire()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM dual")
                cur.fetchone()
            db_state = "ok"
        finally:
            conn.close()
    except Exception:  # pragma: no cover
        logger.exception("DB health check failed")
    return {"status": "ok", "service": "osint-fusion", "db": db_state}

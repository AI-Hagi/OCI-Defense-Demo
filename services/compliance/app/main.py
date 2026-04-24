"""
FastAPI entrypoint for the Compliance service (port 8005).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import get_pool
from .routers import compliance
from .openapi import customize_openapi

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("compliance")

app = FastAPI(title="Sovereign Defence Compliance", version="1.0.0")
customize_openapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compliance.router, prefix="/api/compliance")


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
    return {"status": "ok", "service": "compliance", "db": db_state}

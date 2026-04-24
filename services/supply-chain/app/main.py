"""
FastAPI entrypoint for the Supply Chain service (port 8004).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import get_pool
from .routers import sc
from .openapi import customize_openapi

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("supply-chain")

app = FastAPI(title="Sovereign Defence Supply Chain", version="1.0.0")
customize_openapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sc.router)


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
    return {"status": "ok", "service": "supply-chain", "db": db_state}

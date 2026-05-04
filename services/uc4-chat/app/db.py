"""
Best-effort 26ai pool for audit writes.

The chat service degrades gracefully when ATP credentials are missing — it
still runs the LLM loop, but audit writes log a warning instead of throwing.
That keeps `pytest` and local-laptop runs working without a wallet.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Optional

import structlog

from .settings import Settings, get_settings

logger = structlog.get_logger(__name__)


class DBPoolUnavailable(RuntimeError):
    pass


PoolFactory = Callable[[Settings], Any]


def _default_pool_factory(settings: Settings) -> Any:
    import oracledb

    if not settings.atp_user or not settings.atp_password or not settings.atp_connection_name:
        raise DBPoolUnavailable(
            "ORACLE_USER / ORACLE_PASSWORD / ORACLE_CONNECT_STRING not set"
        )
    pool = oracledb.create_pool(
        user=settings.atp_user,
        password=settings.atp_password,
        dsn=settings.atp_connection_name,
        config_dir=settings.tns_admin,
        wallet_location=settings.tns_admin,
        wallet_password=settings.wallet_password,
        min=1,
        max=2,
        increment=1,
    )
    logger.info("db.pool.created", dsn=settings.atp_connection_name)
    return pool


class DBPool:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        pool_factory: PoolFactory = _default_pool_factory,
    ) -> None:
        self._settings = settings or get_settings()
        self._pool_factory = pool_factory
        self._pool: Any = None
        self._lock = threading.Lock()
        self._unavailable_reason: Optional[str] = None

    def is_available(self) -> bool:
        if self._unavailable_reason is not None:
            return False
        try:
            self._ensure_pool()
            return True
        except DBPoolUnavailable as exc:
            self._unavailable_reason = str(exc)
            return False

    def _ensure_pool(self) -> Any:
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    try:
                        self._pool = self._pool_factory(self._settings)
                    except Exception as exc:
                        raise DBPoolUnavailable(str(exc)) from exc
        return self._pool

    async def execute(self, sql: str, binds: Optional[dict[str, Any]] = None) -> None:
        await asyncio.to_thread(self._execute_sync, sql, binds or {})

    def _execute_sync(self, sql: str, binds: dict[str, Any]) -> None:
        pool = self._ensure_pool()
        conn = pool.acquire()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, binds)
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                logger.exception("db.conn.release_failed")


_GLOBAL_POOL: Optional[DBPool] = None


def get_db_pool() -> DBPool:
    global _GLOBAL_POOL
    if _GLOBAL_POOL is None:
        _GLOBAL_POOL = DBPool()
    return _GLOBAL_POOL

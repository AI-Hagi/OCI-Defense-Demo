"""
Async-friendly Oracle 26ai connection wrapper for the AIS Multiplexer.

oracledb is synchronous; we wrap pool acquisition + execute in
``asyncio.to_thread`` so the event loop is never blocked. The pool itself is
lazy and constructor-injectable for tests.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Optional

import structlog

from .settings import Settings, get_settings

logger = structlog.get_logger(__name__)


class DBPoolUnavailable(RuntimeError):
    """Raised when the connection pool cannot be created or reached."""


# We type-hint as Any to avoid forcing oracledb import at module load time
# (helps unit tests mock the pool without installing oracledb).
PoolFactory = Callable[[Settings], Any]


def _default_pool_factory(settings: Settings) -> Any:
    import oracledb  # imported lazily

    if not settings.atp_user or not settings.atp_password:
        raise DBPoolUnavailable(
            "ATP_USER / ATP_PASSWORD not set — cannot create 26ai pool"
        )

    pool = oracledb.create_pool(
        user=settings.atp_user,
        password=settings.atp_password,
        dsn=settings.atp_connection_name,
        config_dir=settings.tns_admin,
        wallet_location=settings.tns_admin,
        wallet_password=settings.wallet_password,
        min=1,
        max=4,
        increment=1,
    )
    logger.info(
        "db.pool.created",
        dsn=settings.atp_connection_name,
        min=1,
        max=4,
    )
    return pool


class DBPool:
    """Thread-safe lazy wrapper around an oracledb ConnectionPool."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        pool_factory: PoolFactory = _default_pool_factory,
    ) -> None:
        self._settings = settings or get_settings()
        self._pool_factory = pool_factory
        self._pool: Any = None
        self._lock = threading.Lock()

    def _ensure_pool(self) -> Any:
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    try:
                        self._pool = self._pool_factory(self._settings)
                    except Exception as exc:  # noqa: BLE001
                        raise DBPoolUnavailable(str(exc)) from exc
        return self._pool

    async def execute(
        self,
        sql: str,
        binds: Optional[dict[str, Any]] = None,
    ) -> None:
        """Execute a single statement (INSERT/UPDATE) with bind variables and commit."""
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
            except Exception:  # pragma: no cover
                logger.exception("db.conn.release_failed")

    async def healthcheck(self) -> bool:
        """Return True if SELECT 1 FROM dual works, False otherwise."""
        try:
            return await asyncio.to_thread(self._healthcheck_sync)
        except DBPoolUnavailable:
            return False

    def _healthcheck_sync(self) -> bool:
        pool = self._ensure_pool()
        conn = pool.acquire()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM dual")
                row = cur.fetchone()
                return bool(row and row[0] == 1)
        except Exception:  # noqa: BLE001
            logger.exception("db.healthcheck.failed")
            return False
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                logger.exception("db.conn.release_failed")

    def close(self) -> None:
        if self._pool is not None:
            try:
                self._pool.close()
            except Exception:  # pragma: no cover
                logger.exception("db.pool.close_failed")
            self._pool = None


# Module-level default pool — overridable in tests.
_default_pool: Optional[DBPool] = None


def get_db_pool() -> DBPool:
    global _default_pool
    if _default_pool is None:
        _default_pool = DBPool()
    return _default_pool


def set_db_pool(pool: DBPool) -> None:
    """Test hook — replace the default pool with an injected one."""
    global _default_pool
    _default_pool = pool

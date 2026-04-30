"""
Shared Oracle 26ai connection pool for the GEOINT service.

Uses oracledb Thin mode with an Autonomous DB wallet whose location is set via
the TNS_ADMIN environment variable. The connection string defaults to the
TNS alias "sovdef26_tp" (TP = transaction processing).

Required environment variables:
    ORACLE_USER            DB user (e.g. DICE_APP)
    ORACLE_PASSWORD        DB user password
    ORACLE_CONNECT_STRING  TNS alias from tnsnames.ora (default: sovdef26_tp)
    TNS_ADMIN              Wallet directory (default: /app/wallet)
    WALLET_PASSWORD        Wallet PKCS#12 password
"""
from __future__ import annotations

import logging
import os
from typing import Iterator

import oracledb

logger = logging.getLogger(__name__)

_pool: oracledb.ConnectionPool | None = None


def _build_pool() -> oracledb.ConnectionPool:
    """Create the global connection pool (Thin mode, mTLS wallet)."""
    wallet_dir = os.environ.get("TNS_ADMIN", "/app/wallet")
    pool = oracledb.create_pool(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ.get("ORACLE_CONNECT_STRING", "sovdef26_tp"),
        config_dir=wallet_dir,
        wallet_location=wallet_dir,
        wallet_password=os.environ.get("WALLET_PASSWORD", "YourSecurePassword123#"),
        min=1,
        max=4,
        increment=1,
    )
    logger.info("Oracle 26ai connection pool created (Thin mode)")
    return pool


def get_pool() -> oracledb.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = _build_pool()
    return _pool


def get_conn() -> Iterator[oracledb.Connection]:
    """FastAPI dependency: acquire a pooled connection and release on teardown."""
    pool = get_pool()
    conn = pool.acquire()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - best-effort release
            logger.exception("Failed to release pooled connection")


def set_tenant_identifier(conn: oracledb.Connection, tenant_id: str) -> None:
    """Propagate tenant context to the DB session for OLS / duality-view filters."""
    with conn.cursor() as cur:
        cur.execute("BEGIN DBMS_SESSION.SET_IDENTIFIER(:1); END;", [tenant_id])


def tenant_from_header(x_tenant_id: str | None) -> str:
    """Normalise the X-Tenant-Id header, defaulting to T001 for dev/demo."""
    return (x_tenant_id or "T001").strip() or "T001"

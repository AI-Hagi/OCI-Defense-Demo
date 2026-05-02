"""
audit_events writer for the Jamming Poller.

Schema is db/schema/07_audit_compliance.sql — same hash-chained table that
the AIS Multiplexer writes to. Every successful upstream fetch results in
ONE audit row (no batching: at 6 h refresh that's a few rows per day, not
worth amortizing).
"""
from __future__ import annotations

import json
from typing import Optional

import structlog

from .db import DBPool, get_db_pool

logger = structlog.get_logger(__name__)


_INSERT_AUDIT_SQL = """
INSERT INTO audit_events (
    actor_service, action, resource_type, resource_id,
    tenant_id, ols_label, payload
) VALUES (
    :actor_service, :action, :resource_type, :resource_id,
    :tenant_id, :ols_label, :payload
)
"""


class AuditWriter:
    """One audit row per upstream fetch — actor_service='jamming-poller'."""

    def __init__(self, tenant_id: str, pool: Optional[DBPool] = None) -> None:
        self._pool = pool or get_db_pool()
        self._tenant_id = tenant_id
        self.writes_total = 0
        self.write_failures_total = 0

    async def record_fetch(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        ols_label: int,
        payload: dict,
    ) -> None:
        try:
            await self._pool.execute(
                _INSERT_AUDIT_SQL,
                {
                    "actor_service": "jamming-poller",
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "tenant_id": self._tenant_id,
                    "ols_label": ols_label,
                    "payload": json.dumps(payload),
                },
            )
            self.writes_total += 1
        except Exception:
            # Don't swallow silently — log loudly but don't crash the poller
            # (the next fetch tick will re-attempt the audit row).
            self.write_failures_total += 1
            logger.exception(
                "audit.write_failed",
                action=action,
                resource_type=resource_type,
            )

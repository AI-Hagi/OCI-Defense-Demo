"""Audit-log writer for chat sessions and tool invocations.

Every chat turn writes:
  * one `chat_request` row when the user message arrives
  * one `chat_tool_call` row per tool invocation (with args, hops, latency)
  * one `chat_response` row when the loop terminates

The schema (`audit_events`) is shared with the other UC4 backends — see
flights-proxy/app/audit.py for the original column contract.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import structlog

from .db import DBPool, DBPoolUnavailable, get_db_pool

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

_OLS_LABEL_TO_INT = {
    "OFFEN": 10,
    "INTERN": 30,
    "NFD": 50,
    "GEHEIM": 70,
}


def ols_label_to_int(label: str) -> int:
    return _OLS_LABEL_TO_INT.get(label.upper(), 10)


class AuditWriter:
    """Best-effort audit writer — never crashes the chat loop."""

    def __init__(
        self,
        tenant_id: str,
        pool: Optional[DBPool] = None,
        actor_service: str = "uc4-chat",
    ) -> None:
        self._pool = pool or get_db_pool()
        self._tenant_id = tenant_id
        self._actor_service = actor_service
        self.writes_total = 0
        self.write_failures_total = 0
        self.skipped_total = 0

    async def record(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        ols_label: int,
        payload: dict[str, Any],
    ) -> None:
        if not self._pool.is_available():
            self.skipped_total += 1
            logger.debug(
                "audit.skipped",
                reason="pool_unavailable",
                action=action,
                resource_type=resource_type,
            )
            return
        try:
            await self._pool.execute(
                _INSERT_AUDIT_SQL,
                {
                    "actor_service": self._actor_service,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "tenant_id": self._tenant_id,
                    "ols_label": ols_label,
                    "payload": json.dumps(payload, default=str),
                },
            )
            self.writes_total += 1
        except DBPoolUnavailable:
            self.skipped_total += 1
            logger.debug("audit.skipped", reason="pool_unavailable")
        except Exception:
            self.write_failures_total += 1
            logger.exception(
                "audit.write_failed",
                action=action,
                resource_type=resource_type,
            )

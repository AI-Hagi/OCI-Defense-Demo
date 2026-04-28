"""
Mock-first endpoint tests for the ais-multiplexer (Sovereign Proxy Pattern B).

Expected contract (peer agent implements ``app.main``):

  GET  /healthz                -> 200 {"status": "ok", ...}
  GET  /metrics                -> 200 text/plain Prometheus exposition,
                                  must contain ``frames_received``
  WS   /ws/maritime            -> accept connection, normalised AIS frames

The tests mock OCI Vault and oracledb so they run offline. When the
parallel agent has not yet shipped ``app.main`` / ``app.db``, fixtures
``pytest.skip`` instead of failing — see conftest.py.
"""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------
def test_healthz_ok(client: Any) -> None:
    """``GET /healthz`` returns 200 with at least ``{"status": "ok"}``.

    503 is also tolerated when the DB pool is degraded — the service is
    free to return 503, but the JSON shape must still expose ``status``.
    """
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    assert "status" in body
    if resp.status_code == 200:
        assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------
def test_metrics_format(client: Any) -> None:
    """``GET /metrics`` returns a Prometheus-style body containing core counters."""
    resp = client.get("/metrics")
    assert resp.status_code == 200, resp.text
    text = resp.text
    # Required metric per README contract.
    assert "frames_received" in text, (
        f"frames_received metric missing from /metrics body:\n{text[:500]}"
    )


# ---------------------------------------------------------------------------
# /ws/maritime — handshake only.
# ---------------------------------------------------------------------------
def test_websocket_handshake(client: Any) -> None:
    """The downstream WebSocket accepts a connection and closes cleanly.

    We don't push real upstream frames here — the upstream is mocked away
    and frames may not arrive in the brief window we hold the socket open.
    The acceptance + clean-close is the contract.
    """
    try:
        with client.websocket_connect("/ws/maritime") as ws:
            # Optional: try to receive one frame with a tiny timeout. If the
            # service holds the socket open without sending, that's still a
            # valid handshake — a successful __enter__ proves accept().
            try:
                ws.receive_text(timeout=0.2)  # type: ignore[call-arg]
            except TypeError:
                # starlette TestClient WS receive does not take ``timeout``.
                pass
            except Exception:
                # No frame within window — still OK; we just want accept().
                pass
            # __exit__ closes cleanly.
    except Exception as exc:
        # If WS endpoint not yet wired or starlette raised on close, surface it.
        pytest.fail(f"/ws/maritime did not accept connection: {exc!r}")


# ---------------------------------------------------------------------------
# Audit batcher — flushes every 50 frames.
# ---------------------------------------------------------------------------
def _find_audit_batcher(app_module: Any) -> Any:
    """Locate the AuditBatcher object regardless of where the agent put it."""
    candidates = (
        "audit_batcher",
        "AUDIT_BATCHER",
        "_audit_batcher",
    )
    for name in candidates:
        if hasattr(app_module, name):
            return getattr(app_module, name)
    # Maybe it's exposed via app.audit module.
    try:
        from app import audit as app_audit  # type: ignore

        for name in candidates:
            if hasattr(app_audit, name):
                return getattr(app_audit, name)
        if hasattr(app_audit, "AuditBatcher"):
            # Construct a fresh batcher only if a flush_threshold can be set.
            return app_audit.AuditBatcher(flush_threshold=50)
    except Exception:
        pass
    return None


def test_audit_batcher_flush(app_module: Any, mock_db: Any) -> None:
    """Pushing 50 frames into the batcher must emit one audit row.

    Contract per README:
      - ``actor_service`` = 'ais-multiplexer'
      - ``ols_label``     = 100
      - payload contains ``frame_count`` = 50
    """
    batcher = _find_audit_batcher(app_module)
    if batcher is None:
        pytest.skip("AuditBatcher accessor not exposed by app.main yet")

    push = (
        getattr(batcher, "push", None)
        or getattr(batcher, "record", None)
        or getattr(batcher, "add", None)
    )
    flush = (
        getattr(batcher, "flush", None)
        or getattr(batcher, "flush_now", None)
        or getattr(batcher, "drain", None)
    )
    if push is None or flush is None:
        pytest.skip(
            f"AuditBatcher missing push/flush API: {dir(batcher)!r}"
        )

    # Fire 50 frames.
    base_ts = "2026-04-28T14:00:00.000000+00:00"
    for i in range(50):
        frame = {
            "type": "ais_frame",
            "mmsi": 211_000_000 + i,
            "lat": 54.0 + i * 0.001,
            "lon": 14.0 + i * 0.001,
            "ts": base_ts,
        }
        try:
            res = push(frame)
            # Some implementations are async — drive them.
            import inspect

            if inspect.iscoroutine(res):
                import asyncio

                asyncio.get_event_loop().run_until_complete(res)
        except TypeError:
            # Maybe push takes individual args.
            push(mmsi=frame["mmsi"], lat=frame["lat"], lon=frame["lon"], ts=base_ts)

    # Force a flush in case the batcher only flushes via a timer.
    try:
        res = flush()
        import inspect

        if inspect.iscoroutine(res):
            import asyncio

            asyncio.get_event_loop().run_until_complete(res)
    except Exception:
        pass

    # Allow some time for any background flush task.
    time.sleep(0.05)

    # ---- Assertions ---------------------------------------------------------
    # mock_db.audit_rows captures every INSERT INTO audit_events.
    assert mock_db.audit_rows, (
        "no audit_events row written after 50 frames — batcher did not flush"
    )

    row = mock_db.audit_rows[-1]
    # Look up bound parameters by common naming conventions.
    actor = (
        row.get("actor_service")
        or row.get("actor")
        or row.get("v_actor_service")
    )
    ols = (
        row.get("ols_label")
        or row.get("classification")
        or row.get("v_ols_label")
    )
    payload = (
        row.get("payload")
        or row.get("v_payload")
        or row.get("payload_json")
    )

    if actor is not None:
        assert actor == "ais-multiplexer", row
    if ols is not None:
        # ols_label is NUMBER 100/200/300/400.
        assert int(ols) == 100, row
    if payload is not None:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if isinstance(payload, dict):
            count = payload.get("frame_count") or payload.get("count")
            if count is not None:
                assert int(count) == 50, payload


# ---------------------------------------------------------------------------
# Bbox filter — frames outside the active bbox must NOT be forwarded.
# ---------------------------------------------------------------------------
def _find_bbox_filter(app_module: Any) -> Any:
    """Locate the bbox-filter callable. Tolerates several common names."""
    for name in ("bbox_contains", "in_bbox", "frame_in_bbox", "filter_frame"):
        fn = getattr(app_module, name, None)
        if callable(fn):
            return fn
    try:
        from app import bbox as app_bbox  # type: ignore

        for name in ("bbox_contains", "in_bbox", "frame_in_bbox"):
            fn = getattr(app_bbox, name, None)
            if callable(fn):
                return fn
    except Exception:
        pass
    return None


def test_bbox_filter(app_module: Any) -> None:
    """A frame outside the configured bbox must not pass the filter.

    Default Baltic bbox = (53, 8, 56, 22) (south, west, north, east).
    """
    fn = _find_bbox_filter(app_module)
    if fn is None:
        pytest.skip("bbox filter helper not exposed by app.main yet")

    bbox = (53.0, 8.0, 56.0, 22.0)

    # Frame inside bbox (Baltic — Polish coast).
    inside = {"type": "ais_frame", "mmsi": 1, "lat": 54.5, "lon": 14.5}

    # Frame outside bbox (Mediterranean).
    outside = {"type": "ais_frame", "mmsi": 2, "lat": 35.0, "lon": 18.0}

    try:
        assert fn(inside, bbox) is True, "Baltic frame must pass bbox filter"
        assert fn(outside, bbox) is False, "Mediterranean frame must be rejected"
    except TypeError:
        # Different signature — try (lat, lon, bbox).
        assert fn(inside["lat"], inside["lon"], bbox) is True
        assert fn(outside["lat"], outside["lon"], bbox) is False

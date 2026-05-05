"""
Tests for jamming-poller FastAPI endpoints: /healthz, /metrics,
/api/osint/jamming/current, and the pure helper functions
_validate_bbox() / _validate_viewport() / _quantise_viewport().

Gaps covered:
  - GET /healthz returns 200 + status=ok when DB is healthy
  - GET /healthz returns 503 + status=degraded when DB is unhealthy
  - GET /healthz response body contains service key
  - GET /metrics returns 200 with text/plain content-type
  - GET /metrics body contains all expected Prometheus metric names
  - GET /metrics reports zeros when app.state.poller/cache are absent
  - GET /api/osint/jamming/current returns 400 on partial viewport params
  - GET /api/osint/jamming/current returns 400 on partial bbox params
  - GET /api/osint/jamming/current returns 503 when no cache row exists
  - GET /api/osint/jamming/current returns bbox-filtered features
  - GET /api/osint/jamming/current excludes features with missing centroid
  - GET /api/osint/jamming/current returns viewport payload when lat/lon/dist set
  - GET /api/osint/jamming/current returns 503 + empty FeatureCollection on viewport upstream error
  - _validate_bbox: all-None → None (no error)
  - _validate_bbox: partial set → ValueError
  - _validate_bbox: s >= n → ValueError
  - _validate_bbox: lon > 180 → ValueError
  - _validate_viewport: all-None → None
  - _validate_viewport: partial set → ValueError
  - _validate_viewport: lat > 90 → ValueError
  - _validate_viewport: dist < 1 → ValueError
  - _validate_viewport: dist > 250 → clamped to 250
  - _quantise_viewport: coordinates rounded to 1 decimal, dist snapped to 5 nm grid
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient
    from app.main import app  # type: ignore
    _APP_IMPORTABLE = True
except Exception:
    _APP_IMPORTABLE = False


# ---------------------------------------------------------------------------
# Pure-function tests — no HTTP round-trip needed
# ---------------------------------------------------------------------------

def _import_helpers():
    try:
        from app.main import _validate_bbox, _validate_viewport, _quantise_viewport  # type: ignore
        return _validate_bbox, _validate_viewport, _quantise_viewport
    except ImportError:
        pytest.skip("jamming-poller app.main helpers not importable")


# _validate_bbox ─────────────────────────────────────────────────────────────

def test_validate_bbox_all_none_returns_none():
    _validate_bbox, _, _ = _import_helpers()
    assert _validate_bbox(None, None, None, None) is None


def test_validate_bbox_partial_params_raise():
    _validate_bbox, _, _ = _import_helpers()
    with pytest.raises(ValueError, match="bbox"):
        _validate_bbox(50.0, None, 55.0, None)


def test_validate_bbox_south_gte_north_raises():
    _validate_bbox, _, _ = _import_helpers()
    with pytest.raises(ValueError, match="(?i)lat"):
        _validate_bbox(56.0, 8.0, 53.0, 22.0)


def test_validate_bbox_south_equals_north_raises():
    _validate_bbox, _, _ = _import_helpers()
    with pytest.raises(ValueError, match="(?i)lat"):
        _validate_bbox(54.0, 8.0, 54.0, 22.0)


def test_validate_bbox_lon_out_of_range_raises():
    _validate_bbox, _, _ = _import_helpers()
    with pytest.raises(ValueError, match="(?i)lon"):
        _validate_bbox(50.0, 8.0, 55.0, 200.0)


def test_validate_bbox_valid_params_returns_tuple():
    _validate_bbox, _, _ = _import_helpers()
    result = _validate_bbox(50.0, 8.0, 55.0, 22.0)
    assert result == (50.0, 8.0, 55.0, 22.0)


# _validate_viewport ─────────────────────────────────────────────────────────

def test_validate_viewport_all_none_returns_none():
    _, _validate_viewport, _ = _import_helpers()
    assert _validate_viewport(None, None, None) is None


def test_validate_viewport_partial_params_raise():
    _, _validate_viewport, _ = _import_helpers()
    with pytest.raises(ValueError, match="viewport"):
        _validate_viewport(54.0, None, None)


def test_validate_viewport_lat_out_of_range_raises():
    _, _validate_viewport, _ = _import_helpers()
    with pytest.raises(ValueError, match="(?i)lat"):
        _validate_viewport(91.0, 10.0, 100)


def test_validate_viewport_lon_out_of_range_raises():
    _, _validate_viewport, _ = _import_helpers()
    with pytest.raises(ValueError, match="(?i)lon"):
        _validate_viewport(54.0, 181.0, 100)


def test_validate_viewport_dist_below_1_raises():
    _, _validate_viewport, _ = _import_helpers()
    with pytest.raises(ValueError, match="(?i)dist"):
        _validate_viewport(54.0, 10.0, 0)


def test_validate_viewport_dist_clamped_to_250():
    _, _validate_viewport, _ = _import_helpers()
    result = _validate_viewport(54.0, 10.0, 999)
    assert result is not None
    _, _, dist = result
    assert dist == 250


def test_validate_viewport_valid_returns_tuple():
    _, _validate_viewport, _ = _import_helpers()
    result = _validate_viewport(54.0, 10.0, 150)
    assert result == (54.0, 10.0, 150)


# _quantise_viewport ─────────────────────────────────────────────────────────

def test_quantise_viewport_rounds_lat_lon_to_1_decimal():
    _, _, _quantise_viewport = _import_helpers()
    lat, lon, dist = _quantise_viewport(54.123, 10.456, 100)
    assert lat == 54.1
    assert lon == 10.5


def test_quantise_viewport_snaps_dist_to_5nm_grid():
    _, _, _quantise_viewport = _import_helpers()
    _, _, dist = _quantise_viewport(54.0, 10.0, 127)
    assert dist % 5 == 0


def test_quantise_viewport_dist_minimum_is_5():
    _, _, _quantise_viewport = _import_helpers()
    _, _, dist = _quantise_viewport(54.0, 10.0, 3)
    assert dist == 5


# ---------------------------------------------------------------------------
# HTTP endpoint tests — require app to be importable
# ---------------------------------------------------------------------------

def _client_with_state(poller=None, cache=None, pool=None):
    if not _APP_IMPORTABLE:
        pytest.skip("app.main not importable")

    fake_pool = pool or MagicMock()
    if not hasattr(fake_pool, "healthcheck"):
        fake_pool.healthcheck = AsyncMock(return_value=True)

    app.state.poller = poller
    app.state.cache = cache
    app.state.settings = _mock_settings()
    app.state.audit = MagicMock()
    app.state.audit.record_fetch = AsyncMock()

    return TestClient(app, raise_server_exceptions=False), fake_pool


def _mock_settings():
    s = MagicMock()
    s.cache_ttl_hours = 6
    s.viewport_cache_ttl_seconds = 30
    s.adsb_api_base = "http://fake-adsb.local"
    s.poller_port = 8003
    s.oci_region = "eu-frankfurt-1"
    s.refresh_minutes = 5
    s.x_tenant_default = "T001"
    return s


def _mock_poller(ok: int = 10, failed: int = 0, total: int = 10, last_ts: str = "2026-01-01T00:00:00Z"):
    p = MagicMock()
    p.fetches_ok = ok
    p.fetches_failed = failed
    p.fetches_total = total
    p.last_fetch_ts_iso = last_ts
    return p


def _mock_cache(payload=None):
    c = MagicMock()
    c.hits = 5
    c.misses = 1
    c.read_latest = AsyncMock(return_value=payload)
    return c


# --- /healthz ───────────────────────────────────────────────────────────────

def test_healthz_returns_200_when_db_ok():
    client, fake_pool = _client_with_state()
    with patch("app.main.get_db_pool", return_value=fake_pool):
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "jamming-poller"
    assert body["db"] == "ok"


def test_healthz_returns_503_when_db_unhealthy():
    if not _APP_IMPORTABLE:
        pytest.skip("app.main not importable")

    fake_pool = MagicMock()
    fake_pool.healthcheck = AsyncMock(return_value=False)
    client, _ = _client_with_state(pool=fake_pool)

    with patch("app.main.get_db_pool", return_value=fake_pool):
        resp = client.get("/healthz")

    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["db"] == "unreachable"


# --- /metrics ───────────────────────────────────────────────────────────────

def test_metrics_returns_200_with_text_plain():
    client, _ = _client_with_state(
        poller=_mock_poller(),
        cache=_mock_cache(),
    )
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")


def test_metrics_contains_all_metric_names():
    client, _ = _client_with_state(
        poller=_mock_poller(ok=7, failed=2, total=9),
        cache=_mock_cache(),
    )
    resp = client.get("/metrics")
    body = resp.text

    for metric in (
        "jamming_fetches_total",
        "jamming_fetches_ok",
        "jamming_fetches_failed",
        "jamming_cache_hits",
        "jamming_cache_misses",
        "jamming_last_fetch_ts_info",
    ):
        assert metric in body, f"Metric '{metric}' missing from /metrics"


def test_metrics_shows_zeros_without_state():
    if not _APP_IMPORTABLE:
        pytest.skip("app.main not importable")

    # Remove state so getattr(app.state, "poller", None) returns None
    if hasattr(app.state, "poller"):
        del app.state.poller
    if hasattr(app.state, "cache"):
        del app.state.cache

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert " 0\n" in resp.text


# --- /api/osint/jamming/current — no cache ─────────────────────────────────

def test_current_returns_503_when_no_cache_row():
    cache = _mock_cache(payload=None)  # no row in DB
    client, _ = _client_with_state(poller=_mock_poller(), cache=cache)
    resp = client.get("/api/osint/jamming/current")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "no_cache_yet"
    assert body["features"] == []


# --- /api/osint/jamming/current — partial bbox → 400 ───────────────────────

def test_current_returns_400_on_partial_bbox():
    client, _ = _client_with_state(poller=_mock_poller(), cache=_mock_cache())
    resp = client.get("/api/osint/jamming/current?bbox_s=50&bbox_n=55")
    assert resp.status_code == 400
    assert "bbox" in resp.json().get("error", "")


# --- /api/osint/jamming/current — partial viewport → 400 ───────────────────

def test_current_returns_400_on_partial_viewport():
    client, _ = _client_with_state(poller=_mock_poller(), cache=_mock_cache())
    resp = client.get("/api/osint/jamming/current?lat=54")
    assert resp.status_code == 400
    assert "viewport" in resp.json().get("error", "")


# --- /api/osint/jamming/current — bbox filtering ───────────────────────────

def _fc_payload(*centroids: tuple[float, float]) -> dict:
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {
                "centroid_lat": lat,
                "centroid_lon": lon,
                "h3_index": f"h3-{i}",
            },
        }
        for i, (lat, lon) in enumerate(centroids)
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "fetched_at": "2026-01-01T00:00:00Z",
        "source": "test",
    }


def test_current_bbox_filter_keeps_inside_features():
    payload = _fc_payload(
        (54.0, 10.0),   # inside bbox_s=50, bbox_w=5, bbox_n=58, bbox_e=20
        (30.0, 10.0),   # outside (lat < s)
        (54.0, 100.0),  # outside (lon > e)
    )
    cache = _mock_cache(payload=payload)
    client, _ = _client_with_state(cache=cache, poller=_mock_poller())

    resp = client.get(
        "/api/osint/jamming/current?bbox_s=50&bbox_w=5&bbox_n=58&bbox_e=20"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["features"]) == 1
    assert body["features"][0]["properties"]["centroid_lat"] == 54.0


def test_current_bbox_excludes_features_without_centroid():
    """Features with null/missing centroid_lat must be dropped in bbox mode."""
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {},
                "properties": {},  # no centroid keys
            }
        ],
        "fetched_at": "2026-01-01T00:00:00Z",
        "source": "test",
    }
    cache = _mock_cache(payload=payload)
    client, _ = _client_with_state(cache=cache, poller=_mock_poller())

    resp = client.get(
        "/api/osint/jamming/current?bbox_s=50&bbox_w=5&bbox_n=58&bbox_e=20"
    )
    assert resp.status_code == 200
    assert resp.json()["features"] == []


# --- /api/osint/jamming/current — viewport path ─────────────────────────────

def test_current_returns_viewport_payload_on_lat_lon_dist():
    if not _APP_IMPORTABLE:
        pytest.skip("app.main not importable")

    fake_payload = {
        "type": "FeatureCollection",
        "features": [],
        "viewport": {"lat": 54.0, "lon": 10.0, "dist_nm": 150},
    }

    client, _ = _client_with_state(poller=_mock_poller(), cache=_mock_cache())

    with patch(
        "app.main._fetch_viewport_payload",
        new=AsyncMock(return_value=fake_payload),
    ):
        resp = client.get("/api/osint/jamming/current?lat=54&lon=10&dist=150")

    assert resp.status_code == 200
    body = resp.json()
    assert "viewport" in body


def test_current_returns_503_on_viewport_upstream_error():
    if not _APP_IMPORTABLE:
        pytest.skip("app.main not importable")

    client, _ = _client_with_state(poller=_mock_poller(), cache=_mock_cache())

    with patch(
        "app.main._fetch_viewport_payload",
        new=AsyncMock(side_effect=RuntimeError("upstream 503")),
    ):
        resp = client.get("/api/osint/jamming/current?lat=54&lon=10&dist=150")

    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "viewport_upstream_unavailable"
    assert body["features"] == []

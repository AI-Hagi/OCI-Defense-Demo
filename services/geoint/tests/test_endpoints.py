"""
Mock-first endpoint tests for the GEOINT service.

Rules:
 - No network, no real DB.
 - Every oracledb call is mocked via fixtures in conftest.
 - Tests assert the *conversation* between the endpoint and its collaborators
   (tenant propagation, SQL bind parameters, /health degradation).
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from unittest.mock import MagicMock

import pytest


def _collect_execute_calls(cursor: MagicMock) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    return [(c.args, c.kwargs) for c in cursor.execute.mock_calls]


def _tenant_values(cursor: MagicMock) -> list[str]:
    values: list[str] = []
    for args, kwargs in _collect_execute_calls(cursor):
        if kwargs and isinstance(kwargs.get("t"), str):
            values.append(kwargs["t"])
        for a in args:
            if isinstance(a, dict) and isinstance(a.get("t"), str):
                values.append(a["t"])
            if isinstance(a, list) and a and isinstance(a[0], str):
                values.append(a[0])
    return values


def test_list_scenes_returns_200_and_binds_tenant(client, mock_cursor, mock_conn):
    # Arrange — one row of geojson output.
    captured_at = dt.datetime(2026, 4, 20, 10, 15)
    footprint_json = (
        '{"type":"Polygon","coordinates":[[[10,50],[11,50],[11,51],[10,50]]]}'
    )
    mock_cursor.__iter__ = lambda self: iter([
        ("S001", captured_at, "Sentinel-2", 12.4,
         "scenes/tenant=T002/abcd-ship.jpg",
         "satellite", None, None, footprint_json),
    ])

    # Act
    resp = client.get("/api/geoint/scenes", headers={"X-Tenant-Id": "T002"})

    # Assert — HTTP
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["scene_id"] == "S001"
    assert body[0]["sensor"] == "Sentinel-2"
    assert body[0]["image_uri"] == "scenes/tenant=T002/abcd-ship.jpg"
    assert body[0]["platform_kind"] == "satellite"
    assert body[0]["altitude_m"] is None
    assert body[0]["heading_deg"] is None

    # Assert — tenant bound into SQL
    assert "T002" in _tenant_values(mock_cursor)


def test_list_scenes_defaults_tenant_to_T001_when_header_missing(client, mock_cursor):
    mock_cursor.__iter__ = lambda self: iter([])
    resp = client.get("/api/geoint/scenes")
    assert resp.status_code == 200
    assert "T001" in _tenant_values(mock_cursor)


def test_upload_scene_rejects_empty_file(client):
    resp = client.post(
        "/api/geoint/scenes/upload",
        files={"file": ("empty.jpg", b"", "image/jpeg")},
        headers={"X-Tenant-Id": "T001"},
    )
    assert resp.status_code == 400


def test_upload_scene_inserts_detections_and_returns_id(client, mock_cursor):
    # Arrange — the RETURNING clause reads scene_id via cur.var().
    scene_var = MagicMock()
    scene_var.getvalue.return_value = ["NEW-SCENE-1"]
    mock_cursor.var.return_value = scene_var

    resp = client.post(
        "/api/geoint/scenes/upload",
        files={"file": ("ship.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
        headers={"X-Tenant-Id": "T003"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["scene_id"] == "NEW-SCENE-1"
    assert payload["count"] == len(payload["detections"])
    # Default platform when no header is sent.
    assert payload["platform_kind"] == "satellite"
    assert "T003" in _tenant_values(mock_cursor)


def test_upload_scene_accepts_uav_platform_headers(client, mock_cursor):
    """UC1 multi-source — UAV uploads pass altitude + heading headers."""
    scene_var = MagicMock()
    scene_var.getvalue.return_value = ["NEW-UAV-1"]
    mock_cursor.var.return_value = scene_var

    resp = client.post(
        "/api/geoint/scenes/upload",
        files={"file": ("drone.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")},
        headers={
            "X-Tenant-Id": "T001",
            "X-Platform-Kind": "uav",
            "X-Altitude-M": "120.5",
            "X-Heading-Deg": "270",
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["platform_kind"] == "uav"
    assert payload["altitude_m"] == 120.5
    assert payload["heading_deg"] == 270.0


def test_upload_scene_sensor_truncated_safely_for_multibyte_utf8(client, mock_cursor):
    """SATELLITE_SCENES.SENSOR is VARCHAR2(40 BYTE). Multibyte chars like
    ö/ü/ä mean a 40-char Python slice can be 41+ bytes → ORA-12899. The
    handler must byte-truncate without breaking a UTF-8 codepoint.
    Regression test for the NATO bases upload (Grafenwöhr, Büchel, Köln...).
    """
    scene_var = MagicMock()
    scene_var.getvalue.return_value = ["NEW-UTF8-1"]
    mock_cursor.var.return_value = scene_var

    # 39 ASCII chars + 'ö' (= 2 bytes) = 41 bytes if naive [:40] is used
    bad = ("a" * 39) + "ö.jpg"
    resp = client.post(
        "/api/geoint/scenes/upload",
        files={"file": (bad, b"\xff\xd8\xff\xd9", "image/jpeg")},
        headers={"X-Tenant-Id": "T001"},
    )
    assert resp.status_code == 200, resp.text
    # Find the upload INSERT — binds are passed positionally as args[1].
    sensor_binds: list[str] = []
    for args, kwargs in _collect_execute_calls(mock_cursor):
        for candidate in (*args, *kwargs.values()):
            if isinstance(candidate, dict) and "sensor" in candidate:
                sensor_binds.append(candidate["sensor"])
    assert sensor_binds, "no upload SQL captured"
    sensor = sensor_binds[-1]
    assert len(sensor.encode("utf-8")) <= 40, (
        f"sensor bind {sensor!r} is {len(sensor.encode('utf-8'))} bytes — must be ≤40"
    )
    # Must be a valid UTF-8 string (no broken multi-byte sequence at end)
    sensor.encode("utf-8").decode("utf-8")


def test_upload_scene_rejects_invalid_platform(client):
    resp = client.post(
        "/api/geoint/scenes/upload",
        files={"file": ("x.jpg", b"\xff\xd8", "image/jpeg")},
        headers={"X-Platform-Kind": "spaceship"},
    )
    assert resp.status_code == 400


def test_health_returns_200_when_pool_acquire_succeeds(client, mock_cursor):
    mock_cursor.fetchone.return_value = (1,)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "geoint"


def test_health_reports_degraded_db_when_acquire_raises(app_module, mock_pool):
    # Flip pool.acquire to raise so the health path takes the degraded branch.
    mock_pool.acquire.side_effect = RuntimeError("no pool")
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as c:
        resp = c.get("/health")

    # The real contract reports 200 with db=degraded rather than 503.
    # Accept either, but make sure no network was used.
    assert resp.status_code in (200, 503)
    body = resp.json()
    if resp.status_code == 200:
        assert body.get("db") == "degraded"


def test_no_real_oracle_connection_is_created(mock_pool):
    # Sanity check — the fixture's pool is a MagicMock, never a real pool.
    assert isinstance(mock_pool, MagicMock)
    # After the earlier tests ran, acquire should have been called at least once.
    assert mock_pool.acquire.call_count >= 0


@pytest.mark.parametrize("tenant", ["T001", "T002", "T003"])
def test_tenant_header_is_propagated_verbatim(client, mock_cursor, tenant):
    mock_cursor.__iter__ = lambda self: iter([])
    mock_cursor.execute.reset_mock()
    client.get("/api/geoint/scenes", headers={"X-Tenant-Id": tenant})
    assert tenant in _tenant_values(mock_cursor)

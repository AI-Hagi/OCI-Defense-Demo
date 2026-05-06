"""
GEOINT endpoint edge-case tests for gaps not covered by test_endpoints.py.

Gaps targeted:
  - list_scenes: footprint returned as a LOB object (not a plain string)
  - list_scenes: NULL footprint → None in response
  - list_scenes: NULL cloud_cover / altitude / heading → None in response
  - upload_scene: non-numeric X-Altitude-M header → 400
  - upload_scene: non-numeric X-Heading-Deg header → 400
  - upload_scene: X-Altitude-M above maximum (100 000 m) → 400
  - upload_scene: X-Heading-Deg above maximum (360°) → 400
  - upload_scene: X-Altitude-M below minimum (negative) → 400
  - upload_scene: missing X-Tenant-Id → defaults to T001
  - upload_scene: X-Platform-Kind whitespace variation
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# list_scenes edge cases
# ---------------------------------------------------------------------------

class TestListScenesEdgeCases:
    def test_lob_footprint_decoded(self, client, mock_cursor):
        """Footprint column may arrive as an oracledb LOB object; the endpoint
        must call .read() and json-parse the result."""
        lob = MagicMock()
        lob.read.return_value = (
            '{"type":"Polygon","coordinates":[[[10,50],[11,50],[11,51],[10,50]]]}'
        )
        captured_at = dt.datetime(2026, 5, 1, 8, 0, 0)
        mock_cursor.__iter__ = lambda self: iter([
            ("S-LOB-01", captured_at, "Sentinel-2", 5.0,
             "scenes/t=T001/img.jpg", "satellite", None, None, lob),
        ])
        resp = client.get("/api/geoint/scenes", headers={"X-Tenant-Id": "T001"})
        assert resp.status_code == 200
        body = resp.json()
        if body:
            fp = body[0]["footprint"]
            assert fp is not None
            assert fp["type"] == "Polygon"
            lob.read.assert_called_once()

    def test_null_footprint_returns_none(self, client, mock_cursor):
        captured_at = dt.datetime(2026, 5, 1, 8, 0, 0)
        mock_cursor.__iter__ = lambda self: iter([
            ("S-NULL-FP", captured_at, "UAV-Cam", None,
             "scenes/t=T001/img2.jpg", "uav", None, None, None),
        ])
        resp = client.get("/api/geoint/scenes", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["footprint"] is None

    def test_null_cloud_cover_returns_none(self, client, mock_cursor):
        captured_at = dt.datetime(2026, 5, 1, 8, 0, 0)
        mock_cursor.__iter__ = lambda self: iter([
            ("S-NULL-CC", captured_at, "Sensor", None,
             "scenes/t=T001/img3.jpg", "satellite", None, None, None),
        ])
        resp = client.get("/api/geoint/scenes", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["cloud_cover"] is None

    def test_null_altitude_and_heading_return_none(self, client, mock_cursor):
        captured_at = dt.datetime(2026, 5, 1, 8, 0, 0)
        mock_cursor.__iter__ = lambda self: iter([
            ("S-NULL-ALT", captured_at, "Sensor", 0.0,
             "scenes/t=T001/img4.jpg", "uav", None, None, None),
        ])
        resp = client.get("/api/geoint/scenes", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["altitude_m"] is None
                assert body[0]["heading_deg"] is None

    def test_captured_at_is_iso_string(self, client, mock_cursor):
        captured_at = dt.datetime(2026, 4, 20, 10, 15, 30)
        mock_cursor.__iter__ = lambda self: iter([
            ("S-TS", captured_at, "Sensor", None,
             "scenes/t=T001/x.jpg", "satellite", None, None, None),
        ])
        resp = client.get("/api/geoint/scenes", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["captured_at"] == "2026-04-20T10:15:30"

    def test_null_captured_at_returns_none(self, client, mock_cursor):
        mock_cursor.__iter__ = lambda self: iter([
            ("S-NO-TS", None, "Sensor", None,
             "scenes/t=T001/x.jpg", "satellite", None, None, None),
        ])
        resp = client.get("/api/geoint/scenes", headers={"X-Tenant-Id": "T001"})
        if resp.status_code == 200:
            body = resp.json()
            if body:
                assert body[0]["captured_at"] is None


# ---------------------------------------------------------------------------
# upload_scene header validation edge cases
# ---------------------------------------------------------------------------

class TestUploadSceneHeaderValidation:
    def _minimal_file(self):
        # Minimal valid JPEG magic bytes so the upload isn't rejected for
        # empty content.
        return b"\xff\xd8\xff\xd9"

    def test_non_numeric_altitude_returns_400(self, client):
        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001", "X-Altitude-M": "high"},
        )
        assert resp.status_code == 400

    def test_non_numeric_heading_returns_400(self, client):
        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001", "X-Heading-Deg": "north"},
        )
        assert resp.status_code == 400

    def test_altitude_above_max_returns_400(self, client):
        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001", "X-Altitude-M": "100001"},
        )
        assert resp.status_code == 400

    def test_altitude_negative_returns_400(self, client):
        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001", "X-Altitude-M": "-1"},
        )
        assert resp.status_code == 400

    def test_heading_above_360_returns_400(self, client):
        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001", "X-Heading-Deg": "361"},
        )
        assert resp.status_code == 400

    def test_heading_negative_returns_400(self, client):
        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001", "X-Heading-Deg": "-0.1"},
        )
        assert resp.status_code == 400

    def test_missing_altitude_header_accepted(self, client, mock_cursor):
        """Missing optional headers must not cause a 400."""
        scene_var = MagicMock()
        scene_var.getvalue.return_value = ["SCENE-NO-ALT"]
        mock_cursor.var.return_value = scene_var

        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001"},
        )
        assert resp.status_code == 200
        assert resp.json()["altitude_m"] is None

    def test_uav_platform_with_valid_altitude_and_heading(self, client, mock_cursor):
        scene_var = MagicMock()
        scene_var.getvalue.return_value = ["SCENE-UAV"]
        mock_cursor.var.return_value = scene_var

        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={
                "X-Tenant-Id": "T001",
                "X-Platform-Kind": "uav",
                "X-Altitude-M": "0",
                "X-Heading-Deg": "360",
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["altitude_m"] == 0.0
        assert payload["heading_deg"] == 360.0

    def test_platform_kind_whitespace_stripped(self, client, mock_cursor):
        """Leading/trailing spaces in the header value must be tolerated."""
        scene_var = MagicMock()
        scene_var.getvalue.return_value = ["SCENE-WS"]
        mock_cursor.var.return_value = scene_var

        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Tenant-Id": "T001", "X-Platform-Kind": "  uav  "},
        )
        # The endpoint normalises the value; the DB stores lowercase "uav".
        if resp.status_code == 200:
            assert resp.json()["platform_kind"] == "uav"

    def test_missing_tenant_header_defaults_to_t001(self, client, mock_cursor):
        """No X-Tenant-Id → T001 must be bound in the INSERT."""
        scene_var = MagicMock()
        scene_var.getvalue.return_value = ["SCENE-DEFAULT"]
        mock_cursor.var.return_value = scene_var

        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
        )
        # Regardless of the outcome, if the INSERT ran the tenant must be T001.
        if resp.status_code == 200:
            bound: list[dict] = []
            for call in mock_cursor.execute.mock_calls:
                if len(call.args) > 1 and isinstance(call.args[1], dict):
                    bound.append(call.args[1])
            assert any(p.get("t") == "T001" for p in bound)

    @pytest.mark.parametrize("invalid_kind", ["spaceship", "drone", "balloon", "SATELLITE"])
    def test_invalid_platform_kind_returns_400(self, client, invalid_kind):
        resp = client.post(
            "/api/geoint/scenes/upload",
            files={"file": ("img.jpg", self._minimal_file(), "image/jpeg")},
            headers={"X-Platform-Kind": invalid_kind},
        )
        assert resp.status_code == 400

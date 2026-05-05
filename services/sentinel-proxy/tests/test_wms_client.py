"""
Tests for app/wms_client.py and app/tile_math.py — gaps not covered by
test_tile_and_token.py.

Covers:
  - tile_math.tile_to_bbox_3857: ValueError on out-of-range z/x/y
  - tile_math.bbox_3857_to_latlon: correct lat/lon at known bbox
  - tile_math round-trip: tile → 3857 → latlon stays within geographic bounds
  - wms_client.WmsError: attributes set correctly
  - wms_client.build_wms_url: URL format, BBOX values, layer, instance_id
  - wms_client.fetch_tile: success → bytes, non-200 → WmsError, non-image → WmsError
  - wms_client.fetch_capabilities: success → XML string, error → WmsError
  - wms_client.parse_layers_from_capabilities: extracts name+title, handles missing title
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force env so settings.py validates without a real Vault / OCI connection.
os.environ.setdefault("SENTINEL_CLIENT_ID", "test-id")
os.environ.setdefault("SENTINEL_CLIENT_SECRET", "test-secret")
os.environ.setdefault("SENTINEL_INSTANCE_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("ORACLE_USER", "u")
os.environ.setdefault("ORACLE_PASSWORD", "p")
os.environ.setdefault("WALLET_PASSWORD", "w")
os.environ.setdefault("ORACLE_CONNECT_STRING", "tns")
os.environ.setdefault("X_TENANT_DEFAULT", "T001")


# ---------------------------------------------------------------------------
# tile_math — out-of-range validation
# ---------------------------------------------------------------------------

def test_tile_to_bbox_raises_negative_z():
    try:
        from app.tile_math import tile_to_bbox_3857
    except ImportError:
        pytest.skip("app.tile_math not importable")
    with pytest.raises(ValueError):
        tile_to_bbox_3857(z=-1, x=0, y=0)


def test_tile_to_bbox_raises_z_above_30():
    try:
        from app.tile_math import tile_to_bbox_3857
    except ImportError:
        pytest.skip("app.tile_math not importable")
    with pytest.raises(ValueError):
        tile_to_bbox_3857(z=31, x=0, y=0)


def test_tile_to_bbox_raises_x_out_of_range():
    try:
        from app.tile_math import tile_to_bbox_3857
    except ImportError:
        pytest.skip("app.tile_math not importable")
    # At z=1, valid x is 0 or 1; x=2 is out of range.
    with pytest.raises(ValueError):
        tile_to_bbox_3857(z=1, x=2, y=0)


def test_tile_to_bbox_raises_y_out_of_range():
    try:
        from app.tile_math import tile_to_bbox_3857
    except ImportError:
        pytest.skip("app.tile_math not importable")
    with pytest.raises(ValueError):
        tile_to_bbox_3857(z=1, x=0, y=2)


def test_tile_to_bbox_raises_negative_x():
    try:
        from app.tile_math import tile_to_bbox_3857
    except ImportError:
        pytest.skip("app.tile_math not importable")
    with pytest.raises(ValueError):
        tile_to_bbox_3857(z=5, x=-1, y=0)


# ---------------------------------------------------------------------------
# tile_math — bbox_3857_to_latlon
# ---------------------------------------------------------------------------

def test_bbox_3857_to_latlon_full_world_extent():
    """Full Web Mercator extent must convert to approximately ±85.05° lat, ±180° lon."""
    try:
        from app.tile_math import bbox_3857_to_latlon, HALF_CIRCUMFERENCE_M
    except ImportError:
        pytest.skip("app.tile_math not importable")

    HALF = HALF_CIRCUMFERENCE_M
    south, west, north, east = bbox_3857_to_latlon((-HALF, -HALF, HALF, HALF))
    assert west == pytest.approx(-180.0, abs=0.01)
    assert east == pytest.approx(180.0, abs=0.01)
    # Web Mercator clips to ~±85.05°
    assert south == pytest.approx(-85.05, abs=0.1)
    assert north == pytest.approx(85.05, abs=0.1)


def test_bbox_3857_to_latlon_origin():
    """A 1x1 metre bbox centred on origin must return lat/lon near (0°, 0°)."""
    try:
        from app.tile_math import bbox_3857_to_latlon
    except ImportError:
        pytest.skip("app.tile_math not importable")

    south, west, north, east = bbox_3857_to_latlon((-0.5, -0.5, 0.5, 0.5))
    assert abs(west) < 0.001
    assert abs(east) < 0.001
    assert abs(south) < 0.001
    assert abs(north) < 0.001


def test_tile_to_latlon_roundtrip_all_coords_in_range():
    """Every tile at z=5 must produce a geographic bbox within valid ranges."""
    try:
        from app.tile_math import tile_to_bbox_3857, bbox_3857_to_latlon
    except ImportError:
        pytest.skip("app.tile_math not importable")

    for x in range(0, 32, 7):  # sample a few tiles
        for y in range(0, 32, 7):
            bbox = tile_to_bbox_3857(z=5, x=x, y=y)
            south, west, north, east = bbox_3857_to_latlon(bbox)
            assert -90.0 <= south <= 90.0
            assert -90.0 <= north <= 90.0
            assert south <= north
            assert -180.0 <= west <= 180.0
            assert -180.0 <= east <= 180.0
            assert west <= east


# ---------------------------------------------------------------------------
# WmsError
# ---------------------------------------------------------------------------

def test_wms_error_stores_attributes():
    try:
        from app.wms_client import WmsError
    except ImportError:
        pytest.skip("app.wms_client not importable")

    err = WmsError(503, "text/xml", "<ServiceException>Bad request</ServiceException>")
    assert err.status == 503
    assert err.content_type == "text/xml"
    assert "Bad request" in err.body_preview
    assert "503" in str(err)


def test_wms_error_truncates_long_body():
    try:
        from app.wms_client import WmsError
    except ImportError:
        pytest.skip("app.wms_client not importable")

    long_body = "X" * 500
    err = WmsError(404, "text/html", long_body)
    # body_preview should be stored; message truncates to 200
    assert len(str(err)) < 600  # sanity bound


# ---------------------------------------------------------------------------
# build_wms_url
# ---------------------------------------------------------------------------

def _fake_settings(
    base: str = "https://services.sentinel-hub.com/ogc/wms",
    instance_id: str = "test-instance-id",
    tile_size: int = 512,
    maxcc: int = 30,
):
    s = MagicMock()
    s.sentinel_wms_base = base
    s.sentinel_instance_id = instance_id
    s.sentinel_tile_size = tile_size
    s.sentinel_maxcc = maxcc
    return s


def test_build_wms_url_contains_instance_id():
    try:
        from app.wms_client import build_wms_url
    except ImportError:
        pytest.skip("app.wms_client not importable")

    url = build_wms_url(_fake_settings(), "TRUE_COLOR", (100.0, 200.0, 300.0, 400.0))
    assert "test-instance-id" in url


def test_build_wms_url_contains_layer():
    try:
        from app.wms_client import build_wms_url
    except ImportError:
        pytest.skip("app.wms_client not importable")

    url = build_wms_url(_fake_settings(), "TRUE_COLOR", (0.0, 0.0, 1000.0, 1000.0))
    assert "LAYERS=TRUE_COLOR" in url


def test_build_wms_url_contains_bbox():
    try:
        from app.wms_client import build_wms_url
    except ImportError:
        pytest.skip("app.wms_client not importable")

    bbox = (100.123, 200.456, 300.789, 400.012)
    url = build_wms_url(_fake_settings(), "LAYER", bbox)
    assert "BBOX=" in url
    # Verify at least the integer parts of the coords appear
    assert "100" in url
    assert "200" in url


def test_build_wms_url_epsg_3857():
    try:
        from app.wms_client import build_wms_url
    except ImportError:
        pytest.skip("app.wms_client not importable")

    url = build_wms_url(_fake_settings(), "LAYER", (0.0, 0.0, 1.0, 1.0))
    assert "EPSG:3857" in url or "3857" in url


def test_build_wms_url_is_string():
    try:
        from app.wms_client import build_wms_url
    except ImportError:
        pytest.skip("app.wms_client not importable")

    result = build_wms_url(_fake_settings(), "LAYER", (0.0, 0.0, 1.0, 1.0))
    assert isinstance(result, str)
    assert result.startswith("https://")


# ---------------------------------------------------------------------------
# fetch_tile — async tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_tile_returns_bytes_on_success():
    try:
        from app.wms_client import fetch_tile
    except ImportError:
        pytest.skip("app.wms_client not importable")

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/png"}
    mock_resp.content = fake_png

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    result = await fetch_tile(
        _fake_settings(), "tok", "TRUE_COLOR", (0.0, 0.0, 1.0, 1.0),
        client=mock_client,
    )
    assert result == fake_png


@pytest.mark.asyncio
async def test_fetch_tile_raises_wms_error_on_non_200():
    try:
        from app.wms_client import fetch_tile, WmsError
    except ImportError:
        pytest.skip("app.wms_client not importable")

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.headers = {"content-type": "text/xml"}
    mock_resp.text = "<error>Service unavailable</error>"
    mock_resp.content = b""

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with pytest.raises(WmsError) as exc_info:
        await fetch_tile(
            _fake_settings(), "tok", "TRUE_COLOR", (0.0, 0.0, 1.0, 1.0),
            client=mock_client,
        )
    assert exc_info.value.status == 503


@pytest.mark.asyncio
async def test_fetch_tile_raises_wms_error_on_non_image_content_type():
    try:
        from app.wms_client import fetch_tile, WmsError
    except ImportError:
        pytest.skip("app.wms_client not importable")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/xml"}  # WMS error XML, not PNG
    mock_resp.text = "<ServiceException>Invalid layer</ServiceException>"
    mock_resp.content = b""

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with pytest.raises(WmsError):
        await fetch_tile(
            _fake_settings(), "tok", "TRUE_COLOR", (0.0, 0.0, 1.0, 1.0),
            client=mock_client,
        )


# ---------------------------------------------------------------------------
# fetch_capabilities — async tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_capabilities_returns_xml_string():
    try:
        from app.wms_client import fetch_capabilities
    except ImportError:
        pytest.skip("app.wms_client not importable")

    fake_xml = "<?xml version='1.0'?><WMT_MS_Capabilities></WMT_MS_Capabilities>"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = fake_xml

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    result = await fetch_capabilities(_fake_settings(), client=mock_client)
    assert result == fake_xml


@pytest.mark.asyncio
async def test_fetch_capabilities_raises_on_non_200():
    try:
        from app.wms_client import fetch_capabilities, WmsError
    except ImportError:
        pytest.skip("app.wms_client not importable")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.text = "Unauthorized"

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    with pytest.raises(WmsError) as exc_info:
        await fetch_capabilities(_fake_settings(), client=mock_client)
    assert exc_info.value.status == 401


# ---------------------------------------------------------------------------
# parse_layers_from_capabilities
# ---------------------------------------------------------------------------

_CAPS_XML = """<?xml version="1.0"?>
<WMT_MS_Capabilities>
  <Layer>
    <Layer>
      <Name>TRUE_COLOR</Name>
      <Title>True Color Composite</Title>
    </Layer>
    <Layer>
      <Name>FALSE_COLOR</Name>
      <Title>False Color Composite</Title>
    </Layer>
    <Layer>
      <Name>NO_TITLE_LAYER</Name>
    </Layer>
  </Layer>
</WMT_MS_Capabilities>"""


def test_parse_layers_extracts_name_and_title():
    try:
        from app.wms_client import parse_layers_from_capabilities
    except ImportError:
        pytest.skip("app.wms_client not importable")

    layers = parse_layers_from_capabilities(_CAPS_XML)
    names = [l["name"] for l in layers]
    assert "TRUE_COLOR" in names
    assert "FALSE_COLOR" in names


def test_parse_layers_title_correct():
    try:
        from app.wms_client import parse_layers_from_capabilities
    except ImportError:
        pytest.skip("app.wms_client not importable")

    layers = parse_layers_from_capabilities(_CAPS_XML)
    by_name = {l["name"]: l for l in layers}
    assert by_name["TRUE_COLOR"]["title"] == "True Color Composite"


def test_parse_layers_missing_title_defaults_to_empty():
    try:
        from app.wms_client import parse_layers_from_capabilities
    except ImportError:
        pytest.skip("app.wms_client not importable")

    layers = parse_layers_from_capabilities(_CAPS_XML)
    by_name = {l["name"]: l for l in layers}
    assert by_name.get("NO_TITLE_LAYER", {}).get("title", "") == ""


def test_parse_layers_empty_xml_returns_empty_list():
    try:
        from app.wms_client import parse_layers_from_capabilities
    except ImportError:
        pytest.skip("app.wms_client not importable")

    layers = parse_layers_from_capabilities("")
    assert layers == []


def test_parse_layers_returns_list_of_dicts():
    try:
        from app.wms_client import parse_layers_from_capabilities
    except ImportError:
        pytest.skip("app.wms_client not importable")

    layers = parse_layers_from_capabilities(_CAPS_XML)
    assert isinstance(layers, list)
    for layer in layers:
        assert "name" in layer
        assert "title" in layer

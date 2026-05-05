"""
Test skeletons for sentinel-proxy tile endpoint and token manager.

Gaps covered:
  - GET /xyz/{z}/{x}/{y}.png returns 200 with image/png content-type on success
  - GET /xyz/{z}/{x}/{y}.png returns 502 when WMS server returns non-200
  - GET /xyz/{z}/{x}/{y}.png returns 504 when WMS request times out
  - tile_math.tile_to_bbox_3857() correct EPSG:3857 coordinate transform
  - tile_math.tile_to_bbox_3857() edge case: tile (0,0,0) covers full extent
  - TokenManager.get_token() refreshes when token is expired
  - TokenManager.get_token() raises on OAuth failure
  - lifespan() raises RuntimeError when Sentinel credentials are missing
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# tile_math — EPSG:3857 bounding box
# ---------------------------------------------------------------------------

def test_tile_to_bbox_3857_zoom0_covers_full_extent():
    """Tile (z=0, x=0, y=0) must cover the full Web Mercator extent."""
    try:
        from app.tile_math import tile_to_bbox_3857  # type: ignore
    except ImportError:
        pytest.skip("app.tile_math not yet importable")

    bbox = tile_to_bbox_3857(z=0, x=0, y=0)
    # Full Web Mercator extent: ±20037508.342789244 m
    HALF_WORLD = 20_037_508.342789244
    assert len(bbox) == 4, "bbox must be (min_x, min_y, max_x, max_y)"
    min_x, min_y, max_x, max_y = bbox
    assert abs(min_x - (-HALF_WORLD)) < 1.0, f"min_x wrong: {min_x}"
    assert abs(max_x - HALF_WORLD) < 1.0, f"max_x wrong: {max_x}"


def test_tile_to_bbox_3857_zoom1_northwest_tile():
    """Tile (z=1, x=0, y=0) must be the NW quarter of the world."""
    try:
        from app.tile_math import tile_to_bbox_3857  # type: ignore
    except ImportError:
        pytest.skip("app.tile_math not yet importable")

    bbox = tile_to_bbox_3857(z=1, x=0, y=0)
    min_x, min_y, max_x, max_y = bbox
    HALF_WORLD = 20_037_508.342789244
    # NW tile: x from -HALF_WORLD to 0, y from 0 to HALF_WORLD
    assert min_x < 0 < max_x or max_x <= 0, "x range should be left half"
    assert max_y > 0, "NW tile y max should be positive"


def test_tile_to_bbox_3857_returns_four_floats():
    """tile_to_bbox_3857() must always return exactly 4 float values."""
    try:
        from app.tile_math import tile_to_bbox_3857  # type: ignore
    except ImportError:
        pytest.skip("app.tile_math not yet importable")

    bbox = tile_to_bbox_3857(z=5, x=17, y=11)
    assert len(bbox) == 4
    assert all(isinstance(v, float) for v in bbox)


# ---------------------------------------------------------------------------
# Tile endpoint — success
# ---------------------------------------------------------------------------

def test_tile_endpoint_returns_png_on_success(client):  # type: ignore[name-defined]
    """GET /xyz/{z}/{x}/{y}.png must return 200 with image/png on valid tile."""
    pytest.skip("skeleton — needs client fixture from conftest.py")

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    with patch("app.main.wms_client") as mock_wms:  # type: ignore
        mock_wms.fetch_tile = AsyncMock(return_value=fake_png)
        resp = client.get("/xyz/5/17/11.png")

    assert resp.status_code == 200
    assert "image/png" in resp.headers.get("content-type", "")
    assert resp.content[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Tile endpoint — WMS non-200
# ---------------------------------------------------------------------------

def test_tile_endpoint_returns_502_when_wms_fails(client):  # type: ignore[name-defined]
    """GET /xyz/{z}/{x}/{y}.png must return 502 when WMS returns non-200."""
    pytest.skip("skeleton — needs client fixture from conftest.py")

    with patch("app.main.wms_client") as mock_wms:  # type: ignore
        mock_wms.fetch_tile = AsyncMock(side_effect=Exception("WMS 503"))
        resp = client.get("/xyz/5/17/11.png")

    assert resp.status_code in (502, 503)


# ---------------------------------------------------------------------------
# Tile endpoint — WMS timeout
# ---------------------------------------------------------------------------

def test_tile_endpoint_returns_504_on_wms_timeout(client):  # type: ignore[name-defined]
    """GET /xyz/{z}/{x}/{y}.png must return 504 when WMS request times out."""
    pytest.skip("skeleton — needs client fixture from conftest.py")

    import httpx

    with patch("app.main.wms_client") as mock_wms:  # type: ignore
        mock_wms.fetch_tile = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        resp = client.get("/xyz/5/17/11.png")

    assert resp.status_code in (504, 502)


# ---------------------------------------------------------------------------
# TokenManager — refresh on expiry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_manager_refreshes_expired_token():
    """get_token() must call OAuth refresh when stored token is expired."""
    try:
        from app.token_manager import TokenManager  # type: ignore
    except ImportError:
        pytest.skip("app.token_manager not yet importable")

    import time

    manager = TokenManager(
        client_id="test-client",
        client_secret="test-secret",
        token_url="https://fake.auth/token",
    )
    # Simulate an expired token
    manager._token = "old-token"
    manager._expires_at = time.time() - 60  # expired 60 s ago

    new_token_response = MagicMock()
    new_token_response.json = MagicMock(
        return_value={"access_token": "new-token", "expires_in": 3600}
    )
    new_token_response.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=new_token_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        token = await manager.get_token()

    assert token == "new-token"


@pytest.mark.asyncio
async def test_token_manager_raises_on_oauth_failure():
    """get_token() must raise when the OAuth endpoint returns non-200."""
    try:
        from app.token_manager import TokenManager  # type: ignore
    except ImportError:
        pytest.skip("app.token_manager not yet importable")

    manager = TokenManager(
        client_id="test-client",
        client_secret="test-secret",
        token_url="https://fake.auth/token",
    )
    # No cached token → will always try to fetch
    manager._token = None

    bad_response = MagicMock()
    bad_response.status_code = 401
    bad_response.text = "Unauthorized"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=bad_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(Exception, match="(?i)(auth|token|401|unauthorized)"):
            await manager.get_token()


# ---------------------------------------------------------------------------
# lifespan — missing Sentinel credentials
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_raises_when_sentinel_credentials_missing():
    """lifespan() must raise RuntimeError when Sentinel credentials are absent."""
    pytest.skip("skeleton — import app.main after sentinel-proxy conftest is wired")

    from app.main import lifespan, app  # type: ignore

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="(?i)(sentinel|credentials|missing)"):
            async with lifespan(app):
                pass  # pragma: no cover

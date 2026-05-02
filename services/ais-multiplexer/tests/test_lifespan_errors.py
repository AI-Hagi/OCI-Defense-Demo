"""
Test skeletons for ais-multiplexer lifespan and WebSocket error paths.

Gaps covered:
  - lifespan() raises RuntimeError when no key source is configured
  - lifespan() raises RuntimeError when vault returns empty string
  - lifespan() wraps VaultError as RuntimeError with context
  - _resolve_bbox() raises ValueError when s >= n (inverted latitudes)
  - _resolve_bbox() raises ValueError when lon is out of -180..180
  - ws_maritime() closes with code 1008 on invalid bbox params
  - _build_signer() raises VaultError when all three auth chains fail
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(
    ais_stream_api_key: str = "",
    mock_vault_key: str = "",
    vault_ais_stream_key_ocid: str = "",
    oci_region: str = "eu-frankfurt-1",
    bbox: str = "53,8,56,22",
) -> MagicMock:
    s = MagicMock()
    s.ais_stream_api_key = ais_stream_api_key
    s.mock_vault_key = mock_vault_key
    s.vault_ais_stream_key_ocid = vault_ais_stream_key_ocid
    s.oci_region = oci_region
    s.multiplexer_port = 8080
    s.bbox_default_tuple = MagicMock(return_value=(53.0, 8.0, 56.0, 22.0))
    return s


# ---------------------------------------------------------------------------
# lifespan — no key source configured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_raises_when_no_key_source_configured():
    """RuntimeError raised before vault call when all three sources are absent."""
    # TODO: import app and trigger lifespan with no key env vars set
    # Expected: RuntimeError("No AIS Stream API key source configured")
    pytest.skip("skeleton — implement after app.main is importable in test env")

    from app.main import lifespan, app  # type: ignore

    settings = _settings()  # no key, no OCID, no mock
    with patch("app.main.get_settings", return_value=settings):
        with pytest.raises(RuntimeError, match="No AIS Stream API key source"):
            async with lifespan(app):
                pass  # pragma: no cover


# ---------------------------------------------------------------------------
# lifespan — vault returns empty string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_raises_when_vault_returns_empty_key():
    """RuntimeError raised when get_secret() resolves to an empty string."""
    pytest.skip("skeleton — implement after app.main is importable in test env")

    from app.main import lifespan, app  # type: ignore
    from app.vault import VaultError  # type: ignore

    settings = _settings(vault_ais_stream_key_ocid="ocid1.vaultsecret.oc1..test")
    with patch("app.main.get_settings", return_value=settings):
        with patch("app.main.get_secret", new=AsyncMock(return_value="")):
            with pytest.raises(RuntimeError, match="empty AIS Stream API key"):
                async with lifespan(app):
                    pass  # pragma: no cover


# ---------------------------------------------------------------------------
# lifespan — VaultError is re-raised as RuntimeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_wraps_vault_error_as_runtime_error():
    """VaultError from get_secret() must surface as RuntimeError with context."""
    pytest.skip("skeleton — implement after app.main is importable in test env")

    from app.main import lifespan, app  # type: ignore
    from app.vault import VaultError  # type: ignore

    settings = _settings(vault_ais_stream_key_ocid="ocid1.vaultsecret.oc1..test")
    with patch("app.main.get_settings", return_value=settings):
        with patch(
            "app.main.get_secret",
            new=AsyncMock(side_effect=VaultError("SDK timeout")),
        ):
            with pytest.raises(RuntimeError, match="Vault read failed"):
                async with lifespan(app):
                    pass  # pragma: no cover


# ---------------------------------------------------------------------------
# _resolve_bbox — invalid latitude range (s >= n)
# ---------------------------------------------------------------------------

def test_resolve_bbox_raises_when_south_equals_north():
    from app.main import _resolve_bbox  # type: ignore

    settings = _settings()
    with pytest.raises(ValueError, match="bbox lat invalid"):
        _resolve_bbox(settings, bbox_s=55.0, bbox_w=8.0, bbox_n=55.0, bbox_e=22.0)


def test_resolve_bbox_raises_when_south_greater_than_north():
    from app.main import _resolve_bbox  # type: ignore

    settings = _settings()
    with pytest.raises(ValueError, match="bbox lat invalid"):
        _resolve_bbox(settings, bbox_s=57.0, bbox_w=8.0, bbox_n=53.0, bbox_e=22.0)


def test_resolve_bbox_raises_when_lat_out_of_world_bounds():
    from app.main import _resolve_bbox  # type: ignore

    settings = _settings()
    with pytest.raises(ValueError, match="bbox lat invalid"):
        _resolve_bbox(settings, bbox_s=-91.0, bbox_w=8.0, bbox_n=56.0, bbox_e=22.0)


# ---------------------------------------------------------------------------
# _resolve_bbox — invalid longitude
# ---------------------------------------------------------------------------

def test_resolve_bbox_raises_when_lon_out_of_range():
    from app.main import _resolve_bbox  # type: ignore

    settings = _settings()
    with pytest.raises(ValueError, match="bbox lon invalid"):
        _resolve_bbox(settings, bbox_s=53.0, bbox_w=8.0, bbox_n=56.0, bbox_e=200.0)


# ---------------------------------------------------------------------------
# _resolve_bbox — valid bbox returns tuple
# ---------------------------------------------------------------------------

def test_resolve_bbox_returns_tuple_for_valid_params():
    from app.main import _resolve_bbox  # type: ignore

    settings = _settings()
    result = _resolve_bbox(settings, bbox_s=53.0, bbox_w=8.0, bbox_n=56.0, bbox_e=22.0)
    assert result == (53.0, 8.0, 56.0, 22.0)


def test_resolve_bbox_uses_defaults_when_params_are_none():
    from app.main import _resolve_bbox  # type: ignore

    settings = _settings()
    result = _resolve_bbox(settings, bbox_s=None, bbox_w=None, bbox_n=None, bbox_e=None)
    assert result == (53.0, 8.0, 56.0, 22.0)  # from _settings() default tuple


# ---------------------------------------------------------------------------
# ws_maritime — closes with code 1008 on invalid bbox
# ---------------------------------------------------------------------------

def test_ws_maritime_closes_1008_on_invalid_bbox(client):  # type: ignore[name-defined]
    """Connecting with bbox_s > bbox_n must be rejected with close code 1008."""
    pytest.skip("skeleton — needs client fixture from conftest.py")

    # starlette WebSocket test client does not expose close code easily;
    # verify the connection is refused before accept() completes.
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/ws/maritime?bbox_s=57&bbox_w=8&bbox_n=53&bbox_e=22"
        ) as ws:
            ws.receive_text()


# ---------------------------------------------------------------------------
# _build_signer — all three auth chains fail
# ---------------------------------------------------------------------------

def test_build_signer_raises_vault_error_when_all_auth_unavailable():
    from app.vault import VaultError, _build_signer  # type: ignore

    with patch("oci.auth.signers.get_oke_workload_identity_resource_principal_signer",
               side_effect=Exception("not OKE")):
        with patch("oci.auth.signers.InstancePrincipalsSecurityTokenSigner",
                   side_effect=Exception("not VM")):
            with patch("oci.config.from_file", side_effect=Exception("no config file")):
                with pytest.raises(VaultError, match="no OCI auth available"):
                    _build_signer("eu-frankfurt-1")

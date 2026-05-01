"""
Tests for vault.get_secret() — ESO-injected key, mock key, empty OCID,
and base64 decoding of secret bundle content.
"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vault import VaultError, get_secret


# ---------------------------------------------------------------------------
# Helpers — fake Settings
# ---------------------------------------------------------------------------

def _settings(
    ais_stream_api_key: str = "",
    mock_vault_key: str = "",
    oci_region: str = "eu-frankfurt-1",
) -> MagicMock:
    s = MagicMock()
    s.ais_stream_api_key = ais_stream_api_key
    s.mock_vault_key = mock_vault_key
    s.oci_region = oci_region
    return s


# ---------------------------------------------------------------------------
# ESO-injected path (AIS_STREAM_API_KEY env present)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_secret_returns_eso_key_without_vault_call():
    settings = _settings(ais_stream_api_key="direct-key-from-eso")
    result = await get_secret("ocid1.vaultsecret.test", settings)
    assert result == "direct-key-from-eso"


@pytest.mark.asyncio
async def test_get_secret_eso_key_takes_precedence_over_mock():
    settings = _settings(ais_stream_api_key="eso-key", mock_vault_key="mock-key")
    result = await get_secret("ocid1.vaultsecret.test", settings)
    assert result == "eso-key"


# ---------------------------------------------------------------------------
# Mock vault path (MOCK_VAULT_KEY set, no ESO key)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_secret_returns_mock_key():
    settings = _settings(mock_vault_key="mock-aisstream-key")
    result = await get_secret("ocid1.vaultsecret.test", settings)
    assert result == "mock-aisstream-key"


# ---------------------------------------------------------------------------
# Empty OCID guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_secret_empty_ocid_raises_vault_error():
    settings = _settings()  # no ESO key, no mock key
    with pytest.raises(VaultError, match="OCID is empty"):
        await get_secret("", settings)


# ---------------------------------------------------------------------------
# VaultError is a RuntimeError subclass
# ---------------------------------------------------------------------------

def test_vault_error_is_runtime_error():
    err = VaultError("test")
    assert isinstance(err, RuntimeError)
    assert str(err) == "test"


# ---------------------------------------------------------------------------
# _read_secret_sync — base64 decoding
# ---------------------------------------------------------------------------

def test_read_secret_sync_decodes_base64():
    from app.vault import _read_secret_sync

    raw_value = "my-secret-api-key"
    encoded = base64.b64encode(raw_value.encode()).decode()

    content = MagicMock()
    content.content = encoded
    content.content_type = "BASE64"

    bundle_data = MagicMock()
    bundle_data.secret_bundle_content = content

    bundle_response = MagicMock()
    bundle_response.data = bundle_data

    mock_client = MagicMock()
    mock_client.get_secret_bundle = MagicMock(return_value=bundle_response)

    with patch("app.vault._build_signer", return_value=(MagicMock(), None)):
        with patch("oci.secrets.SecretsClient", return_value=mock_client):
            result = _read_secret_sync("ocid1.vaultsecret.test", "eu-frankfurt-1")

    assert result == raw_value


def test_read_secret_sync_plaintext_type_returned_as_is():
    from app.vault import _read_secret_sync

    content = MagicMock()
    content.content = "plaintext-secret"
    content.content_type = "PLAINTEXT"

    bundle_data = MagicMock()
    bundle_data.secret_bundle_content = content

    bundle_response = MagicMock()
    bundle_response.data = bundle_data

    mock_client = MagicMock()
    mock_client.get_secret_bundle = MagicMock(return_value=bundle_response)

    with patch("app.vault._build_signer", return_value=(MagicMock(), None)):
        with patch("oci.secrets.SecretsClient", return_value=mock_client):
            result = _read_secret_sync("ocid1.vaultsecret.test", "eu-frankfurt-1")

    assert result == "plaintext-secret"


def test_read_secret_sync_raises_when_bundle_has_no_content():
    from app.vault import _read_secret_sync

    content = MagicMock()
    content.content = None
    content.content_type = "BASE64"

    bundle_data = MagicMock()
    bundle_data.secret_bundle_content = content

    bundle_response = MagicMock()
    bundle_response.data = bundle_data

    mock_client = MagicMock()
    mock_client.get_secret_bundle = MagicMock(return_value=bundle_response)

    with patch("app.vault._build_signer", return_value=(MagicMock(), None)):
        with patch("oci.secrets.SecretsClient", return_value=mock_client):
            with pytest.raises(VaultError, match="no content"):
                _read_secret_sync("ocid1.vaultsecret.test", "eu-frankfurt-1")


def test_read_secret_sync_raises_on_sdk_exception():
    from app.vault import _read_secret_sync

    mock_client = MagicMock()
    mock_client.get_secret_bundle = MagicMock(side_effect=RuntimeError("SDK timeout"))

    with patch("app.vault._build_signer", return_value=(MagicMock(), None)):
        with patch("oci.secrets.SecretsClient", return_value=mock_client):
            with pytest.raises(VaultError, match="failed to fetch secret"):
                _read_secret_sync("ocid1.vaultsecret.test", "eu-frankfurt-1")

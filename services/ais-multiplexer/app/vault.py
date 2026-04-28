"""
OCI Vault adapter — reads a secret bundle by OCID.

Auth precedence:
  1. Workload Identity (OKE pods) — preferred in production.
  2. Instance Principal (dev VM).
  3. API-key config file (local-dev fallback only).
  4. MOCK_VAULT_KEY env — pure unit-test / offline-dev shortcut, NEVER prod.

If none of the above can produce a secret, the service must NOT start.
"""
from __future__ import annotations

import base64
from typing import Optional

import structlog

from .settings import Settings, get_settings

logger = structlog.get_logger(__name__)


class VaultError(RuntimeError):
    """Raised when a Vault secret cannot be read."""


def _build_signer(region: str):
    """Return an OCI auth signer using the highest-trust mechanism available.

    Tries Workload Identity first (OKE), then Instance Principal (dev VM),
    then ~/.oci/config (local dev). Raises VaultError if all fail.
    """
    # Imported lazily so unit tests that mock get_secret don't need the SDK.
    try:
        from oci.auth import signers  # type: ignore
    except ImportError as exc:  # pragma: no cover - SDK always installed in image
        raise VaultError("oci SDK not installed") from exc

    # 1. Workload Identity (OKE)
    try:
        signer = signers.get_oke_workload_identity_resource_principal_signer()
        logger.info("vault.signer.selected", kind="workload_identity")
        return signer, None
    except Exception as exc:  # noqa: BLE001 - any failure means try next
        logger.debug("vault.signer.workload_identity_unavailable", error=str(exc))

    # 2. Instance Principal
    try:
        signer = signers.InstancePrincipalsSecurityTokenSigner()
        logger.info("vault.signer.selected", kind="instance_principal")
        return signer, None
    except Exception as exc:  # noqa: BLE001
        logger.debug("vault.signer.instance_principal_unavailable", error=str(exc))

    # 3. API-key config file (local dev only)
    try:
        from oci import config as oci_config  # type: ignore

        cfg = oci_config.from_file()
        cfg["region"] = region
        logger.warning("vault.signer.selected", kind="api_key_config_file")
        return None, cfg
    except Exception as exc:  # noqa: BLE001
        raise VaultError(
            "no OCI auth available (workload identity / instance principal / api key)"
        ) from exc


async def get_secret(ocid: str, settings: Optional[Settings] = None) -> str:
    """
    Read a secret bundle by OCID and return the plaintext content.

    The OCI SDK is synchronous; we keep this function ``async`` for symmetry
    with the rest of the service so callers can ``await`` it without thinking.
    Internally we use ``asyncio.to_thread`` to avoid blocking the event loop.
    """
    settings = settings or get_settings()

    # ESO-injected pre-resolved value — preferred path under Kubernetes.
    # The External Secrets Operator pulls the secret from OCI Vault and
    # mounts it as `AIS_STREAM_API_KEY`. No runtime SDK call needed.
    if settings.ais_stream_api_key:
        logger.info(
            "vault.eso_injected_value_used",
            source="AIS_STREAM_API_KEY env (via ExternalSecret)",
        )
        return settings.ais_stream_api_key

    # MOCK escape hatch — local dev / unit tests only.
    if settings.mock_vault_key:
        logger.warning(
            "vault.mock_key_used",
            ocid=ocid,
            message="MOCK_VAULT_KEY set — bypassing OCI Vault. NEVER use in production.",
        )
        return settings.mock_vault_key

    if not ocid:
        raise VaultError("vault secret OCID is empty")

    import asyncio

    return await asyncio.to_thread(_read_secret_sync, ocid, settings.oci_region)


def _read_secret_sync(ocid: str, region: str) -> str:
    try:
        from oci.secrets import SecretsClient  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise VaultError("oci SDK not installed") from exc

    signer, cfg = _build_signer(region)
    if signer is not None:
        client = SecretsClient(config={"region": region}, signer=signer)
    else:
        client = SecretsClient(config=cfg)  # type: ignore[arg-type]

    try:
        bundle = client.get_secret_bundle(secret_id=ocid).data
    except Exception as exc:  # noqa: BLE001
        raise VaultError(f"failed to fetch secret {ocid}: {exc}") from exc

    content = bundle.secret_bundle_content
    # Bundles are base64 by default for Generic secrets.
    raw = getattr(content, "content", None)
    content_type = getattr(content, "content_type", "BASE64")
    if raw is None:
        raise VaultError(f"secret {ocid} bundle has no content")

    if content_type == "BASE64":
        try:
            return base64.b64decode(raw).decode("utf-8").strip()
        except Exception as exc:  # noqa: BLE001
            raise VaultError(f"failed to decode base64 secret {ocid}: {exc}") from exc
    return str(raw).strip()

"""
Settings for the AIS Multiplexer.

All values come from environment variables / .env. There are NO hardcoded
OCIDs, secrets, or region strings in code paths. Region defaults to
eu-frankfurt-1 (EU Sovereign Cloud) per project convention.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service-level configuration loaded from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- OCI tenancy ---
    oci_region: str = Field(default="eu-frankfurt-1", alias="OCI_REGION")
    oci_compartment_ocid: Optional[str] = Field(
        default=None, alias="OCI_COMPARTMENT_OCID"
    )

    # --- Vault ---
    vault_ais_stream_key_ocid: Optional[str] = Field(
        default=None, alias="VAULT_AIS_STREAM_KEY_OCID"
    )
    # Pre-resolved AIS Stream API key, typically injected by External Secrets
    # Operator from OCI Vault as a Kubernetes Secret. Preferred over OCID-based
    # resolution when set: avoids a runtime SDK call inside the pod.
    ais_stream_api_key: Optional[str] = Field(
        default=None, alias="AIS_STREAM_API_KEY"
    )
    # Local-dev only: when set, vault.get_secret returns this verbatim and
    # the service skips the OCI SDK call. NEVER set in production.
    mock_vault_key: Optional[str] = Field(default=None, alias="MOCK_VAULT_KEY")

    # --- Oracle 26ai ATP ---
    # Env names match the platform convention used by sibling services
    # (compliance/geoint/osint-fusion all read ORACLE_USER / ORACLE_PASSWORD
    # from the `adb-credentials` Secret; configmap-common provides
    # ORACLE_CONNECT_STRING + TNS_ADMIN). Python field names stay
    # `atp_*` so db.py doesn't need to change.
    atp_connection_name: str = Field(default="sovdef26_tp", alias="ORACLE_CONNECT_STRING")
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")

    # --- Multiplexer behaviour ---
    multiplexer_port: int = Field(default=8001, alias="MULTIPLEXER_PORT")
    ais_bbox_default: str = Field(default="53,8,56,22", alias="AIS_BBOX_DEFAULT")

    # --- Audit batching ---
    audit_flush_frames: int = Field(default=50, alias="AUDIT_FLUSH_FRAMES", ge=1)
    audit_flush_seconds: float = Field(
        default=10.0, alias="AUDIT_FLUSH_SECONDS", gt=0.0
    )

    # --- Upstream ---
    upstream_url: str = Field(
        default="wss://stream.aisstream.io/v0/stream",
        alias="AIS_UPSTREAM_URL",
    )
    upstream_max_backoff_seconds: float = Field(
        default=60.0, alias="UPSTREAM_MAX_BACKOFF", gt=0.0
    )

    @field_validator("ais_bbox_default")
    @classmethod
    def _validate_bbox(cls, v: str) -> str:
        parts = v.split(",")
        if len(parts) != 4:
            raise ValueError(
                "AIS_BBOX_DEFAULT must be 'south,west,north,east' (4 floats)"
            )
        try:
            s, w, n, e = (float(p) for p in parts)
        except ValueError as exc:
            raise ValueError("AIS_BBOX_DEFAULT components must be numbers") from exc
        if not (-90.0 <= s <= 90.0 and -90.0 <= n <= 90.0):
            raise ValueError("AIS_BBOX_DEFAULT lat out of range")
        if not (-180.0 <= w <= 180.0 and -180.0 <= e <= 180.0):
            raise ValueError("AIS_BBOX_DEFAULT lon out of range")
        if s >= n:
            raise ValueError("AIS_BBOX_DEFAULT south must be < north")
        return v

    def bbox_default_tuple(self) -> tuple[float, float, float, float]:
        s, w, n, e = (float(x) for x in self.ais_bbox_default.split(","))
        return (s, w, n, e)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Tests can override via FastAPI dependency override or by clearing the
    cache: ``get_settings.cache_clear()``.
    """
    return Settings()

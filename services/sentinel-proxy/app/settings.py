"""
Settings for the Sentinel-2 Proxy.

Environment contract:
  OCI_REGION                 default eu-frankfurt-1
  PROXY_PORT                 default 8008
  SENTINEL_CLIENT_ID         from ExternalSecret (Vault: sentinel-client-id)
  SENTINEL_CLIENT_SECRET     from ExternalSecret (Vault: sentinel-client-secret)
  SENTINEL_INSTANCE_ID       from ExternalSecret (Vault: sentinel-instance-id)
  SENTINEL_TOKEN_URL         default https://identity.dataspace.copernicus.eu/...
  SENTINEL_WMS_BASE          default https://sh.dataspace.copernicus.eu/ogc/wms
  SENTINEL_DEFAULT_LAYER     default TRUE-COLOR-HIGHLIGHT-OPTIMIZED
  SENTINEL_TILE_SIZE         default 512
  SENTINEL_MAXCC             default 20
  SENTINEL_BBOX_DEFAULT      default 55.0,14.7,55.3,15.2 (Bornholm — UC4 demo)
  TOKEN_REFRESH_MINUTES      default 25 (Copernicus tokens live 30 min)
  CAPABILITIES_TTL_HOURS     default 24 (refresh layer list daily)
  AUDIT_FLUSH_TILES          default 50
  AUDIT_FLUSH_SECONDS        default 30
  ORACLE_CONNECT_STRING      TNS alias (e.g. sovdef26_tp)
  ORACLE_USER, ORACLE_PASSWORD, WALLET_PASSWORD   from adb-credentials
  TNS_ADMIN                  default /app/wallet
  X_TENANT_DEFAULT           default T001
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- OCI ---
    oci_region: str = Field(default="eu-frankfurt-1", alias="OCI_REGION")
    oci_compartment_ocid: Optional[str] = Field(default=None, alias="OCI_COMPARTMENT_OCID")

    # --- Service ---
    proxy_port: int = Field(default=8008, alias="PROXY_PORT")

    # --- Sentinel Hub credentials (ExternalSecret-injected) ---
    sentinel_client_id: Optional[str] = Field(default=None, alias="SENTINEL_CLIENT_ID")
    sentinel_client_secret: Optional[str] = Field(default=None, alias="SENTINEL_CLIENT_SECRET")
    sentinel_instance_id: Optional[str] = Field(default=None, alias="SENTINEL_INSTANCE_ID")

    # --- Sentinel Hub endpoints + defaults ---
    sentinel_token_url: str = Field(
        default="https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        alias="SENTINEL_TOKEN_URL",
    )
    sentinel_wms_base: str = Field(
        default="https://sh.dataspace.copernicus.eu/ogc/wms",
        alias="SENTINEL_WMS_BASE",
    )
    sentinel_default_layer: str = Field(
        default="TRUE-COLOR-HIGHLIGHT-OPTIMIZED",
        alias="SENTINEL_DEFAULT_LAYER",
    )
    sentinel_tile_size: int = Field(default=512, alias="SENTINEL_TILE_SIZE", ge=64, le=2048)
    sentinel_maxcc: int = Field(default=20, alias="SENTINEL_MAXCC", ge=0, le=100)
    sentinel_bbox_default: str = Field(
        default="55.0,14.7,55.3,15.2", alias="SENTINEL_BBOX_DEFAULT"
    )

    token_refresh_minutes: int = Field(
        default=25, alias="TOKEN_REFRESH_MINUTES", ge=1, le=29
    )
    capabilities_ttl_hours: int = Field(
        default=24, alias="CAPABILITIES_TTL_HOURS", ge=1
    )

    # --- Audit batching ---
    audit_flush_tiles: int = Field(default=50, alias="AUDIT_FLUSH_TILES", ge=1)
    audit_flush_seconds: float = Field(
        default=30.0, alias="AUDIT_FLUSH_SECONDS", gt=0.0
    )

    # --- Tenant for audit ---
    x_tenant_default: str = Field(default="T001", alias="X_TENANT_DEFAULT")

    # --- Oracle 26ai ATP ---
    atp_connection_name: str = Field(default="sovdef26_tp", alias="ORACLE_CONNECT_STRING")
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

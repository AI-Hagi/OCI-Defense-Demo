"""
Settings for the GPS Jamming Poller.

Environment contract (no hardcoded secrets, no hardcoded region):
  OCI_REGION                default eu-frankfurt-1
  POLLER_PORT               default 8007
  GPSJAM_URL_TEMPLATE       default https://gpsjam.org/data/{date}.csv
  REFRESH_HOURS             default 6
  CACHE_TTL_HOURS           default 24
  ORACLE_CONNECT_STRING     TNS alias (e.g. sovdef26_tp)
  ORACLE_USER, ORACLE_PASSWORD, WALLET_PASSWORD   from adb-credentials Secret
  TNS_ADMIN                 default /app/wallet
  X_TENANT_DEFAULT          default T001 (audit row tenant tag)
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

    # OCI
    oci_region: str = Field(default="eu-frankfurt-1", alias="OCI_REGION")
    oci_compartment_ocid: Optional[str] = Field(
        default=None, alias="OCI_COMPARTMENT_OCID"
    )

    # Service
    poller_port: int = Field(default=8007, alias="POLLER_PORT")

    # Upstream gpsjam.org
    gpsjam_url_template: str = Field(
        default="https://gpsjam.org/data/{date}.csv",
        alias="GPSJAM_URL_TEMPLATE",
    )
    refresh_hours: int = Field(default=6, alias="REFRESH_HOURS", ge=1)
    cache_ttl_hours: int = Field(default=24, alias="CACHE_TTL_HOURS", ge=1)

    # Classification thresholds (ratio of low-NACp aircraft / total).
    classify_amber_threshold: float = Field(
        default=0.02, alias="CLASSIFY_AMBER_THRESHOLD", ge=0.0, le=1.0
    )
    classify_red_threshold: float = Field(
        default=0.10, alias="CLASSIFY_RED_THRESHOLD", ge=0.0, le=1.0
    )
    minimum_aircraft_count: int = Field(
        default=3, alias="MINIMUM_AIRCRAFT_COUNT", ge=1
    )

    # Tenant tag for audit_events.
    x_tenant_default: str = Field(default="T001", alias="X_TENANT_DEFAULT")

    # Oracle 26ai ATP — platform-convention env names (matches sibling services).
    atp_connection_name: str = Field(default="sovdef26_tp", alias="ORACLE_CONNECT_STRING")
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

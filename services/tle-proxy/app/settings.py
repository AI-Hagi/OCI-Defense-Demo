"""
Settings for the TLE Proxy.

Environment contract:
  OCI_REGION                         default eu-frankfurt-1
  PROXY_PORT                         default 8010
  CELESTRAK_BASE_URL                 default https://celestrak.org
  TLE_REFRESH_HOURS                  default 6  (TLEs change ~daily; 6 h is conservative)
  CACHE_TTL_HOURS                    default 12 (cold-cache threshold;
                                                 still served if upstream blip)
  TLE_GROUPS                         default stations,resource,active
  ORACLE_*  (from adb-credentials Secret)
  TNS_ADMIN                          default /app/wallet
  X_TENANT_DEFAULT                   default T001
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

    oci_region: str = Field(default="eu-frankfurt-1", alias="OCI_REGION")
    oci_compartment_ocid: Optional[str] = Field(default=None, alias="OCI_COMPARTMENT_OCID")
    proxy_port: int = Field(default=8010, alias="PROXY_PORT")

    celestrak_base_url: str = Field(
        default="https://celestrak.org", alias="CELESTRAK_BASE_URL"
    )
    tle_refresh_hours: int = Field(default=6, alias="TLE_REFRESH_HOURS", ge=1)
    cache_ttl_hours: int = Field(default=12, alias="CACHE_TTL_HOURS", ge=1)
    # Comma-separated CelesTrak GROUP names. Default = the three Recipe-L
    # categories. Adding more requires no code change — just env override.
    tle_groups: str = Field(
        default="stations,resource,active", alias="TLE_GROUPS"
    )

    x_tenant_default: str = Field(default="T001", alias="X_TENANT_DEFAULT")

    atp_connection_name: str = Field(default="sovdef26_tp", alias="ORACLE_CONNECT_STRING")
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")

    def groups_list(self) -> list[str]:
        return [g.strip() for g in self.tle_groups.split(",") if g.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

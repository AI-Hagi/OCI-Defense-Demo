"""
Settings for the Flights Proxy.

Environment contract:
  OCI_REGION                         default eu-frankfurt-1
  PROXY_PORT                         default 8009
  ADSB_API_BASE                      default https://api.adsb.lol
  ADSB_CENTER_LAT, ADSB_CENTER_LON   default Bornholm region (matches the
                                              Maritime layer demo for UC4
                                              correlation stories)
  ADSB_RADIUS_NM                     default 250
  REFRESH_MINUTES                    default 2  (aircraft move fast)
  CACHE_TTL_MINUTES                  default 10 (cold-cache threshold)
  CLASSIFIER_CACHE_TTL_MINUTES       default 30
  FLIGHTS_BBOX_DEFAULT               default 53.0,8.0,60.0,25.0
                                              (matches AIS/Maritime broad
                                              Baltic envelope)
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
    proxy_port: int = Field(default=8009, alias="PROXY_PORT")

    adsb_api_base: str = Field(default="https://api.adsb.lol", alias="ADSB_API_BASE")
    adsb_center_lat: float = Field(default=54.5, alias="ADSB_CENTER_LAT")
    adsb_center_lon: float = Field(default=15.0, alias="ADSB_CENTER_LON")
    adsb_radius_nm: int = Field(default=250, alias="ADSB_RADIUS_NM", ge=1, le=250)

    refresh_minutes: int = Field(default=2, alias="REFRESH_MINUTES", ge=1)
    cache_ttl_minutes: int = Field(default=10, alias="CACHE_TTL_MINUTES", ge=1)
    classifier_cache_ttl_minutes: int = Field(
        default=30, alias="CLASSIFIER_CACHE_TTL_MINUTES", ge=1
    )
    # In-memory TTL for viewport-driven on-demand fetches. Short — the
    # frontend pans/zooms freely and we want fresh data per camera move,
    # but adjacent users on the same viewport share the upstream call.
    viewport_cache_ttl_seconds: int = Field(
        default=30, alias="VIEWPORT_CACHE_TTL_SECONDS", ge=1
    )

    flights_bbox_default: str = Field(
        default="53.0,8.0,60.0,25.0", alias="FLIGHTS_BBOX_DEFAULT"
    )

    x_tenant_default: str = Field(default="T001", alias="X_TENANT_DEFAULT")

    atp_connection_name: str = Field(default="sovdef26_tp", alias="ORACLE_CONNECT_STRING")
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

"""
Settings for the GPS Jamming Poller.

Environment contract (no hardcoded secrets, no hardcoded region):
  OCI_REGION                default eu-frankfurt-1
  POLLER_PORT               default 8007
  ADSB_API_BASE             default https://api.adsb.lol
  ADSB_CENTER_LAT           default 54.5  (Baltic mid)
  ADSB_CENTER_LON           default 15.0  (Baltic mid)
  ADSB_RADIUS_NM            default 250   (covers AIS_BBOX_DEFAULT 53..60 N, 8..25 E)
  REFRESH_MINUTES           default 30    (live aircraft snapshot, not daily)
  CACHE_TTL_HOURS           default 6     (read_latest returns None if older)
  H3_RESOLUTION             default 4
  LOW_NACP_THRESHOLD        default 8     (NACp < 8 ≈ position uncertainty > 30 m)
  CLASSIFY_AMBER_THRESHOLD  default 0.02
  CLASSIFY_RED_THRESHOLD    default 0.10
  MINIMUM_AIRCRAFT_COUNT    default 3
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

    # Upstream — ADS-B feeder community network. Same response schema as the
    # paid ADS-B Exchange API. No API key required.
    adsb_api_base: str = Field(
        default="https://api.adsb.lol", alias="ADSB_API_BASE"
    )
    adsb_center_lat: float = Field(default=54.5, alias="ADSB_CENTER_LAT")
    adsb_center_lon: float = Field(default=15.0, alias="ADSB_CENTER_LON")
    adsb_radius_nm: int = Field(default=250, alias="ADSB_RADIUS_NM", ge=1, le=250)

    refresh_minutes: int = Field(default=30, alias="REFRESH_MINUTES", ge=1)
    cache_ttl_hours: int = Field(default=6, alias="CACHE_TTL_HOURS", ge=1)
    # In-memory TTL for viewport-driven on-demand fetches. Short — operator
    # pans/zooms freely and we want fresh data per camera move; concurrent
    # users on the same viewport share the upstream call.
    viewport_cache_ttl_seconds: int = Field(
        default=30, alias="VIEWPORT_CACHE_TTL_SECONDS", ge=1
    )
    # Sliding-window accumulator size. Default 48 samples × 30 min refresh
    # = 24 h window — gives statistically meaningful per-cell counts even
    # at H3 res 4. State is in-process; pod restart resets the window.
    window_samples: int = Field(default=48, alias="WINDOW_SAMPLES", ge=1)

    # H3 + NACp aggregation
    h3_resolution: int = Field(default=4, alias="H3_RESOLUTION", ge=0, le=15)
    low_nacp_threshold: int = Field(
        default=8, alias="LOW_NACP_THRESHOLD", ge=0, le=11
    )
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

    # Oracle 26ai ATP — platform-convention env names.
    atp_connection_name: str = Field(default="sovdef26_tp", alias="ORACLE_CONNECT_STRING")
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

"""
Settings for the Ports Proxy.

Environment contract:
  OCI_REGION                       default eu-frankfurt-1
  PROXY_PORT                       default 8011
  OVERPASS_API_URL                 default https://overpass-api.de/api/interpreter
  OVERPASS_TIMEOUT_SECONDS         default 60
  PORTS_DEMO_BBOX                  south,west,north,east — default Europe+Mediterranean
                                   (35,-15,72,40). The loader runs the Overpass
                                   query against this bbox; an empty/global
                                   bbox is acceptable but slow + rate-limited.
  PORTS_CURATED_RADIUS_M           default 5000 — nearest-neighbor radius for
                                   curated→OSM merge.
  PORTS_CACHE_TTL_DAYS             default 30 — cold-cache threshold.
                                   Service starts immediately if cache is
                                   younger than this; loader is invoked
                                   automatically only when cache is empty
                                   or older.
  PORTS_INTERNAL_TOKEN             /api/osint/ports/refresh requires
                                   X-Internal-Token: <this>. Set to a real
                                   secret in prod; default is intentionally
                                   absent (refresh disabled until set).
  ORACLE_*  (from adb-credentials Secret)
  TNS_ADMIN                        default /app/wallet
  X_TENANT_DEFAULT                 default T001
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
    proxy_port: int = Field(default=8011, alias="PROXY_PORT")

    overpass_api_url: str = Field(
        default="https://overpass-api.de/api/interpreter", alias="OVERPASS_API_URL"
    )
    overpass_timeout_seconds: int = Field(
        default=60, alias="OVERPASS_TIMEOUT_SECONDS", ge=10
    )
    ports_demo_bbox: str = Field(
        default="35,-15,72,40", alias="PORTS_DEMO_BBOX",
    )
    ports_curated_radius_m: int = Field(
        default=5000, alias="PORTS_CURATED_RADIUS_M", ge=100
    )
    ports_cache_ttl_days: int = Field(
        default=30, alias="PORTS_CACHE_TTL_DAYS", ge=1
    )
    ports_internal_token: Optional[str] = Field(
        default=None, alias="PORTS_INTERNAL_TOKEN"
    )

    x_tenant_default: str = Field(default="T001", alias="X_TENANT_DEFAULT")

    atp_connection_name: str = Field(default="sovdef26_tp", alias="ORACLE_CONNECT_STRING")
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")

    def bbox_tuple(self) -> tuple[float, float, float, float]:
        try:
            parts = [float(x) for x in self.ports_demo_bbox.split(",")]
            assert len(parts) == 4
            s, w, n, e = parts
            return (s, w, n, e)
        except Exception as exc:
            raise ValueError(
                f"PORTS_DEMO_BBOX must be 'south,west,north,east' (4 floats), "
                f"got {self.ports_demo_bbox!r}: {exc}"
            ) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

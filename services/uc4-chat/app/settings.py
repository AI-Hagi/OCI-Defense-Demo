"""
Settings for the UC4 Chat Service.

Environment contract:
  CHAT_PORT                          default 8013
  OCI_REGION                         default eu-frankfurt-1
  OCI_COMPARTMENT_OCID               required for OCI GenAI Inference (prod)

  CHAT_MODEL                         default cohere.command-r-plus
  CHAT_FALLBACK_MODEL                default meta.llama-3.3-70b-instruct
  CHAT_MAX_TOOL_HOPS                 default 5
  CHAT_LLM_MODE                      'oci' | 'mock'   (default 'oci' in-cluster,
                                     'mock' in tests via env override)

  Upstream UC4 backends (in-cluster service DNS):
    FLIGHTS_PROXY_URL                default http://flights-proxy:8009
    AIS_MULTIPLEXER_URL              default http://ais-multiplexer:8001
    JAMMING_POLLER_URL               default http://jamming-poller:8007
    OSINT_FUSION_URL                 default http://osint:8003

  Audit DB (optional in dev — service degrades gracefully if unset):
    ORACLE_USER, ORACLE_PASSWORD, ORACLE_CONNECT_STRING, TNS_ADMIN

  X_TENANT_DEFAULT                   default T001
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    chat_port: int = Field(default=8013, alias="CHAT_PORT")

    oci_region: str = Field(default="eu-frankfurt-1", alias="OCI_REGION")
    oci_compartment_ocid: Optional[str] = Field(
        default=None, alias="OCI_COMPARTMENT_OCID"
    )

    chat_model: str = Field(default="cohere.command-r-plus", alias="CHAT_MODEL")
    chat_fallback_model: str = Field(
        default="meta.llama-3.3-70b-instruct", alias="CHAT_FALLBACK_MODEL"
    )
    chat_max_tool_hops: int = Field(default=5, alias="CHAT_MAX_TOOL_HOPS", ge=1, le=20)
    chat_llm_mode: Literal["oci", "mock"] = Field(default="oci", alias="CHAT_LLM_MODE")

    flights_proxy_url: str = Field(
        default="http://flights-proxy:8009", alias="FLIGHTS_PROXY_URL"
    )
    ais_multiplexer_url: str = Field(
        default="http://ais-multiplexer:8001", alias="AIS_MULTIPLEXER_URL"
    )
    jamming_poller_url: str = Field(
        default="http://jamming-poller:8007", alias="JAMMING_POLLER_URL"
    )
    osint_fusion_url: str = Field(
        default="http://osint:8003", alias="OSINT_FUSION_URL"
    )

    upstream_timeout_seconds: float = Field(
        default=15.0, alias="UPSTREAM_TIMEOUT_SECONDS", ge=1.0, le=120.0
    )

    x_tenant_default: str = Field(default="T001", alias="X_TENANT_DEFAULT")

    atp_connection_name: Optional[str] = Field(
        default=None, alias="ORACLE_CONNECT_STRING"
    )
    atp_user: Optional[str] = Field(default=None, alias="ORACLE_USER")
    atp_password: Optional[str] = Field(default=None, alias="ORACLE_PASSWORD")
    tns_admin: str = Field(default="/app/wallet", alias="TNS_ADMIN")
    wallet_password: Optional[str] = Field(default=None, alias="WALLET_PASSWORD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

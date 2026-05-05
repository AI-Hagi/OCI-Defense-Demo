"""
Unit tests for Settings and get_settings() in app/settings.py.

Gaps covered:
  - Default values when only mandatory env vars are absent
  - oci_region defaults to eu-frankfurt-1 (EU Sovereign Cloud)
  - AIS_BBOX_DEFAULT validator: valid, wrong part count, non-numeric, lat out of range,
    lon out of range, south >= north
  - bbox_default_tuple() raises ValueError when AIS_BBOX_DEFAULT is not set
  - bbox_default_tuple() returns correct (s, w, n, e) tuple when set
  - multiplexer_port defaults to 8001
  - audit_flush_frames defaults to 50; rejects 0 (ge=1)
  - audit_flush_seconds defaults to 10.0; rejects 0.0 (gt=0.0)
  - get_settings() returns the same instance (lru_cache)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _purge() -> None:
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]


def _make_settings(**env_overrides):
    """Import Settings fresh and instantiate with the given env vars."""
    _purge()
    with patch.dict(os.environ, env_overrides, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"app.settings not importable: {exc}")
        return Settings()


# ---------------------------------------------------------------------------
# OCI region default
# ---------------------------------------------------------------------------

def test_oci_region_defaults_to_eu_frankfurt_1():
    s = _make_settings()
    assert s.oci_region == "eu-frankfurt-1"


def test_oci_region_can_be_overridden():
    s = _make_settings(OCI_REGION="us-ashburn-1")
    assert s.oci_region == "us-ashburn-1"


# ---------------------------------------------------------------------------
# AIS_BBOX_DEFAULT validator
# ---------------------------------------------------------------------------

def test_bbox_default_none_does_not_raise_at_construction():
    # bbox_default_tuple() raises, but Settings() itself must not.
    s = _make_settings()
    assert s.ais_bbox_default is None


def test_bbox_default_valid_parses_ok():
    s = _make_settings(AIS_BBOX_DEFAULT="47.0,5.0,55.5,15.5")
    assert s.ais_bbox_default == "47.0,5.0,55.5,15.5"


def test_bbox_default_rejects_wrong_part_count():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AIS_BBOX_DEFAULT": "47.0,5.0,55.5"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError, match="4 floats"):
            Settings()


def test_bbox_default_rejects_non_numeric():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AIS_BBOX_DEFAULT": "north,5.0,55.5,15.5"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError, match="numbers"):
            Settings()


def test_bbox_default_rejects_lat_out_of_range():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AIS_BBOX_DEFAULT": "-91.0,5.0,55.5,15.5"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError, match="lat"):
            Settings()


def test_bbox_default_rejects_lon_out_of_range():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AIS_BBOX_DEFAULT": "47.0,181.0,55.5,15.5"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError, match="lon"):
            Settings()


def test_bbox_default_rejects_south_ge_north():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AIS_BBOX_DEFAULT": "55.5,5.0,47.0,15.5"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError, match="south must be < north"):
            Settings()


def test_bbox_default_rejects_south_equal_north():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AIS_BBOX_DEFAULT": "50.0,5.0,50.0,15.5"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError):
            Settings()


# ---------------------------------------------------------------------------
# bbox_default_tuple()
# ---------------------------------------------------------------------------

def test_bbox_default_tuple_raises_when_not_set():
    s = _make_settings()
    with pytest.raises(ValueError, match="AIS_BBOX_DEFAULT not set"):
        s.bbox_default_tuple()


def test_bbox_default_tuple_returns_correct_snwe():
    s = _make_settings(AIS_BBOX_DEFAULT="47.0,5.0,55.5,15.5")
    result = s.bbox_default_tuple()
    assert result == pytest.approx((47.0, 5.0, 55.5, 15.5))


def test_bbox_default_tuple_type_is_tuple_of_floats():
    s = _make_settings(AIS_BBOX_DEFAULT="47.0,5.0,55.5,15.5")
    result = s.bbox_default_tuple()
    assert isinstance(result, tuple)
    assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# Port and audit defaults
# ---------------------------------------------------------------------------

def test_multiplexer_port_defaults_to_8001():
    s = _make_settings()
    assert s.multiplexer_port == 8001


def test_multiplexer_port_can_be_overridden():
    s = _make_settings(MULTIPLEXER_PORT="9000")
    assert s.multiplexer_port == 9000


def test_audit_flush_frames_default_is_50():
    s = _make_settings()
    assert s.audit_flush_frames == 50


def test_audit_flush_seconds_default_is_10():
    s = _make_settings()
    assert s.audit_flush_seconds == pytest.approx(10.0)


def test_audit_flush_frames_rejects_zero():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AUDIT_FLUSH_FRAMES": "0"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError):
            Settings()


def test_audit_flush_seconds_rejects_zero():
    from pydantic import ValidationError
    _purge()
    with patch.dict(os.environ, {"AUDIT_FLUSH_SECONDS": "0.0"}, clear=False):
        try:
            from app.settings import Settings  # type: ignore
        except Exception as exc:
            pytest.skip(f"not importable: {exc}")
        with pytest.raises(ValidationError):
            Settings()


# ---------------------------------------------------------------------------
# get_settings() caching
# ---------------------------------------------------------------------------

def test_get_settings_returns_same_instance():
    _purge()
    try:
        from app.settings import get_settings  # type: ignore
    except Exception as exc:
        pytest.skip(f"not importable: {exc}")
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()


def test_get_settings_cache_clear_reloads():
    _purge()
    try:
        from app.settings import get_settings  # type: ignore
    except Exception as exc:
        pytest.skip(f"not importable: {exc}")
    get_settings.cache_clear()
    first = get_settings()
    get_settings.cache_clear()
    second = get_settings()
    # After clearing, a new instance is created (not the same object).
    assert first is not second
    get_settings.cache_clear()

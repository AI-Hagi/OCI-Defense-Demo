"""
Tests for app/exif_gps.py — EXIF GPS extraction + synthetic fallback footprint.

Covers:
  - _coerce_rational: IFDRational float, (num, den) tuple, bad shape
  - _convert_to_dd: N/S/E/W hemispheres, short/None value, ZeroDivisionError
  - extract_exif_gps: no EXIF, missing GPS IFD, valid GPS, bad image bytes,
                      out-of-range coords, partial GPS tags
  - _deterministic_jitter: determinism, different-bytes diverge, output range
  - _polygon_ring: 5 points, closed ring, correct bbox
  - resolve_footprint: real GPS path (is_synthetic=False), synthetic fallback,
                       ring is closed, jitter within _JITTER_DEG bounds
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# _coerce_rational
# ---------------------------------------------------------------------------

def test_coerce_rational_float_passthrough():
    from app.exif_gps import _coerce_rational
    assert _coerce_rational(1.5) == pytest.approx(1.5)


def test_coerce_rational_ifd_rational_like():
    from app.exif_gps import _coerce_rational
    # IFDRational is float-castable — simulate with int
    assert _coerce_rational(3) == pytest.approx(3.0)


def test_coerce_rational_tuple_num_den():
    from app.exif_gps import _coerce_rational
    assert _coerce_rational((10, 4)) == pytest.approx(2.5)


def test_coerce_rational_list_num_den():
    from app.exif_gps import _coerce_rational
    assert _coerce_rational([7, 2]) == pytest.approx(3.5)


def test_coerce_rational_bad_tuple_shape_raises():
    from app.exif_gps import _coerce_rational
    with pytest.raises(TypeError):
        _coerce_rational((1, 2, 3))


def test_coerce_rational_empty_tuple_raises():
    from app.exif_gps import _coerce_rational
    with pytest.raises(TypeError):
        _coerce_rational(())


# ---------------------------------------------------------------------------
# _convert_to_dd
# ---------------------------------------------------------------------------

def test_convert_to_dd_north():
    from app.exif_gps import _convert_to_dd
    # 48° 8' 22.56" N  =  48 + 8/60 + 22.56/3600 ≈ 48.1396
    result = _convert_to_dd((48, 8, 22.56), "N")
    assert result == pytest.approx(48.1396, abs=1e-3)


def test_convert_to_dd_south_is_negative():
    from app.exif_gps import _convert_to_dd
    result = _convert_to_dd((10, 0, 0), "S")
    assert result == pytest.approx(-10.0)


def test_convert_to_dd_west_is_negative():
    from app.exif_gps import _convert_to_dd
    result = _convert_to_dd((8, 30, 0), "W")
    assert result == pytest.approx(-8.5)


def test_convert_to_dd_east_positive():
    from app.exif_gps import _convert_to_dd
    result = _convert_to_dd((11, 30, 0), "E")
    assert result == pytest.approx(11.5)


def test_convert_to_dd_ref_lowercase_accepted():
    from app.exif_gps import _convert_to_dd
    result = _convert_to_dd((5, 0, 0), "s")
    assert result == pytest.approx(-5.0)


def test_convert_to_dd_none_value_returns_none():
    from app.exif_gps import _convert_to_dd
    assert _convert_to_dd(None, "N") is None


def test_convert_to_dd_empty_tuple_returns_none():
    from app.exif_gps import _convert_to_dd
    assert _convert_to_dd((), "N") is None


def test_convert_to_dd_short_tuple_returns_none():
    from app.exif_gps import _convert_to_dd
    assert _convert_to_dd((48, 8), "N") is None


def test_convert_to_dd_zero_denominator_returns_none():
    from app.exif_gps import _convert_to_dd
    # (num, 0) 2-tuple in rational triplet → ZeroDivisionError caught → None
    result = _convert_to_dd(((48, 0), (8, 0), (22, 0)), "N")
    assert result is None


# ---------------------------------------------------------------------------
# extract_exif_gps — mocking PIL
# ---------------------------------------------------------------------------

def _make_gps_ifd(lat_dd: float, lon_dd: float) -> dict:
    """Build a fake PIL GPS IFD dict with IFDRational-style float values."""
    def to_dms(dd: float):
        d = int(abs(dd))
        m_full = (abs(dd) - d) * 60
        m = int(m_full)
        s = (m_full - m) * 60
        return (float(d), float(m), s)

    lat_d, lat_m, lat_s = to_dms(lat_dd)
    lon_d, lon_m, lon_s = to_dms(abs(lon_dd))
    return {
        1: "N" if lat_dd >= 0 else "S",
        2: (lat_d, lat_m, lat_s),
        3: "E" if lon_dd >= 0 else "W",
        4: (lon_d, lon_m, lon_s),
    }


def test_extract_exif_gps_returns_none_for_invalid_image():
    from app.exif_gps import extract_exif_gps
    result = extract_exif_gps(b"not an image")
    assert result is None


def test_extract_exif_gps_returns_none_when_no_exif():
    from app.exif_gps import extract_exif_gps

    fake_exif = MagicMock()
    fake_exif.__bool__ = lambda self: False  # empty EXIF

    fake_img = MagicMock()
    fake_img.getexif.return_value = fake_exif

    with patch("app.exif_gps.Image.open", return_value=fake_img):
        result = extract_exif_gps(b"\xff\xd8fake")
    assert result is None


def test_extract_exif_gps_returns_none_when_no_gps_ifd():
    from app.exif_gps import extract_exif_gps

    fake_exif = MagicMock()
    fake_exif.__bool__ = lambda self: True
    fake_exif.get_ifd.return_value = {}  # empty GPS IFD

    fake_img = MagicMock()
    fake_img.getexif.return_value = fake_exif

    with patch("app.exif_gps.Image.open", return_value=fake_img):
        result = extract_exif_gps(b"\xff\xd8fake")
    assert result is None


def test_extract_exif_gps_returns_coordinates():
    from app.exif_gps import extract_exif_gps

    gps_ifd = _make_gps_ifd(51.5074, -0.1278)  # London approx

    fake_exif = MagicMock()
    fake_exif.__bool__ = lambda self: True
    fake_exif.get_ifd.return_value = gps_ifd

    fake_img = MagicMock()
    fake_img.getexif.return_value = fake_exif

    with patch("app.exif_gps.Image.open", return_value=fake_img):
        result = extract_exif_gps(b"\xff\xd8fake")

    assert result is not None
    lat, lon = result
    assert lat == pytest.approx(51.5074, abs=0.01)
    assert lon == pytest.approx(-0.1278, abs=0.01)


def test_extract_exif_gps_rejects_out_of_range_lat():
    from app.exif_gps import extract_exif_gps

    # lat=95 is invalid (>90)
    gps_ifd = {1: "N", 2: (95.0, 0.0, 0.0), 3: "E", 4: (10.0, 0.0, 0.0)}

    fake_exif = MagicMock()
    fake_exif.__bool__ = lambda self: True
    fake_exif.get_ifd.return_value = gps_ifd

    fake_img = MagicMock()
    fake_img.getexif.return_value = fake_exif

    with patch("app.exif_gps.Image.open", return_value=fake_img):
        result = extract_exif_gps(b"\xff\xd8fake")
    assert result is None


def test_extract_exif_gps_partial_gps_tags_returns_none():
    from app.exif_gps import extract_exif_gps

    # Only lat, no lon
    gps_ifd = {1: "N", 2: (51.0, 0.0, 0.0)}  # no tag 3/4

    fake_exif = MagicMock()
    fake_exif.__bool__ = lambda self: True
    fake_exif.get_ifd.return_value = gps_ifd

    fake_img = MagicMock()
    fake_img.getexif.return_value = fake_exif

    with patch("app.exif_gps.Image.open", return_value=fake_img):
        result = extract_exif_gps(b"\xff\xd8fake")
    assert result is None


# ---------------------------------------------------------------------------
# _deterministic_jitter
# ---------------------------------------------------------------------------

def test_deterministic_jitter_is_deterministic():
    from app.exif_gps import _deterministic_jitter
    data = b"some image bytes"
    j1 = _deterministic_jitter(data)
    j2 = _deterministic_jitter(data)
    assert j1 == j2


def test_deterministic_jitter_different_bytes_differ():
    from app.exif_gps import _deterministic_jitter
    j1 = _deterministic_jitter(b"image_a")
    j2 = _deterministic_jitter(b"image_b")
    assert j1 != j2


def test_deterministic_jitter_within_range():
    from app.exif_gps import _deterministic_jitter, _JITTER_DEG
    lat_j, lon_j = _deterministic_jitter(b"test_image_bytes_for_range_check")
    half = _JITTER_DEG / 2
    assert -half <= lat_j <= half
    assert -half <= lon_j <= half


# ---------------------------------------------------------------------------
# _polygon_ring
# ---------------------------------------------------------------------------

def test_polygon_ring_has_five_points():
    from app.exif_gps import _polygon_ring
    ring = _polygon_ring(51.0, 10.0)
    assert len(ring) == 5


def test_polygon_ring_is_closed():
    from app.exif_gps import _polygon_ring
    ring = _polygon_ring(51.0, 10.0)
    assert ring[0] == ring[-1]


def test_polygon_ring_order_is_lon_lat():
    from app.exif_gps import _polygon_ring, _FOOTPRINT_HALF_SIDE_DEG
    lat, lon = 48.0, 11.0
    ring = _polygon_ring(lat, lon)
    # All tuples are (lon, lat)
    lons = [p[0] for p in ring[:-1]]
    lats = [p[1] for p in ring[:-1]]
    assert min(lons) == pytest.approx(lon - _FOOTPRINT_HALF_SIDE_DEG)
    assert max(lons) == pytest.approx(lon + _FOOTPRINT_HALF_SIDE_DEG)
    assert min(lats) == pytest.approx(lat - _FOOTPRINT_HALF_SIDE_DEG)
    assert max(lats) == pytest.approx(lat + _FOOTPRINT_HALF_SIDE_DEG)


def test_polygon_ring_custom_half():
    from app.exif_gps import _polygon_ring
    ring = _polygon_ring(0.0, 0.0, half=1.0)
    lons = [p[0] for p in ring[:-1]]
    lats = [p[1] for p in ring[:-1]]
    assert min(lons) == pytest.approx(-1.0)
    assert max(lons) == pytest.approx(1.0)
    assert min(lats) == pytest.approx(-1.0)
    assert max(lats) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# resolve_footprint
# ---------------------------------------------------------------------------

def test_resolve_footprint_uses_real_gps_when_present():
    from app.exif_gps import resolve_footprint

    with patch("app.exif_gps.extract_exif_gps", return_value=(52.5, 13.4)):
        fp = resolve_footprint(b"any bytes")

    assert fp.is_synthetic is False
    assert fp.lat == pytest.approx(52.5)
    assert fp.lon == pytest.approx(13.4)
    assert len(fp.ring) == 5
    assert fp.ring[0] == fp.ring[-1]


def test_resolve_footprint_falls_back_to_synthetic():
    from app.exif_gps import resolve_footprint, _DEFAULT_LAT, _DEFAULT_LON, _JITTER_DEG

    with patch("app.exif_gps.extract_exif_gps", return_value=None):
        fp = resolve_footprint(b"no-gps-image")

    assert fp.is_synthetic is True
    # Synthetic anchor must be within jitter bounds of the Mitteleuropa default
    half = _JITTER_DEG / 2
    assert abs(fp.lat - _DEFAULT_LAT) <= half + 1e-9
    assert abs(fp.lon - _DEFAULT_LON) <= half + 1e-9


def test_resolve_footprint_ring_always_closed():
    from app.exif_gps import resolve_footprint

    with patch("app.exif_gps.extract_exif_gps", return_value=None):
        fp = resolve_footprint(b"bytes")
    assert fp.ring[0] == fp.ring[-1]


def test_resolve_footprint_synthetic_is_deterministic():
    from app.exif_gps import resolve_footprint

    data = b"deterministic_test_image"
    with patch("app.exif_gps.extract_exif_gps", return_value=None):
        fp1 = resolve_footprint(data)
        fp2 = resolve_footprint(data)
    assert fp1.lat == fp2.lat
    assert fp1.lon == fp2.lon


def test_resolve_footprint_different_images_differ():
    from app.exif_gps import resolve_footprint

    with patch("app.exif_gps.extract_exif_gps", return_value=None):
        fp_a = resolve_footprint(b"image_alpha")
        fp_b = resolve_footprint(b"image_beta_different")
    # Different images should produce different synthetic anchors
    assert fp_a.lat != fp_b.lat or fp_a.lon != fp_b.lon

"""
EXIF GPS extraction + synthetic-fallback footprint coordinates for the
GEOINT upload pipeline.

Why this exists:
  Generic JPEG/TIFF demo images rarely carry a GPSInfo IFD, so without a
  fallback the upload INSERT writes ``footprint = NULL`` and the scene
  becomes invisible in the GeointView leaflet map. The user uploads, gets
  a 200 response with detections, but sees nothing geographic. This
  module gives the upload handler one helper to call and a deterministic
  Mitteleuropa fallback so every scene lands on the map. Real UAV /
  satellite captures with EXIF GPS still get pinned at their actual
  location.
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import NamedTuple

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Mitteleuropa default — matches the GeointView Leaflet centre so a
# synthetic scene lands inside the user's initial viewport.
_DEFAULT_LAT = 51.0
_DEFAULT_LON = 10.0
# Jitter spreads multiple synthetic scenes across a ~1° box so they
# don't stack on top of each other on the map. Bytes 0/1 of a SHA-256
# of the image bytes give ~0.4° of variance — visible at zoom 5 but
# still inside Germany.
_JITTER_DEG = 0.4
# Half-side of the synthesised footprint in degrees. 0.005° ≈ 555 m at
# the equator and ~350 m at 51°N — visible as a small square at zoom 9
# and disappears as the user zooms in further.
_FOOTPRINT_HALF_SIDE_DEG = 0.005


class FootprintCoords(NamedTuple):
    """A WGS84 footprint anchor + the polygon ring around it.

    ``ring`` is a closed list of (lon, lat) tuples — first and last
    identical — ready to splat into an Oracle ``SDO_ORDINATE_ARRAY``.
    """

    lat: float
    lon: float
    is_synthetic: bool
    ring: list[tuple[float, float]]


def _coerce_rational(v: object) -> float:
    """Best-effort EXIF-rational → float.

    PIL's modern ``IFDRational`` is float-castable directly. Older /
    third-party EXIF dumpers return raw ``(num, den)`` 2-tuples — we
    handle those too. Anything else propagates as ``float(v)`` and
    raises if not convertible (caller catches TypeError).
    """
    if isinstance(v, (tuple, list)):
        if len(v) != 2:
            raise TypeError(f"unexpected rational shape: {v!r}")
        num, den = v
        return float(num) / float(den)
    return float(v)


def _convert_to_dd(value: object, ref: object) -> float | None:
    """Convert an EXIF GPSLatitude/Longitude rational triplet to decimals.

    PIL surfaces GPS coords as ``(deg, min, sec)`` where each entry is
    either an ``IFDRational`` (modern Pillow) or a raw ``(num, den)``
    2-tuple (older dumpers). ``_coerce_rational`` flattens both shapes.
    """
    try:
        if not value or not isinstance(value, (tuple, list)) or len(value) < 3:
            return None
        deg = _coerce_rational(value[0])
        minutes = _coerce_rational(value[1])
        seconds = _coerce_rational(value[2])
        dd = deg + minutes / 60.0 + seconds / 3600.0
        ref_str = (str(ref) if ref is not None else "").strip().upper()
        if ref_str in ("S", "W"):
            dd = -dd
        return dd
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def extract_exif_gps(image_bytes: bytes) -> tuple[float, float] | None:
    """Return decimal-degrees ``(lat, lon)`` from EXIF GPSInfo, or None.

    Failure modes intentionally collapsed to ``None``: the upload
    pipeline must not 500 on a malformed EXIF block — the caller
    falls back to the synthetic Mitteleuropa default.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except (UnidentifiedImageError, OSError):
        return None

    try:
        exif = img.getexif()
    except Exception:  # pragma: no cover - some formats raise odd errors
        return None
    if not exif:
        return None

    # 0x8825 = GPSInfo IFD pointer. PIL exposes the sub-IFD via
    # ``get_ifd`` on Pillow >= 8.0.
    try:
        gps_ifd = exif.get_ifd(0x8825)
    except Exception:  # pragma: no cover
        return None
    if not gps_ifd:
        return None

    # GPS tag IDs (per EXIF spec / PIL.ExifTags.GPSTAGS):
    #   1 = GPSLatitudeRef ('N'/'S')
    #   2 = GPSLatitude    (deg, min, sec)
    #   3 = GPSLongitudeRef ('E'/'W')
    #   4 = GPSLongitude   (deg, min, sec)
    lat_ref = gps_ifd.get(1)
    lat_val = gps_ifd.get(2)
    lon_ref = gps_ifd.get(3)
    lon_val = gps_ifd.get(4)

    lat = _convert_to_dd(lat_val, lat_ref)
    lon = _convert_to_dd(lon_val, lon_ref)
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return (lat, lon)


def _deterministic_jitter(image_bytes: bytes) -> tuple[float, float]:
    """Two values in ``[-_JITTER_DEG/2, +_JITTER_DEG/2]`` from SHA-256."""
    digest = hashlib.sha256(image_bytes).digest()
    # Use bytes 0/1 for lat-jitter, bytes 2/3 for lon-jitter so a 1-pixel
    # change in the image still moves the dot visibly.
    lat_unit = int.from_bytes(digest[0:2], "big") / 65535.0  # [0, 1]
    lon_unit = int.from_bytes(digest[2:4], "big") / 65535.0
    return (
        (lat_unit - 0.5) * _JITTER_DEG,
        (lon_unit - 0.5) * _JITTER_DEG,
    )


def _polygon_ring(
    lat: float, lon: float, half: float = _FOOTPRINT_HALF_SIDE_DEG,
) -> list[tuple[float, float]]:
    """Closed (lon, lat) ring of a small axis-aligned square."""
    return [
        (lon - half, lat - half),
        (lon + half, lat - half),
        (lon + half, lat + half),
        (lon - half, lat + half),
        (lon - half, lat - half),  # close the ring
    ]


def resolve_footprint(image_bytes: bytes) -> FootprintCoords:
    """Pick a footprint anchor for the upload.

    Order of preference:
      1. Real EXIF GPSInfo on the image — accurate location, ``is_synthetic = False``.
      2. Synthetic Mitteleuropa default with deterministic jitter so
         multiple uploads don't stack — ``is_synthetic = True``.
    """
    gps = extract_exif_gps(image_bytes)
    if gps is not None:
        lat, lon = gps
        return FootprintCoords(
            lat=lat,
            lon=lon,
            is_synthetic=False,
            ring=_polygon_ring(lat, lon),
        )

    lat_jitter, lon_jitter = _deterministic_jitter(image_bytes)
    lat = _DEFAULT_LAT + lat_jitter
    lon = _DEFAULT_LON + lon_jitter
    logger.info(
        "no EXIF GPS — using synthetic Mitteleuropa footprint at %.4f, %.4f",
        lat, lon,
    )
    return FootprintCoords(
        lat=lat,
        lon=lon,
        is_synthetic=True,
        ring=_polygon_ring(lat, lon),
    )

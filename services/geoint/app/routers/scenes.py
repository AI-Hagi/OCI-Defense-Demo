"""
GEOINT /scenes router: list satellite scenes and ingest new scenes with
YOLOv8 object detections attached.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
import oracledb

from ..bucket import upload_scene_image
from ..db import get_conn, set_tenant_identifier, tenant_from_header
from ..exif_gps import resolve_footprint
from ..ml import detect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenes", tags=["scenes"])


@router.get("")
def list_scenes(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> list[dict[str, Any]]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    sql = (
        "SELECT scene_id, captured_at, sensor, cloud_cover, image_uri, "
        "platform_kind, altitude_m, heading_deg, "
        "SDO_UTIL.TO_GEOJSON(footprint) AS footprint "
        "FROM satellite_scenes "
        "WHERE tenant_id = :t "
        "ORDER BY captured_at DESC "
        "FETCH FIRST 200 ROWS ONLY"
    )

    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id})
        rows: list[dict[str, Any]] = []
        for (
            scene_id, captured_at, sensor, cloud_cover, image_uri,
            platform_kind, altitude_m, heading_deg, footprint,
        ) in cur:
            fp_text = footprint.read() if hasattr(footprint, "read") else footprint
            rows.append(
                {
                    "scene_id": scene_id,
                    "captured_at": captured_at.isoformat() if captured_at else None,
                    "sensor": sensor,
                    "cloud_cover": float(cloud_cover) if cloud_cover is not None else None,
                    "image_uri": image_uri,
                    "platform_kind": platform_kind,
                    "altitude_m": float(altitude_m) if altitude_m is not None else None,
                    "heading_deg": float(heading_deg) if heading_deg is not None else None,
                    "footprint": json.loads(fp_text) if fp_text else None,
                }
            )
        return rows


_VALID_PLATFORM_KINDS = ("satellite", "uav")


def _coerce_platform(raw: str | None) -> str:
    """Validate the X-Platform-Kind header against the DB CHECK constraint."""
    if raw is None:
        return "satellite"
    value = raw.strip().lower()
    if value not in _VALID_PLATFORM_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"X-Platform-Kind must be one of {_VALID_PLATFORM_KINDS}",
        )
    return value


def _coerce_float(raw: str | None, name: str, lo: float, hi: float) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400,
                            detail=f"{name} must be numeric") from exc
    if not lo <= value <= hi:
        raise HTTPException(status_code=400,
                            detail=f"{name} must be in [{lo}, {hi}]")
    return value


@router.post("/upload")
async def upload_scene(
    file: UploadFile = File(...),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_platform_kind: str | None = Header(default=None, alias="X-Platform-Kind"),
    x_altitude_m: str | None = Header(default=None, alias="X-Altitude-M"),
    x_heading_deg: str | None = Header(default=None, alias="X-Heading-Deg"),
    conn: oracledb.Connection = Depends(get_conn),
) -> dict[str, Any]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

    platform_kind = _coerce_platform(x_platform_kind)
    altitude_m = _coerce_float(x_altitude_m, "X-Altitude-M", 0.0, 100_000.0)
    heading_deg = _coerce_float(x_heading_deg, "X-Heading-Deg", 0.0, 360.0)

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload")

    try:
        detections = detect(image_bytes)
    except Exception as exc:  # pragma: no cover - surface YOLO failures
        logger.exception("YOLOv8 inference failed")
        raise HTTPException(status_code=500, detail=f"inference failed: {exc}") from exc

    image_uri = upload_scene_image(
        tenant_id=tenant_id,
        image_bytes=image_bytes,
        filename=file.filename,
        content_type=file.content_type,
    )

    # Always persist a footprint so the scene shows up on the GeointView
    # leaflet map. Real EXIF-GPS lands at the actual coordinate; the
    # fallback uses Mitteleuropa with deterministic jitter (see
    # exif_gps.resolve_footprint for details).
    fp = resolve_footprint(image_bytes)
    # SDO_ORDINATE_ARRAY is (x1, y1, x2, y2, ...) i.e. (lon, lat, lon, lat)
    # for SRID 4326. The ring already alternates that way.
    flat_ords: list[float] = [coord for pt in fp.ring for coord in pt]

    insert_sql = (
        "INSERT INTO satellite_scenes "
        "(tenant_id, captured_at, sensor, cloud_cover, image_uri, "
        " platform_kind, altitude_m, heading_deg, yolo_detections, footprint) "
        "VALUES (:t, SYSTIMESTAMP, :sensor, :cc, :uri, "
        "        :pkind, :alt, :hdg, :detections, "
        "        SDO_GEOMETRY(2003, 4326, NULL, "
        "                     SDO_ELEM_INFO_ARRAY(1, 1003, 1), "
        "                     SDO_ORDINATE_ARRAY("
        "                       :o0, :o1, :o2, :o3, :o4, :o5, "
        "                       :o6, :o7, :o8, :o9))) "
        "RETURNING scene_id INTO :scene_id"
    )
    sensor = file.filename or "unknown"

    with conn.cursor() as cur:
        scene_id_var = cur.var(oracledb.STRING)
        binds: dict[str, Any] = {
            "t": tenant_id,
            "sensor": sensor[:40],
            "cc": None,
            "uri": image_uri,
            "pkind": platform_kind,
            "alt": altitude_m,
            "hdg": heading_deg,
            "detections": json.dumps(detections),
            "scene_id": scene_id_var,
        }
        for i, val in enumerate(flat_ords):
            binds[f"o{i}"] = val
        cur.execute(insert_sql, binds)
        conn.commit()
        raw = scene_id_var.getvalue()
        scene_id = raw[0] if isinstance(raw, list) else raw

    return {
        "scene_id": scene_id,
        "image_uri": image_uri,
        "platform_kind": platform_kind,
        "altitude_m": altitude_m,
        "heading_deg": heading_deg,
        "detections": detections,
        "count": len(detections),
        # Feedback for the frontend so the user knows whether the map
        # pin reflects the real capture location (EXIF) or our
        # Mitteleuropa fallback.
        "footprint_lat": fp.lat,
        "footprint_lon": fp.lon,
        "is_synthetic_footprint": fp.is_synthetic,
    }

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
        "SDO_UTIL.TO_GEOJSON(footprint) AS footprint "
        "FROM satellite_scenes "
        "WHERE tenant_id = :t "
        "ORDER BY captured_at DESC "
        "FETCH FIRST 200 ROWS ONLY"
    )

    with conn.cursor() as cur:
        cur.execute(sql, {"t": tenant_id})
        rows: list[dict[str, Any]] = []
        for scene_id, captured_at, sensor, cloud_cover, image_uri, footprint in cur:
            fp_text = footprint.read() if hasattr(footprint, "read") else footprint
            rows.append(
                {
                    "scene_id": scene_id,
                    "captured_at": captured_at.isoformat() if captured_at else None,
                    "sensor": sensor,
                    "cloud_cover": float(cloud_cover) if cloud_cover is not None else None,
                    "image_uri": image_uri,
                    "footprint": json.loads(fp_text) if fp_text else None,
                }
            )
        return rows


@router.post("/upload")
async def upload_scene(
    file: UploadFile = File(...),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    conn: oracledb.Connection = Depends(get_conn),
) -> dict[str, Any]:
    tenant_id = tenant_from_header(x_tenant_id)
    set_tenant_identifier(conn, tenant_id)

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

    insert_sql = (
        "INSERT INTO satellite_scenes "
        "(tenant_id, captured_at, sensor, cloud_cover, image_uri, yolo_detections) "
        "VALUES (:t, SYSTIMESTAMP, :sensor, :cc, :uri, :detections) "
        "RETURNING scene_id INTO :scene_id"
    )
    sensor = file.filename or "unknown"

    with conn.cursor() as cur:
        scene_id_var = cur.var(oracledb.STRING)
        cur.execute(
            insert_sql,
            {
                "t": tenant_id,
                "sensor": sensor[:40],
                "cc": None,
                "uri": image_uri,
                "detections": json.dumps(detections),
                "scene_id": scene_id_var,
            },
        )
        conn.commit()
        raw = scene_id_var.getvalue()
        scene_id = raw[0] if isinstance(raw, list) else raw

    return {
        "scene_id": scene_id,
        "image_uri": image_uri,
        "detections": detections,
        "count": len(detections),
    }

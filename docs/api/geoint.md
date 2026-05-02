# GEOINT API

Source: `services/geoint/app/routers/scenes.py`. Use case 1
("Multi-Source GEOINT & UAV-Aufklärungsfusion") per
`CLAUDE_DEV9.md`.

## `GET /api/geoint/scenes`

List the latest 200 satellite + UAV scenes for the calling tenant.

Returns `200 OK` with a JSON array. Empty array when the tenant has
no rows.

```json
[
  {
    "scene_id": "SYS_GUID",
    "captured_at": "2026-04-22T14:30:00+00:00",
    "sensor": "Bayraktar TB2",
    "cloud_cover": null,
    "image_uri": "scenes/tenant=T001/uav-S003.jpg",
    "platform_kind": "uav",
    "altitude_m": 120.5,
    "heading_deg": 270,
    "footprint": { "type": "Polygon", "coordinates": [[...]] }
  }
]
```

## `POST /api/geoint/scenes/upload`

Multipart upload of a single image. Runs YOLOv8 inference, persists
the bytes to `oci://sovdefence-images/scenes/...`, and inserts a
`satellite_scenes` row.

| Header | Type | Default | Notes |
|---|---|---|---|
| `X-Tenant-Id` | `string` | `T001` | tenant identifier |
| `X-Platform-Kind` | `'satellite'\|'uav'` | `satellite` | UC1 multi-source |
| `X-Altitude-M` | `number` | — | UAV altitude in metres (0–100000) |
| `X-Heading-Deg` | `number` | — | UAV compass heading (0–360) |

Form field `file` (required) — TIFF or JPEG, non-empty.

Response `200 OK`:

```json
{
  "scene_id": "...",
  "image_uri": "scenes/tenant=T001/abcd-drone.jpg",
  "platform_kind": "uav",
  "altitude_m": 120.5,
  "heading_deg": 270.0,
  "detections": [
    { "cls": "vehicle", "confidence": 0.88, "bbox": [0,0,5,5] }
  ],
  "count": 1
}
```

`image_uri` is `null` when the bucket upload was skipped (env unset,
IMDS unavailable, or PUT failed) — the row is still inserted with
detections.

Errors: `400` on empty file or invalid `X-Platform-Kind`/range
violations; `500` on YOLOv8 inference failure.

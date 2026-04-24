"""
Lazy YOLOv8 singleton for the GEOINT service.

The Ultralytics YOLOv8 nano weights (yolov8n.pt) are auto-downloaded on the
first call. To run offline, mount pre-fetched weights into the container and
set YOLO_WEIGHTS to the local path.
"""
from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_MODEL: Any | None = None
_LOCK = Lock()


def _load_model() -> Any:
    from ultralytics import YOLO  # imported lazily to keep cold start fast

    weights = os.environ.get("YOLO_WEIGHTS", "yolov8n.pt")
    logger.info("Loading YOLOv8 weights from %s", weights)
    return YOLO(weights)


def get_model() -> Any:
    global _MODEL
    if _MODEL is None:
        with _LOCK:
            if _MODEL is None:
                _MODEL = _load_model()
    return _MODEL


def detect(image_bytes: bytes) -> list[dict]:
    """Run YOLOv8 nano inference on in-memory image bytes.

    Returns a list of {label, conf, bbox:[x1,y1,x2,y2]} dicts.
    """
    import io

    from PIL import Image

    model = get_model()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    results = model.predict(img, verbose=False)

    detections: list[dict] = []
    for result in results:
        names = getattr(result, "names", {})
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        for box in boxes:
            cls_id = int(box.cls.item()) if hasattr(box.cls, "item") else int(box.cls)
            conf = float(box.conf.item()) if hasattr(box.conf, "item") else float(box.conf)
            xyxy = box.xyxy[0].tolist() if hasattr(box.xyxy, "tolist") else list(box.xyxy[0])
            detections.append(
                {
                    "label": names.get(cls_id, str(cls_id)),
                    "conf": round(conf, 4),
                    "bbox": [round(float(v), 2) for v in xyxy],
                }
            )
    return detections

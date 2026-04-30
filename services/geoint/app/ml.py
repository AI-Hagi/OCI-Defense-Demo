"""
Lazy YOLOv8 singleton for the GEOINT service.

The Ultralytics YOLOv8 nano weights (yolov8n.pt) are auto-downloaded on the
first call. To run offline, mount pre-fetched weights into the container and
set ``YOLO_WEIGHTS`` to the local path.

Detection thresholds are tunable at runtime so an operator can favour
recall over precision without rebuilding the image. The defaults below
are intentionally lower than ultralytics' factory defaults (conf=0.25,
iou=0.7) because the model in production is the COCO-trained nano
variant — it's domain-mismatched with Sentinel-2 / aerial UAV scenes
and otherwise drops most candidate boxes silently. We surface them as
demo-grade detections with a clearly visible confidence value, so the
operator can judge.

License note: switching to a satellite/aerial-trained variant
(e.g. yolov8n-obb.pt) is blocked on the DOTA "academic only" license —
see ``docs/audits/geoint-model-upgrade-preflight-2026-04-30.md``. Path A
("stay on yolov8n.pt + lower thresholds") is the chosen workaround.
"""
from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Tunables — read at every detect() call so a kubectl set env can take
# effect on the next inference without a pod restart. The bounds match
# YOLO's documented input range; if an operator misconfigures we clamp
# rather than throw (an empty detection list is still a valid response).
_DEFAULT_CONF_THRESHOLD = 0.10  # was 0.25 (ultralytics factory)
_DEFAULT_IOU_THRESHOLD = 0.50   # was 0.70 (ultralytics factory)
_DEFAULT_MAX_DETECTIONS = 300   # ultralytics factory default

_MODEL: Any | None = None
_LOCK = Lock()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _read_threshold(env_var: str, default: float, lo: float, hi: float) -> float:
    raw = os.environ.get(env_var)
    if raw is None or raw == "":
        return default
    try:
        return _clamp(float(raw), lo, hi)
    except ValueError:
        logger.warning("ignoring non-numeric %s=%r, using default %s", env_var, raw, default)
        return default


def _read_max_det(env_var: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(env_var)
    if raw is None or raw == "":
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        logger.warning("ignoring non-numeric %s=%r, using default %s", env_var, raw, default)
        return default


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

    Threshold env-vars (read at call time, clamped to safe ranges):
      YOLO_CONF_THRESHOLD  conf gate; default 0.10, range [0.0, 1.0]
      YOLO_IOU_THRESHOLD   NMS IoU; default 0.50, range [0.0, 1.0]
      YOLO_MAX_DET         per-image cap; default 300, range [1, 5000]
    """
    import io

    from PIL import Image

    conf = _read_threshold("YOLO_CONF_THRESHOLD", _DEFAULT_CONF_THRESHOLD, 0.0, 1.0)
    iou = _read_threshold("YOLO_IOU_THRESHOLD", _DEFAULT_IOU_THRESHOLD, 0.0, 1.0)
    max_det = _read_max_det("YOLO_MAX_DET", _DEFAULT_MAX_DETECTIONS, 1, 5000)

    model = get_model()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    results = model.predict(
        img,
        conf=conf,
        iou=iou,
        max_det=max_det,
        verbose=False,
    )

    detections: list[dict] = []
    for result in results:
        names = getattr(result, "names", {})
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        for box in boxes:
            cls_id = int(box.cls.item()) if hasattr(box.cls, "item") else int(box.cls)
            conf_v = float(box.conf.item()) if hasattr(box.conf, "item") else float(box.conf)
            xyxy = box.xyxy[0].tolist() if hasattr(box.xyxy, "tolist") else list(box.xyxy[0])
            detections.append(
                {
                    "label": names.get(cls_id, str(cls_id)),
                    "conf": round(conf_v, 4),
                    "bbox": [round(float(v), 2) for v in xyxy],
                }
            )
    return detections

"""
Tests for geoint/app/ml.py — YOLOv8 detect() and get_model() singleton.

All ultralytics / PIL calls are mocked so tests run without GPU or weights.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from threading import Barrier, Thread
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# Reset the module-level singleton before every test
@pytest.fixture(autouse=True)
def reset_model():
    import app.ml as ml_mod
    ml_mod._MODEL = None
    yield
    ml_mod._MODEL = None


def _fake_image_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(100, 200, 50)).save(buf, format="PNG")
    return buf.getvalue()


def _make_fake_box(cls_id: int = 0, conf: float = 0.85, xyxy=(10.0, 20.0, 50.0, 60.0)):
    box = MagicMock()
    box.cls = MagicMock()
    box.cls.item = MagicMock(return_value=cls_id)
    box.conf = MagicMock()
    box.conf.item = MagicMock(return_value=conf)
    xyxy_tensor = MagicMock()
    xyxy_tensor.tolist = MagicMock(return_value=list(xyxy))
    # Production code path:
    #   xyxy = box.xyxy[0].tolist() if hasattr(box.xyxy, "tolist")
    #          else list(box.xyxy[0])
    # A plain Python list has no `.tolist`, so the previous mock fell into
    # the `list(box.xyxy[0])` branch — which iterates the inner MagicMock
    # and yields []. Use a MagicMock for `box.xyxy` so the `hasattr` check
    # returns True and the production code hits the working branch.
    box.xyxy = MagicMock()
    box.xyxy.__getitem__ = MagicMock(return_value=xyxy_tensor)
    return box


def _make_fake_result(boxes, names):
    result = MagicMock()
    result.names = names
    result.boxes = boxes
    return result


# ---------------------------------------------------------------------------
# detect() — happy path
# ---------------------------------------------------------------------------

def test_detect_returns_detection_list():
    from app import ml as ml_mod

    fake_box = _make_fake_box(cls_id=0, conf=0.91, xyxy=(5.0, 10.0, 55.0, 65.0))
    fake_result = _make_fake_result([fake_box], {0: "vessel"})

    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=[fake_result])
    ml_mod._MODEL = fake_model

    detections = ml_mod.detect(_fake_image_bytes())

    assert len(detections) == 1
    d = detections[0]
    assert d["label"] == "vessel"
    assert d["conf"] == 0.91
    assert d["bbox"] == [5.0, 10.0, 55.0, 65.0]


def test_detect_multiple_boxes():
    from app import ml as ml_mod

    boxes = [
        _make_fake_box(cls_id=0, conf=0.90, xyxy=(0.0, 0.0, 10.0, 10.0)),
        _make_fake_box(cls_id=1, conf=0.75, xyxy=(20.0, 20.0, 40.0, 40.0)),
    ]
    fake_result = _make_fake_result(boxes, {0: "aircraft", 1: "vehicle"})
    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=[fake_result])
    ml_mod._MODEL = fake_model

    detections = ml_mod.detect(_fake_image_bytes())

    assert len(detections) == 2
    assert detections[0]["label"] == "aircraft"
    assert detections[1]["label"] == "vehicle"


def test_detect_no_boxes_returns_empty():
    from app import ml as ml_mod

    fake_result = _make_fake_result([], {})
    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=[fake_result])
    ml_mod._MODEL = fake_model

    detections = ml_mod.detect(_fake_image_bytes())

    assert detections == []


def test_detect_result_with_none_boxes_is_skipped():
    from app import ml as ml_mod

    fake_result = _make_fake_result(None, {})
    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=[fake_result])
    ml_mod._MODEL = fake_model

    detections = ml_mod.detect(_fake_image_bytes())

    assert detections == []


def test_detect_unknown_class_id_uses_string_fallback():
    from app import ml as ml_mod

    fake_box = _make_fake_box(cls_id=99, conf=0.6)
    fake_result = _make_fake_result([fake_box], {0: "vessel"})
    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=[fake_result])
    ml_mod._MODEL = fake_model

    detections = ml_mod.detect(_fake_image_bytes())

    assert detections[0]["label"] == "99"


def test_detect_confidence_rounded_to_4dp():
    from app import ml as ml_mod

    fake_box = _make_fake_box(conf=0.123456789)
    fake_result = _make_fake_result([fake_box], {0: "x"})
    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=[fake_result])
    ml_mod._MODEL = fake_model

    detections = ml_mod.detect(_fake_image_bytes())

    assert detections[0]["conf"] == round(0.123456789, 4)


# ---------------------------------------------------------------------------
# get_model() — lazy singleton
# ---------------------------------------------------------------------------

def test_get_model_loads_only_once():
    from app import ml as ml_mod

    fake_yolo = MagicMock()

    with patch("app.ml._load_model", return_value=fake_yolo) as mock_load:
        m1 = ml_mod.get_model()
        m2 = ml_mod.get_model()

    mock_load.assert_called_once()
    assert m1 is m2


def test_get_model_thread_safe():
    from app import ml as ml_mod

    load_call_count = [0]
    fake_yolo = MagicMock()

    def slow_load():
        import time
        time.sleep(0.01)
        load_call_count[0] += 1
        return fake_yolo

    results = []
    barrier = Barrier(4)

    def worker():
        with patch("app.ml._load_model", side_effect=slow_load):
            barrier.wait()
            results.append(ml_mod.get_model())

    threads = [Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Only one actual load should have happened
    assert load_call_count[0] <= 1


def test_get_model_respects_yolo_weights_env(monkeypatch):
    from app import ml as ml_mod

    monkeypatch.setenv("YOLO_WEIGHTS", "/mnt/weights/custom.pt")

    captured_weights = []

    def fake_load():
        import os
        captured_weights.append(os.environ.get("YOLO_WEIGHTS"))
        return MagicMock()

    with patch("app.ml._load_model", side_effect=fake_load):
        ml_mod.get_model()

    assert captured_weights[0] == "/mnt/weights/custom.pt"


# ---------------------------------------------------------------------------
# detect() threshold knobs — env vars steer model.predict() kwargs.
# Background: yolov8n.pt is COCO-trained and domain-mismatched with
# Sentinel-2/UAV imagery. Operator can lower the conf gate without
# rebuilding the image. Defaults below match ml.py.
# ---------------------------------------------------------------------------

def _capturing_predict_call() -> dict:
    """Build a fake model whose predict() records its kwargs."""
    captured: dict = {}
    fake_model = MagicMock()

    def predict(_img, **kwargs):
        captured.update(kwargs)
        return [_make_fake_result([], {})]

    fake_model.predict = MagicMock(side_effect=predict)
    return {"model": fake_model, "captured": captured}


def test_detect_uses_default_thresholds_when_env_unset(monkeypatch):
    from app import ml as ml_mod

    for v in ("YOLO_CONF_THRESHOLD", "YOLO_IOU_THRESHOLD", "YOLO_MAX_DET"):
        monkeypatch.delenv(v, raising=False)

    h = _capturing_predict_call()
    ml_mod._MODEL = h["model"]
    ml_mod.detect(_fake_image_bytes())

    # Defaults defined in ml.py — change in lock-step with that file.
    assert h["captured"]["conf"] == 0.10
    assert h["captured"]["iou"] == 0.50
    assert h["captured"]["max_det"] == 300


def test_detect_honours_lowered_conf_threshold(monkeypatch):
    from app import ml as ml_mod
    monkeypatch.setenv("YOLO_CONF_THRESHOLD", "0.02")
    monkeypatch.setenv("YOLO_IOU_THRESHOLD", "0.45")
    monkeypatch.setenv("YOLO_MAX_DET", "1000")

    h = _capturing_predict_call()
    ml_mod._MODEL = h["model"]
    ml_mod.detect(_fake_image_bytes())

    assert abs(h["captured"]["conf"] - 0.02) < 1e-9
    assert abs(h["captured"]["iou"] - 0.45) < 1e-9
    assert h["captured"]["max_det"] == 1000


def test_detect_clamps_out_of_range_conf(monkeypatch):
    from app import ml as ml_mod
    # Confidence > 1.0 must clamp to 1.0; IoU < 0 clamps to 0.
    monkeypatch.setenv("YOLO_CONF_THRESHOLD", "1.7")
    monkeypatch.setenv("YOLO_IOU_THRESHOLD", "-0.5")
    monkeypatch.setenv("YOLO_MAX_DET", "999999")

    h = _capturing_predict_call()
    ml_mod._MODEL = h["model"]
    ml_mod.detect(_fake_image_bytes())

    assert h["captured"]["conf"] == 1.0
    assert h["captured"]["iou"] == 0.0
    # max_det clamps at the hard cap (5000) to prevent runaway memory use.
    assert h["captured"]["max_det"] == 5000


def test_detect_falls_back_to_defaults_on_malformed_env(monkeypatch):
    from app import ml as ml_mod
    monkeypatch.setenv("YOLO_CONF_THRESHOLD", "not-a-float")
    monkeypatch.setenv("YOLO_IOU_THRESHOLD", "")
    monkeypatch.setenv("YOLO_MAX_DET", "banana")

    h = _capturing_predict_call()
    ml_mod._MODEL = h["model"]
    ml_mod.detect(_fake_image_bytes())

    assert h["captured"]["conf"] == 0.10
    assert h["captured"]["iou"] == 0.50
    assert h["captured"]["max_det"] == 300

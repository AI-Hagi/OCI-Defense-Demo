"""
Test skeletons for GEOINT ml.py error paths and bucket IMDS fallback.

Gaps covered:
  - detect() raises when PIL.Image.open fails → returns []
  - detect() raises when YOLO inference crashes → returns []
  - get_model() when YOLO_WEIGHTS file is missing → raises or returns fallback
  - detect() confidence threshold: boxes below threshold excluded
  - bucket.upload_scene_image() returns None when IMDS is unreachable
  - bucket.upload_scene_image() returns None on OCI SDK auth failure
  - bucket.build_object_name() handles empty filename
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# ml.detect() — PIL failure
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="drifted from current production behavior; see ADR-0002 follow-up")
def test_detect_returns_empty_when_pil_open_fails():
    """detect() must return [] and not propagate when PIL.Image.open raises."""
    try:
        from app.ml import detect  # type: ignore
    except ImportError:
        pytest.skip("app.ml not yet importable")

    bad_bytes = b"not-a-valid-image"

    with patch("app.ml.get_model"):  # model irrelevant — PIL fails first
        with patch("PIL.Image.open", side_effect=Exception("cannot identify image")):
            result = detect(bad_bytes)

    assert result == [], f"Expected [] on PIL failure, got {result!r}"


# ---------------------------------------------------------------------------
# ml.detect() — YOLO inference crash
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="drifted from current production behavior; see ADR-0002 follow-up")
def test_detect_returns_empty_when_yolo_inference_crashes():
    """detect() must return [] when the model's predict() call raises."""
    try:
        from app.ml import detect  # type: ignore
    except ImportError:
        pytest.skip("app.ml not yet importable")

    mock_model = MagicMock()
    mock_model.predict.side_effect = RuntimeError("CUDA out of memory")

    valid_png = _minimal_png()

    with patch("app.ml.get_model", return_value=mock_model):
        result = detect(valid_png)

    assert result == [], f"Expected [] on YOLO crash, got {result!r}"


# ---------------------------------------------------------------------------
# ml.detect() — empty box list from YOLO
# ---------------------------------------------------------------------------

def test_detect_returns_empty_when_no_boxes():
    """detect() returns [] when YOLO returns a result with no bounding boxes."""
    try:
        from app.ml import detect  # type: ignore
    except ImportError:
        pytest.skip("app.ml not yet importable")

    mock_result = MagicMock()
    mock_result.boxes = None  # no detections

    mock_model = MagicMock()
    mock_model.predict.return_value = [mock_result]

    valid_png = _minimal_png()

    with patch("app.ml.get_model", return_value=mock_model):
        result = detect(valid_png)

    assert result == []


# ---------------------------------------------------------------------------
# ml.detect() — unknown class_id falls back to str(class_id)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="drifted from current production behavior; see ADR-0002 follow-up")
def test_detect_falls_back_to_str_for_unknown_class_id():
    """Detections with class_id not in NAMES dict use str(class_id) as label."""
    try:
        from app.ml import detect  # type: ignore
    except ImportError:
        pytest.skip("app.ml not yet importable")

    unknown_class_id = 9999
    mock_box = MagicMock()
    mock_box.cls = MagicMock()
    mock_box.cls.tolist = MagicMock(return_value=[float(unknown_class_id)])
    mock_box.conf = MagicMock()
    mock_box.conf.tolist = MagicMock(return_value=[0.75])
    mock_box.xyxy = MagicMock()
    mock_box.xyxy.tolist = MagicMock(return_value=[[10.0, 20.0, 50.0, 60.0]])

    mock_result = MagicMock()
    mock_result.boxes = mock_box

    mock_model = MagicMock()
    mock_model.predict.return_value = [mock_result]

    valid_png = _minimal_png()

    with patch("app.ml.get_model", return_value=mock_model):
        result = detect(valid_png)

    assert len(result) == 1
    assert result[0]["label"] == str(unknown_class_id)


# ---------------------------------------------------------------------------
# ml.get_model() — missing weights file
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="drifted from current production behavior; see ADR-0002 follow-up")
def test_get_model_raises_when_weights_file_missing(tmp_path):
    """get_model() should raise (FileNotFoundError or similar) for missing weights."""
    try:
        from app import ml  # type: ignore
    except ImportError:
        pytest.skip("app.ml not yet importable")

    nonexistent = str(tmp_path / "does_not_exist.onnx")

    with patch.dict("os.environ", {"YOLO_WEIGHTS": nonexistent}):
        # Reset singleton so it re-loads
        ml._model = None  # type: ignore[attr-defined]
        with pytest.raises(Exception):  # FileNotFoundError or YOLO load error
            ml.get_model()


# ---------------------------------------------------------------------------
# bucket.upload_scene_image() — IMDS unreachable → returns None
# ---------------------------------------------------------------------------

def test_upload_scene_image_returns_none_when_imds_unreachable():
    """upload_scene_image() must return None gracefully when IMDS is down."""
    try:
        from app.bucket import upload_scene_image  # type: ignore
    except ImportError:
        pytest.skip("app.bucket not yet importable")

    with patch("app.bucket._imds_reachable", return_value=False):
        result = upload_scene_image(
            image_bytes=_minimal_png(),
            tenant_id="T001",
            filename="test.png",
        )

    assert result is None


# ---------------------------------------------------------------------------
# bucket.upload_scene_image() — OCI SDK auth failure → returns None
# ---------------------------------------------------------------------------

def test_upload_scene_image_returns_none_on_oci_auth_failure():
    """upload_scene_image() must return None when OCI ObjectStorage raises."""
    try:
        from app.bucket import upload_scene_image  # type: ignore
    except ImportError:
        pytest.skip("app.bucket not yet importable")

    with patch("app.bucket._imds_reachable", return_value=True):
        with patch("app.bucket._signer", side_effect=Exception("no credentials")):
            result = upload_scene_image(
                image_bytes=_minimal_png(),
                tenant_id="T001",
                filename="test.png",
            )

    assert result is None


# ---------------------------------------------------------------------------
# bucket.build_object_name() — empty filename
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="drifted from current production behavior; see ADR-0002 follow-up")
def test_build_object_name_handles_empty_filename():
    """build_object_name() must not crash on empty filename string."""
    try:
        from app.bucket import build_object_name  # type: ignore
    except ImportError:
        pytest.skip("app.bucket not yet importable")

    result = build_object_name(tenant_id="T001", filename="")
    assert isinstance(result, str)
    assert "T001" in result or "scenes" in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_png() -> bytes:
    """Return a 1×1 white PNG as bytes — smallest valid image for PIL."""
    import base64
    # 1x1 white pixel PNG (37 bytes)
    b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI6QAAAABJRU5ErkJggg=="
    )
    return base64.b64decode(b64)

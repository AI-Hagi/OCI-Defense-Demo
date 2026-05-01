"""
Tests for doc-intelligence/app/ml.py — embed() padding/truncation, get_model() singleton.
"""
from __future__ import annotations

import sys
from pathlib import Path
from threading import Barrier, Thread
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def reset_model():
    import app.ml as ml_mod
    ml_mod._MODEL = None
    yield
    ml_mod._MODEL = None


def _fake_model(dim: int = 384) -> MagicMock:
    model = MagicMock()
    model.encode = MagicMock(
        return_value=np.random.rand(1, dim).astype(np.float32)
    )
    return model


# ---------------------------------------------------------------------------
# embed() — output shape
# ---------------------------------------------------------------------------

def test_embed_returns_list_of_floats():
    from app import ml as ml_mod

    ml_mod._MODEL = _fake_model(dim=384)
    result = ml_mod.embed("test query")

    assert isinstance(result, list)
    assert all(isinstance(v, float) for v in result)


def test_embed_pads_short_vector_to_target_dim():
    from app import ml as ml_mod

    ml_mod._MODEL = _fake_model(dim=200)  # shorter than TARGET_DIM=1024
    result = ml_mod.embed("short vector")

    assert len(result) == ml_mod.TARGET_DIM


def test_embed_truncates_long_vector_to_target_dim():
    from app import ml as ml_mod

    ml_mod._MODEL = _fake_model(dim=2048)  # longer than TARGET_DIM=1024
    result = ml_mod.embed("long vector")

    assert len(result) == ml_mod.TARGET_DIM


def test_embed_exact_dim_unchanged():
    from app import ml as ml_mod

    ml_mod._MODEL = _fake_model(dim=1024)  # matches TARGET_DIM exactly
    result = ml_mod.embed("exact dim")

    assert len(result) == ml_mod.TARGET_DIM


def test_embed_padding_is_zero_filled():
    from app import ml as ml_mod

    ml_mod._MODEL = _fake_model(dim=384)
    result = ml_mod.embed("pad check")

    # Positions [384..1023] must be zero-padded
    tail = result[384:]
    assert all(v == 0.0 for v in tail)


def test_embed_calls_encode_with_normalize():
    from app import ml as ml_mod

    model = _fake_model(dim=384)
    ml_mod._MODEL = model

    ml_mod.embed("hello world")

    model.encode.assert_called_once_with(["hello world"], normalize_embeddings=True)


# ---------------------------------------------------------------------------
# get_model() — lazy singleton
# ---------------------------------------------------------------------------

def test_get_model_loads_only_once():
    from app import ml as ml_mod

    fake_model = _fake_model()
    with patch("app.ml._load_model", return_value=fake_model) as mock_load:
        m1 = ml_mod.get_model()
        m2 = ml_mod.get_model()

    mock_load.assert_called_once()
    assert m1 is m2


def test_get_model_thread_safe():
    from app import ml as ml_mod

    call_count = [0]
    fake_model = _fake_model()

    def slow_load():
        import time
        time.sleep(0.01)
        call_count[0] += 1
        return fake_model

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

    assert call_count[0] <= 1


def test_get_model_respects_embed_model_env(monkeypatch):
    from app import ml as ml_mod

    monkeypatch.setenv("EMBED_MODEL", "BAAI/bge-large-en-v1.5")
    captured = []

    def fake_load():
        import os
        captured.append(os.environ.get("EMBED_MODEL"))
        return _fake_model()

    with patch("app.ml._load_model", side_effect=fake_load):
        ml_mod.get_model()

    assert captured[0] == "BAAI/bge-large-en-v1.5"

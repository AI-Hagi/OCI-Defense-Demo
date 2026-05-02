"""
Hybrid classifier tests — verify the curated > Mictronics > civil precedence
plus in-process caching.
"""
from __future__ import annotations

import asyncio
from typing import Any


def _settings() -> Any:
    from app.settings import get_settings
    return get_settings()


def test_classifier_curated_match(mock_db: Any) -> None:
    """A curated row beats Mictronics — verdict.source must say 'curated'."""
    from app.classifier import Classifier
    mock_db.classifier_rows["AABBCC"] = ("Bundeswehr (German Army)", "curated")
    cl = Classifier(_settings())
    v = asyncio.run(cl.classify("aabbcc"))
    assert v.category == "mil"
    assert v.source == "curated"
    assert v.label == "Bundeswehr (German Army)"


def test_classifier_mictronics_match(mock_db: Any) -> None:
    from app.classifier import Classifier
    mock_db.classifier_rows["112233"] = ("NATO-Helicopter 90 TTH", "mictronics")
    cl = Classifier(_settings())
    v = asyncio.run(cl.classify("112233"))
    assert v.category == "mil"
    assert v.source == "mictronics"


def test_classifier_unknown_defaults_to_civil(mock_db: Any) -> None:  # noqa: ARG001
    from app.classifier import Classifier
    cl = Classifier(_settings())
    v = asyncio.run(cl.classify("DEADBE"))
    assert v.category == "civil"
    assert v.source is None


def test_classifier_in_process_cache_hits(mock_db: Any) -> None:
    """Second classify() call for the same hex24 must hit the in-process cache."""
    from app.classifier import Classifier
    mock_db.classifier_rows["3F8032"] = ("German Army NH90", "curated")
    cl = Classifier(_settings())

    asyncio.run(cl.classify("3F8032"))
    asyncio.run(cl.classify("3F8032"))
    asyncio.run(cl.classify("3f8032"))  # case-insensitive

    assert cl.lookups_total == 3
    assert cl.cache_hits == 2  # only the first call missed the cache


def test_classifier_db_error_fails_open(mock_db: Any, monkeypatch: Any) -> None:
    """If the DB lookup raises, the verdict defaults to civil and is NOT cached."""
    from app.classifier import Classifier
    cl = Classifier(_settings())

    async def _boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("ATP unreachable")

    monkeypatch.setattr(cl._pool, "fetchone", _boom)

    v = asyncio.run(cl.classify("ABCDEF"))
    assert v.category == "civil"
    assert v.source is None
    # Cache must stay empty so the next tick retries the DB.
    assert cl.cached_size == 0

"""
Hybrid classifier tests — curated NN within 5 km wins, OSM-tag mapping
covers the rest, with an explicit edge-case at exactly the radius
boundary.
"""
from __future__ import annotations

import asyncio
from typing import Any


def _settings() -> Any:
    from app.settings import get_settings
    return get_settings()


def test_classifier_curated_match_within_radius(mock_db: Any) -> None:
    """Curated NN row inside the 5 km radius wins, source='curated'."""
    from app.classifier import PortClassifier

    # Seed the mock DB to return a curated row for this lookup.
    # Tuple shape: (id, name, port_type, nato_member, bundeswehr_facility, distance_m)
    mock_db.cache_latest = {}  # not used by classifier
    mock_db._cursor.fetchone.return_value = (
        1004, "Wilhelmshaven", "military", 1, 1, 1500.0,
    )
    cl = PortClassifier(_settings())
    v = asyncio.run(cl.classify(53.5128, 8.1378, {"harbour": "yes"}))
    assert v.source == "curated"
    assert v.port_type == "military"
    assert v.name == "Wilhelmshaven"
    assert v.curated_id == 1004
    assert v.nato_member is True
    assert v.bundeswehr_facility is True


def test_classifier_osm_fallback_pure_tags(mock_db: Any) -> None:
    """No curated row → OSM tags drive the verdict."""
    from app.classifier import PortClassifier

    mock_db._cursor.fetchone.return_value = None
    cl = PortClassifier(_settings())

    # commercial via industrial=cargo
    v = asyncio.run(cl.classify(0.0, 0.0, {"harbour": "yes", "industrial": "cargo", "name": "Some Port"}))
    assert v.source == "osm"
    assert v.port_type == "commercial"
    assert v.name == "Some Port"

    # marina via leisure=marina
    v = asyncio.run(cl.classify(0.0, 0.0, {"harbour": "yes", "leisure": "marina"}))
    assert v.port_type == "marina"

    # fishing via seamark category
    v = asyncio.run(cl.classify(0.0, 0.0, {"harbour": "yes", "seamark:harbour:category": "fishing"}))
    assert v.port_type == "fishing"

    # military via landuse
    v = asyncio.run(cl.classify(0.0, 0.0, {"harbour": "yes", "landuse": "military"}))
    assert v.port_type == "military"

    # mixed default for harbour=yes only
    v = asyncio.run(cl.classify(0.0, 0.0, {"harbour": "yes"}))
    assert v.port_type == "mixed"


def test_classifier_unknown_tags_default_to_mixed(mock_db: Any) -> None:
    """Empty tags dict + no curated row → port_type='mixed'."""
    from app.classifier import PortClassifier

    mock_db._cursor.fetchone.return_value = None
    cl = PortClassifier(_settings())
    v = asyncio.run(cl.classify(0.0, 0.0, {}))
    assert v.source == "osm"
    assert v.port_type == "mixed"


def test_classifier_curated_wins_over_osm(mock_db: Any) -> None:
    """
    Curated must win even when OSM tags strongly suggest a different
    type. Eckernförde is curated 'military'; an OSM lookup at the same
    location with leisure=marina must still resolve to 'military'.
    """
    from app.classifier import PortClassifier

    # Curated returns military with 200 m distance — well inside the 5 km radius.
    mock_db._cursor.fetchone.return_value = (
        1006, "Eckernförde", "military", 1, 1, 200.0,
    )
    cl = PortClassifier(_settings())
    v = asyncio.run(cl.classify(54.4711, 9.8378, {"harbour": "yes", "leisure": "marina"}))
    assert v.source == "curated"
    assert v.port_type == "military"
    assert v.name == "Eckernförde"


def test_classifier_distance_edge_case_exactly_5km(mock_db: Any) -> None:
    """
    Curated row exactly at the radius boundary still counts as a match
    (the SDO_WITHIN_DISTANCE filter is inclusive at 'distance=5000m').
    A row JUST outside falls through to the OSM heuristic.
    """
    from app.classifier import PortClassifier
    cl = PortClassifier(_settings())

    # 1) Exactly at 5000 m → curated match.
    mock_db._cursor.fetchone.return_value = (
        2001, "Edge Port", "commercial", 0, 0, 5000.0,
    )
    v = asyncio.run(cl.classify(0.0, 0.0, {"harbour": "yes"}))
    assert v.source == "curated"
    assert v.port_type == "commercial"

    # 2) Just outside (mock returns None to simulate
    #    SDO_WITHIN_DISTANCE having filtered it out).
    mock_db._cursor.fetchone.return_value = None
    v = asyncio.run(cl.classify(0.0, 0.0, {"harbour": "yes", "industrial": "cargo"}))
    assert v.source == "osm"
    assert v.port_type == "commercial"

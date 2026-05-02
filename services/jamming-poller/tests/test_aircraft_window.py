"""
Tests for app/aircraft_window.py — in-process sliding-window accumulator.

Covers:
  - __init__: max_samples < 1 raises ValueError
  - add_snapshot: appends entry, auto-timestamp, bounded by maxlen
  - flat_aircraft: yields all entries across all snapshots, no dedup
  - coverage_window: None when empty, (oldest, newest) when populated
  - sample_count / max_samples / is_full properties
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

def test_init_valid_max_samples():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=5)
    assert w.max_samples == 5


def test_init_zero_raises():
    from app.aircraft_window import AircraftWindow
    with pytest.raises(ValueError):
        AircraftWindow(max_samples=0)


def test_init_negative_raises():
    from app.aircraft_window import AircraftWindow
    with pytest.raises(ValueError):
        AircraftWindow(max_samples=-1)


# ---------------------------------------------------------------------------
# Properties on empty window
# ---------------------------------------------------------------------------

def test_empty_window_sample_count_is_zero():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=10)
    assert w.sample_count == 0


def test_empty_window_is_not_full():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=3)
    assert w.is_full is False


def test_empty_window_coverage_window_is_none():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=3)
    assert w.coverage_window() is None


# ---------------------------------------------------------------------------
# add_snapshot
# ---------------------------------------------------------------------------

def test_add_snapshot_increments_sample_count():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=10)
    w.add_snapshot([{"icao": "abc"}])
    assert w.sample_count == 1


def test_add_snapshot_accepts_empty_list():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=5)
    w.add_snapshot([])
    assert w.sample_count == 1


def test_add_snapshot_uses_provided_timestamp():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=5)
    ts = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    w.add_snapshot([{"icao": "x"}], ts=ts)
    oldest, newest = w.coverage_window()
    assert oldest == ts
    assert newest == ts


def test_add_snapshot_auto_timestamp_is_utc():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=5)
    w.add_snapshot([])
    oldest, _ = w.coverage_window()
    assert oldest.tzinfo is not None


def test_add_snapshot_bounded_by_maxlen():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=3)
    ts1 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    ts3 = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    ts4 = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)
    w.add_snapshot([{"snap": 1}], ts=ts1)
    w.add_snapshot([{"snap": 2}], ts=ts2)
    w.add_snapshot([{"snap": 3}], ts=ts3)
    w.add_snapshot([{"snap": 4}], ts=ts4)  # evicts snap 1
    assert w.sample_count == 3
    oldest, newest = w.coverage_window()
    assert oldest == ts2  # ts1 was evicted
    assert newest == ts4


# ---------------------------------------------------------------------------
# is_full
# ---------------------------------------------------------------------------

def test_is_full_false_when_not_full():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=3)
    w.add_snapshot([])
    w.add_snapshot([])
    assert w.is_full is False


def test_is_full_true_when_at_capacity():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=2)
    w.add_snapshot([])
    w.add_snapshot([])
    assert w.is_full is True


def test_is_full_stays_true_after_overflow():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=2)
    for _ in range(5):
        w.add_snapshot([])
    assert w.is_full is True


# ---------------------------------------------------------------------------
# flat_aircraft
# ---------------------------------------------------------------------------

def test_flat_aircraft_yields_all_entries():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=10)
    w.add_snapshot([{"icao": "a"}, {"icao": "b"}])
    w.add_snapshot([{"icao": "c"}])
    all_ac = list(w.flat_aircraft())
    assert len(all_ac) == 3
    icaos = {a["icao"] for a in all_ac}
    assert icaos == {"a", "b", "c"}


def test_flat_aircraft_empty_window_yields_nothing():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=5)
    assert list(w.flat_aircraft()) == []


def test_flat_aircraft_no_dedup_same_aircraft_multiple_snapshots():
    """Same aircraft in two snapshots appears twice — intended semantics."""
    from app.aircraft_window import AircraftWindow
    ac = {"icao": "AAB123", "nac_p": 2}
    w = AircraftWindow(max_samples=5)
    w.add_snapshot([ac])
    w.add_snapshot([ac])
    all_ac = list(w.flat_aircraft())
    assert len(all_ac) == 2


def test_flat_aircraft_respects_eviction():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=2)
    w.add_snapshot([{"icao": "old"}])
    w.add_snapshot([{"icao": "mid"}])
    w.add_snapshot([{"icao": "new"}])  # evicts "old"
    all_icaos = {a["icao"] for a in w.flat_aircraft()}
    assert "old" not in all_icaos
    assert "mid" in all_icaos
    assert "new" in all_icaos


# ---------------------------------------------------------------------------
# coverage_window
# ---------------------------------------------------------------------------

def test_coverage_window_single_snapshot():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=5)
    ts = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    w.add_snapshot([], ts=ts)
    oldest, newest = w.coverage_window()
    assert oldest == ts
    assert newest == ts


def test_coverage_window_multiple_snapshots_ordered():
    from app.aircraft_window import AircraftWindow
    w = AircraftWindow(max_samples=5)
    ts_early = datetime(2026, 3, 1, 6, 0, 0, tzinfo=timezone.utc)
    ts_late = datetime(2026, 3, 1, 18, 0, 0, tzinfo=timezone.utc)
    w.add_snapshot([], ts=ts_early)
    w.add_snapshot([], ts=ts_late)
    oldest, newest = w.coverage_window()
    assert oldest == ts_early
    assert newest == ts_late

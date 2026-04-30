"""
In-process sliding-window accumulator for ADS-B aircraft snapshots.

Each upstream poll yields one snapshot (~25 aircraft for the Baltic 250 nm
radius). One snapshot alone is too sparse for meaningful per-cell NACp
statistics at H3 resolution 4 — the gpsjam.org reference numbers assume a
24 h aggregated window with millions of position reports.

This window keeps the last N snapshots in process memory and feeds the flat
union into the aggregator on every tick. Each NACp observation counts
independently, so a single aircraft loitering with low NACp for 6 ticks in
the same cell contributes 6 low-NACp votes — exactly what we want for
detecting persistent jamming.

Trade-off: state is in-process. A pod restart resets the window, so the
first 1-2 hours after a restart deliver thinner output. For real prod,
the next iteration would persist samples to a dedicated ATP table; that
is intentionally out of scope here (demo budget).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Deque, Iterable, List, Tuple

import structlog

logger = structlog.get_logger(__name__)


class AircraftWindow:
    """A bounded deque of (timestamp, aircraft_list) snapshots."""

    def __init__(self, max_samples: int) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        self._samples: Deque[Tuple[datetime, List[dict]]] = deque(maxlen=max_samples)

    @property
    def max_samples(self) -> int:
        return self._samples.maxlen or 0

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def is_full(self) -> bool:
        return len(self._samples) == self.max_samples

    def add_snapshot(
        self,
        aircraft: List[dict],
        ts: datetime | None = None,
    ) -> None:
        ts = ts or datetime.now(timezone.utc)
        self._samples.append((ts, list(aircraft)))
        logger.info(
            "window.snapshot_added",
            ts=ts.isoformat(),
            aircraft_count=len(aircraft),
            samples=len(self._samples),
            max_samples=self.max_samples,
        )

    def flat_aircraft(self) -> Iterable[dict]:
        """Yield every aircraft observation across all samples in the window.

        No deduplication: a single aircraft's NACp at multiple ticks each
        contributes a separate vote to the per-cell ratio. That's the
        intended semantics for jamming detection — persistent low NACp is
        a stronger signal than a single transient observation.
        """
        for _ts, lst in self._samples:
            yield from lst

    def coverage_window(self) -> Tuple[datetime, datetime] | None:
        """Return (oldest_ts, newest_ts) of currently held samples, or None."""
        if not self._samples:
            return None
        return (self._samples[0][0], self._samples[-1][0])

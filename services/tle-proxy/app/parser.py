"""
TLE (Two-Line-Element) parser.

CelesTrak's `gp.php?GROUP=...&FORMAT=tle` returns a stream of 3-line
records:

    NAME (24-char padded, often with trailing spaces)
    1 NORADID  ...  (line 1, starts with "1 ")
    2 NORADID  ...  (line 2, starts with "2 ")

We keep parsing tolerant: lone NAME lines without a complete pair are
skipped silently. The parser never raises on malformed input — it returns
the well-formed subset and counts skips. Empty input or input with fewer
than 3 lines yields an empty list (caller should treat that as a failed
fetch and NOT overwrite the previous cache row).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TleRecord:
    name: str        # human-readable satellite name, e.g. "ISS (ZARYA)"
    norad_id: str    # 5-char NORAD catalog number, e.g. "25544"
    line1: str       # raw TLE line 1 (verbatim, useful for client-side propagation)
    line2: str       # raw TLE line 2

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "norad_id": self.norad_id,
            "line1": self.line1,
            "line2": self.line2,
        }


def _normalise_lines(text: str) -> list[str]:
    # Split on any newline style, drop empty/whitespace-only lines.
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def _norad_from_line1(line1: str) -> str:
    # TLE line 1 columns 3-7 are the catalog number, optionally
    # followed by classification char. Tolerate variable padding.
    if len(line1) < 7:
        return ""
    return line1[2:7].strip()


def parse_tle(text: str) -> list[TleRecord]:
    """
    Parse a CelesTrak gp.php TLE stream into TleRecord objects.

    Robustness:
      * Lone names without `1 ...` / `2 ...` pairs → skipped (logged once
        per parse with skipped count).
      * `1 ...` / `2 ...` pairs without preceding name → skipped (no
        identifier, useless for UI).
      * Catalog numbers diverging between line1 and line2 → skipped.
    """
    lines = _normalise_lines(text)
    records: list[TleRecord] = []
    skipped = 0
    i = 0
    while i < len(lines):
        # Look for a 3-line record: NAME, "1 ...", "2 ...".
        if i + 2 >= len(lines):
            skipped += len(lines) - i
            break
        name = lines[i]
        line1 = lines[i + 1]
        line2 = lines[i + 2]
        if line1.startswith("1 ") and line2.startswith("2 "):
            norad1 = _norad_from_line1(line1)
            norad2 = _norad_from_line1(line2)
            if norad1 and norad1 == norad2:
                records.append(
                    TleRecord(
                        name=name.strip(),
                        norad_id=norad1,
                        line1=line1,
                        line2=line2,
                    )
                )
                i += 3
                continue
        # Misaligned — skip the current line and re-sync.
        skipped += 1
        i += 1
    if skipped:
        logger.info("tle.parser.skipped_lines", count=skipped, total=len(lines))
    return records


def records_to_payload(group: str, records: Iterable[TleRecord]) -> dict:
    items = [r.to_dict() for r in records]
    return {
        "type": "TleCollection",
        "group": group,
        "tle": items,
        "count": len(items),
        "source": "CelesTrak NORAD GP catalog",
    }

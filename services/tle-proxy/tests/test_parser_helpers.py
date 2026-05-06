"""
Direct unit tests for private parser helpers in tle-proxy app/parser.py.

Gaps covered (not tested by test_parser.py, which only exercises parse_tle()):
  - _normalise_lines()   — CRLF/LF/blank stripping, whitespace-only lines
  - _norad_from_line1()  — column 2-6 extraction, short-line guard, padding

These are pure functions with no I/O.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def _helpers():
    try:
        from app.parser import _normalise_lines, _norad_from_line1  # type: ignore
        return _normalise_lines, _norad_from_line1
    except ImportError:
        pytest.skip("tle-proxy app.parser not importable")


# ---------------------------------------------------------------------------
# _normalise_lines
# ---------------------------------------------------------------------------

class TestNormaliseLines:
    @pytest.fixture(autouse=True)
    def _load(self, _helpers):
        self.fn, _ = _helpers

    def test_empty_string_returns_empty_list(self):
        assert self.fn("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert self.fn("   \n  \n\t\n") == []

    def test_lf_line_endings(self):
        result = self.fn("line1\nline2\nline3")
        assert result == ["line1", "line2", "line3"]

    def test_crlf_line_endings(self):
        result = self.fn("line1\r\nline2\r\nline3")
        assert result == ["line1", "line2", "line3"]

    def test_cr_only_line_endings(self):
        result = self.fn("line1\rline2\rline3")
        assert result == ["line1", "line2", "line3"]

    def test_blank_lines_dropped(self):
        result = self.fn("ISS (ZARYA)\n\n1 25544U ...\n\n2 25544 ...")
        assert result == ["ISS (ZARYA)", "1 25544U ...", "2 25544 ..."]

    def test_trailing_spaces_stripped(self):
        result = self.fn("ISS (ZARYA)   \n1 25544U ...   ")
        assert result[0] == "ISS (ZARYA)"
        assert result[1] == "1 25544U ..."

    def test_leading_whitespace_preserved(self):
        # rstrip only — leading spaces on TLE lines are meaningful for column parsing.
        result = self.fn("  1 25544U ...\n")
        assert result[0].startswith("  ")

    def test_single_non_empty_line(self):
        result = self.fn("ISS (ZARYA)")
        assert result == ["ISS (ZARYA)"]

    def test_mixed_empty_and_content_lines(self):
        text = "\n\nNAME\n\n1 LINE1\n2 LINE2\n\n"
        result = self.fn(text)
        assert result == ["NAME", "1 LINE1", "2 LINE2"]

    def test_preserves_order(self):
        lines = ["A", "B", "C", "D", "E"]
        result = self.fn("\n".join(lines))
        assert result == lines


# ---------------------------------------------------------------------------
# _norad_from_line1
# ---------------------------------------------------------------------------

class TestNoradFromLine1:
    @pytest.fixture(autouse=True)
    def _load(self, _helpers):
        _, self.fn = _helpers

    def test_extracts_5_digit_norad_id(self):
        # Standard line1 format: "1 25544U 98067A ..."
        line1 = "1 25544U 98067A   26119.49027628  .00007115  00000+0  13705-3 0  9999"
        assert self.fn(line1) == "25544"

    def test_extracts_leading_zero_norad(self):
        line1 = "1 00005U 58002B   26119.00000000  .00000000  00000+0  00000+0 0  9990"
        assert self.fn(line1) == "00005"

    def test_strips_classification_character(self):
        # Column 7 (index 7) is the classification char — must not appear in ID.
        line1 = "1 25544U 98067A   26119.00000000  .00000000  00000+0  00000+0 0  9990"
        result = self.fn(line1)
        assert len(result) <= 5
        assert result == "25544"

    def test_shorter_than_7_chars_returns_empty_string(self):
        assert self.fn("1 254") == ""
        assert self.fn("1 25") == ""
        assert self.fn("") == ""

    def test_exactly_7_chars_returns_stripped(self):
        # "1 25544" → line1[2:7] = "25544" → strip → "25544"
        assert self.fn("1 25544") == "25544"

    def test_norad_with_spaces_stripped(self):
        # Padded shorter IDs: "1  5U..." → columns 2-6 = " 5U.."
        # strip() removes leading/trailing whitespace from the 5-char field.
        line1 = "1    5U 58002B   26119.00000000  .00000000  00000+0  00000+0 0  9990"
        result = self.fn(line1)
        assert result == "5"

    def test_different_norad_ids_not_equal(self):
        line_iss = "1 25544U 98067A   26119.49027628  .00007115  00000+0  13705-3 0  9999"
        line_tgss = "1 48274U 21035A   26119.36679823  .00012763  00000+0  16834-3 0  9991"
        assert self.fn(line_iss) != self.fn(line_tgss)

    @pytest.mark.parametrize("norad", ["25544", "48274", "99990", "00001"])
    def test_round_trip_known_norad_ids(self, norad):
        # Build a synthetic line1 with this NORAD ID and verify extraction.
        line1 = f"1 {norad}U 98067A   26119.00000000  .00000000  00000+0  00000+0 0  9990"
        assert self.fn(line1) == norad

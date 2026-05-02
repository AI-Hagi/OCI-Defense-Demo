"""Parser tests — TLE multi-block, empty input, malformed lines."""
from __future__ import annotations


def test_parse_tle_multi_block() -> None:
    from app.parser import parse_tle, records_to_payload

    sample = """\
ISS (ZARYA)
1 25544U 98067A   26119.49027628  .00007115  00000+0  13705-3 0  9999
2 25544  51.6319 181.1364 0007113   4.2135 355.8912 15.49020533564200
TIANGONG SPACE STATION
1 48274U 21035A   26119.36679823  .00012763  00000+0  16834-3 0  9991
2 48274  41.4587 110.4567 0006100  78.0000 282.0000 15.59000000200000
"""
    records = parse_tle(sample)
    assert len(records) == 2
    assert records[0].name == "ISS (ZARYA)"
    assert records[0].norad_id == "25544"
    assert records[0].line1.startswith("1 25544U")
    assert records[1].name == "TIANGONG SPACE STATION"
    assert records[1].norad_id == "48274"

    # records_to_payload must wrap them with the right metadata.
    payload = records_to_payload("stations", records)
    assert payload["type"] == "TleCollection"
    assert payload["group"] == "stations"
    assert payload["count"] == 2
    assert len(payload["tle"]) == 2
    assert payload["tle"][0]["norad_id"] == "25544"


def test_parse_tle_empty_input() -> None:
    from app.parser import parse_tle

    assert parse_tle("") == []
    assert parse_tle("\n\n   \n") == []
    # 2 lines is too short for a TLE block — skipped silently.
    assert parse_tle("1 25544U ...\n2 25544 ...") == []


def test_parse_tle_malformed_lines_are_skipped() -> None:
    from app.parser import parse_tle

    # A name with a stray 1-line that doesn't match — parser must drop the
    # bad block and recover at the next valid 3-line group.
    sample = """\
GARBAGE LINE NAME
NOT A TLE LINE 1
NOT A TLE LINE 2
TIANGONG SPACE STATION
1 48274U 21035A   26119.36679823  .00012763  00000+0  16834-3 0  9991
2 48274  41.4587 110.4567 0006100  78.0000 282.0000 15.59000000200000
"""
    records = parse_tle(sample)
    # Only the second block parses cleanly.
    assert len(records) == 1
    assert records[0].name == "TIANGONG SPACE STATION"
    assert records[0].norad_id == "48274"

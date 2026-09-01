from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.probe_nowscore_jc import inspect_jc_surface


PAGE = """
<script>
var filename2 = "ft1.js";
document.getElementById("jingcai").innerHTML =
  '<a href="javascript:SetLevel(3)">JC</a>';
function SetLevel(l) {
    var index = 31;
    if (l == 3) {
        index = 32;
    }
    for (var j = 0; j < matchcount; j++) {
        ShowOrHideMatch(A[j][0], A[j][index] == 1, "league");
    }
}
</script>
"""


def _row(match_id: int, home: str, away: str, jc: int, kickoff: str = "00:30") -> str:
    values = [
        match_id, 1, 101, 202, home, 0, home, away, 0, away,
        kickoff, "09-01", 0, 0, 0, None, None, None, 0, 0, 0, 0,
        "", "", "", 0, "", "", "", 0, 0, 0, jc,
    ]
    encoded = ",".join("" if value is None else repr(value) for value in values)
    return f"A[0]=[{encoded}];"


def test_inspect_jc_surface_uses_explicit_public_filter_flag():
    result = inspect_jc_surface(
        PAGE,
        _row(1001, "Home FC", "Away FC", 1),
        expected_date="2026-09-01",
        source_url="https://live.nowscore.com/schedule.aspx?f=ft1",
        backing_data_url="https://live.nowscore.com/data/ft1.js",
        fetched_at="2026-09-01T12:00:00+08:00",
    )

    assert result["status"] == "PASS"
    assert result["contract"]["row_index"] == 32
    assert result["jc_flagged_row_count"] == 1
    assert result["accepted_fixture_count"] == 1
    fixture = result["fixtures"][0]
    assert fixture["nowscore_id"] == 1001
    assert fixture["jc_membership"] == "VERIFIED"
    assert fixture["jc_membership_source"] == "nowscore_public_jc"
    assert fixture["date_provenance"]["expected_business_date"] == "2026-09-01"


def test_inspect_jc_surface_does_not_guess_from_other_schedule_flags():
    result = inspect_jc_surface(
        PAGE,
        _row(1001, "Home FC", "Away FC", 0),
        expected_date="2026-09-01",
        source_url="https://live.nowscore.com/schedule.aspx?f=ft1",
        backing_data_url="https://live.nowscore.com/data/ft1.js",
        fetched_at="2026-09-01T12:00:00+08:00",
    )

    assert result["status"] == "PASS"
    assert result["jc_flagged_row_count"] == 0
    assert result["accepted_fixture_count"] == 0
    assert result["fixtures"] == []


def test_inspect_jc_surface_fails_closed_on_duplicate_ids():
    first = _row(1001, "Home FC", "Away FC", 1)
    second = _row(1001, "Other Home", "Away FC", 1).replace("A[0]", "A[1]")

    result = inspect_jc_surface(
        PAGE,
        first + "\n" + second,
        expected_date="2026-09-01",
        source_url="https://live.nowscore.com/schedule.aspx?f=ft1",
        backing_data_url="https://live.nowscore.com/data/ft1.js",
        fetched_at="2026-09-01T12:00:00+08:00",
    )

    assert result["status"] == "FAIL"
    assert result["duplicate_nowscore_id_count"] == 1
    assert result["ambiguous_nowscore_id_count"] == 1
    assert result["accepted_fixture_count"] == 0
    assert result["fixtures"] == []

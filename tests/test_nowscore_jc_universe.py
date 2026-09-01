from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import scripts.nowscore_markets as nowscore_markets
from scripts.nowscore_markets import (
    fetch_nowscore_jc_schedule,
    parse_nowscore_jc_surface,
)


def _page(surface: str = "ft1") -> str:
    return f"""
    <script>
    var filename2 = \"{surface}.js\";
    document.getElementById(\"jingcai\").innerHTML =
      '<a href=\"javascript:SetLevel(3)\">JC</a>';
    function SetLevel(l) {{
        var index = 31;
        if (l == 3) {{ index = 32; }}
        for (var j = 0; j < matchcount; j++) {{
            ShowOrHideMatch(A[j][0], A[j][index] == 1, \"league\");
        }}
    }}
    </script>
    """


def _row(match_id: int, jc: int, source_date: str = "09-01") -> str:
    values = [
        match_id, 1, 101, 202, "主队", 0, "Home FC", "客队", 0, "Away FC",
        "00:30", source_date, 0, 0, 0, None, None, None, 0, 0, 0, 0,
        "", "", "", 0, "", "", "", 0, 0, 0, jc,
    ]
    return "A[0]=[" + ",".join("" if value is None else repr(value) for value in values) + "];"


def test_parse_nowscore_jc_surface_persists_explicit_membership_and_date_provenance():
    result = parse_nowscore_jc_surface(
        _page(),
        _row(1001, 1),
        expected_date="2026-09-01",
        source_url="https://live.nowscore.com/schedule.aspx?f=ft1",
        backing_data_url="https://live.nowscore.com/data/ft1.js",
        fetched_at="2026-09-01T12:00:00+08:00",
    )

    assert result["status"] == "PASS"
    assert result["accepted_fixture_count"] == 1
    fixture = result["fixtures"][0]
    assert fixture["nowscore_id"] == 1001
    assert fixture["jc_membership"] == "VERIFIED"
    assert fixture["jc_membership_source"] == "nowscore_public_jc"
    assert fixture["date_provenance"]["source_date_value"] == "09-01"
    assert fixture["source_surface"].endswith("f=ft1")
    assert fixture["source_url"].endswith("/data/ft1.js")


def test_parse_nowscore_jc_surface_uses_only_row_32_not_other_flags():
    result = parse_nowscore_jc_surface(
        _page(),
        _row(1001, 0),
        expected_date="2026-09-01",
        source_url="https://live.nowscore.com/schedule.aspx?f=ft1",
        backing_data_url="https://live.nowscore.com/data/ft1.js",
    )

    assert result["status"] == "PASS"
    assert result["jc_flagged_row_count"] == 0
    assert result["fixtures"] == []


def test_fetch_nowscore_jc_schedule_uses_page_then_backing_data_without_other_providers():
    calls: list[str] = []

    def fetch(url: str, timeout: int = 30) -> bytes:
        calls.append(url)
        if "schedule.aspx?f=ft1" in url:
            return _page().encode("utf-8")
        if "/data/ft1.js?" in url:
            return _row(1001, 1).encode("utf-8")
        raise AssertionError(url)

    with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
        result = fetch_nowscore_jc_schedule("2026-09-01", now=date(2026, 9, 1))

    assert result["success"] is True
    assert result["source"] == "nowscore_public_jc"
    assert result["matches"][0]["nowscore_id"] == 1001
    assert calls[0].endswith("schedule.aspx?f=ft1")
    assert "/data/ft1.js?" in calls[1]


def test_fetch_nowscore_jc_schedule_selects_sc1_for_next_date():
    calls: list[str] = []

    def fetch(url: str, timeout: int = 30) -> bytes:
        calls.append(url)
        if "schedule.aspx?f=sc1" in url:
            return _page("sc1").encode("utf-8")
        if "/data/sc1.js?" in url:
            return _row(1002, 1, "09-02").encode("utf-8")
        raise AssertionError(url)

    with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
        result = fetch_nowscore_jc_schedule("2026-09-02", now=date(2026, 9, 1))

    assert result["success"] is True
    assert result["surface"] == "sc1"
    assert result["matches"][0]["business_date"] == "2026-09-02"
    assert any("schedule.aspx?f=sc1" in url for url in calls)
    assert any("/data/sc1.js?" in url for url in calls)

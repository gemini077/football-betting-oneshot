from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import scripts.nowscore_markets as nowscore_markets
from scripts.nowscore_markets import (
    fetch_nowscore_jc_schedule,
    parse_nowscore_jc_business_page,
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


def _business_page(
    business_date: str = "2026-09-01",
    group: str = "周二",
    match_id: int = 1002,
    kickoff: str = "2026-09-02 00:30",
    sales_row_id: str = "5510001",
    extra_group: bool = False,
) -> str:
    year, month, day = business_date.split("-")
    next_group = """
      <tr class='niDate'><td colspan='15'>2026年09月02日 周三 (11：00--次日11：00)
        <a id='ah_周三' onclick="isShowSclass('周三','none');">周三</a>
      </td></tr>
      <tr id='row_5511001' name='周三' cansale='true' gamename='测试联赛'>
        <td>001</td><td>测试</td><td title='开赛时间：2026-09-03 00:30'>00:30</td>
        <td></td><td><a id='HomeTeam_1003'>主队3</a></td><td></td><td></td>
        <td><a id='GuestTeam_1003'>客队3</a></td>
      </tr>
    """ if extra_group else ""
    return f"""
    <script>var SelDate='{year}-{int(month)}-{int(day)}';</script>
    <select onchange="window.location.href='?date='+this.options[this.selectedIndex].value">
      <option value='{year}-{int(month)}-{int(day)}' selected>{business_date}</option>
    </select>
    <table>
      <tr class='niDate'><td colspan='15'>{business_date} {group} (11：00--次日11：00)
        <a id='ah_{group}' onclick="isShowSclass('{group}','none');">{group}</a>
      </td></tr>
      <tr id='row_{sales_row_id}' name='{group}' cansale='true' gamename='测试联赛'>
        <td>001</td><td>测试</td><td title='开赛时间：{kickoff}'>00:30</td>
        <td></td><td><a id='HomeTeam_{match_id}'>主队</a></td><td></td><td></td>
        <td><a id='GuestTeam_{match_id}'>客队</a></td>
      </tr>
      {next_group}
    </table>
    """


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


def test_parse_nowscore_jc_business_page_anchors_business_date_not_kickoff_date():
    result = parse_nowscore_jc_business_page(
        _business_page(
            business_date="2026-08-31",
            group="周一",
            match_id=1001,
            kickoff="2026-09-01 00:30",
            sales_row_id="5509001",
            extra_group=True,
        ),
        business_date="2026-08-31",
    )

    assert result["status"] == "PASS"
    assert result["contract"]["selected_date"] == "2026-08-31"
    assert result["contract"]["requested_group"] == "周一"
    assert result["contract"]["sales_window"] == "11:00--次日11:00"
    assert result["row_count"] == 1
    assert result["next_calendar_day_kickoff_count"] == 1
    assert result["fixtures"][0]["match_number"] == "周一001"
    assert result["fixtures"][0]["sales_row_id"] == "5509001"


def test_fetch_nowscore_jc_schedule_uses_direct_sales_page_without_live_dependency():
    calls: list[str] = []

    def fetch(url: str, timeout: int = 30) -> bytes:
        calls.append(url)
        if "cp.nowscore.com/buy/jingcai.aspx" in url:
            return _business_page().encode("utf-8")
        raise OSError("optional live surface unavailable")

    with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
        result = fetch_nowscore_jc_schedule("2026-09-01", now=date(2026, 9, 1))

    assert result["success"] is True
    assert result["source"] == "nowscore_public_jc"
    assert result["primary_source"] == "nowscore_public_jc_sales"
    assert result["matches"][0]["nowscore_id"] == 1002
    assert result["matches"][0]["business_date"] == "2026-09-01"
    assert result["matches"][0]["match_number"] == "周二001"
    assert result["matches"][0]["jc_membership_source"] == "nowscore_public_jc_sales"
    assert result["a32_corroborated_count"] == 0
    assert calls[0].startswith("https://cp.nowscore.com/buy/jingcai.aspx")


def test_fetch_nowscore_jc_schedule_persists_optional_a32_corroboration():
    calls: list[str] = []

    def fetch(url: str, timeout: int = 30) -> bytes:
        calls.append(url)
        if "cp.nowscore.com/buy/jingcai.aspx" in url:
            return _business_page().encode("utf-8")
        if "schedule.aspx?f=sc1" in url:
            return _page("sc1").encode("utf-8")
        if "/data/sc1.js?" in url:
            return _row(1002, 1, "09-02").encode("utf-8")
        raise AssertionError(url)

    with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
        result = fetch_nowscore_jc_schedule("2026-09-01", now=date(2026, 9, 1))

    assert result["success"] is True
    assert result["matches"][0]["business_date"] == "2026-09-01"
    assert result["matches"][0]["a32_corroboration"]["predicate"] == "A[j][32] == 1"
    assert result["a32_corroborated_count"] == 1
    assert any("schedule.aspx?f=sc1" in url for url in calls)
    assert any("/data/sc1.js?" in url for url in calls)


def test_fetch_nowscore_jc_schedule_accepts_direct_row_when_a32_is_not_flagged():
    def fetch(url: str, timeout: int = 30) -> bytes:
        if "cp.nowscore.com/buy/jingcai.aspx" in url:
            return _business_page().encode("utf-8")
        if "schedule.aspx?f=sc1" in url:
            return _page("sc1").encode("utf-8")
        if "/data/sc1.js?" in url:
            return _row(1002, 0, "09-02").encode("utf-8")
        raise AssertionError(url)

    with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
        result = fetch_nowscore_jc_schedule("2026-09-01", now=date(2026, 9, 1))

    assert result["success"] is True
    assert len(result["matches"]) == 1
    assert "a32_corroboration" not in result["matches"][0]

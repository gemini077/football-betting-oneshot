from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import probe_nowscore_business_date as probe


def _page(selected: str = "2026-08-31", next_group: bool = False) -> str:
    second = """
    <tr class='niDate'><td colspan=15>2026年09月01日 星期二 (11：00--次日11：00)
      <a id='ah_周二' onclick="isShowSclass('周二','none');">隐藏</a>
    </td></tr>
    <tr id='row_5510001' name='周二' cansale='true' gamename='测试'>
      <td>001</td><td>测试</td><td title='开赛时间：2026-09-02 00:30'>00:30</td>
      <td></td><td><a id='HomeTeam_2002'>主队2</a></td><td></td><td></td>
      <td><a id='GuestTeam_2002'>客队2</a></td>
    </tr>
    """ if next_group else ""
    return f"""
    <script>
    var SelDate='{selected}';
    </script>
    <select onchange="window.location.href='?date='+this.options[this.selectedIndex].value">
      <option value='2026-8-31'>2026-8-31</option>
    </select>
    <table>
      <tr class='niDate'><td colspan=15>2026年08月31日 星期一 (11：00--次日11：00)
        <a id='ah_周一' onclick="isShowSclass('周一','none');">隐藏</a>
      </td></tr>
      <tr id='row_5509001' name='周一' cansale='false' gamename='测试'>
        <td>001</td><td>测试</td><td title='开赛时间：2026-09-01 00:30'>00:30</td>
        <td></td><td><a id='HomeTeam_1001'>主队</a></td><td></td><td></td>
        <td><a id='GuestTeam_1001'>客队</a></td>
      </tr>
      {second}
    </table>
    """


def _schedule_row(match_id: int, source_date: str, jc: int) -> str:
    values = [
        match_id, 1, 101, 202, "主队", 0, "Home", "客队", 0, "Away",
        "00:30", source_date, 0, 0, 0, None, None, None, 0, 0, 0, 0,
        "", "", "", 0, "", "", "", 0, 0, 0, jc,
    ]
    encoded = ",".join("" if value is None else repr(value) for value in values)
    return f"A[0]=[{encoded}];"


def test_parse_jc_page_uses_public_sales_window_and_next_day_kickoff():
    result = probe.parse_jc_page(_page(), business_date="2026-08-31")

    assert result["status"] == "PASS"
    assert result["contract"]["selected_date"] == "2026-08-31"
    assert result["contract"]["requested_header"]["window"] == "11:00--次日11:00"
    assert result["row_count"] == 1
    assert result["next_calendar_day_kickoff_count"] == 1
    assert result["fixtures"][0]["match_number"] == "周一001"


def test_parse_jc_page_filters_to_requested_business_date_group():
    result = probe.parse_jc_page(
        _page(selected="2026-09-01", next_group=True),
        business_date="2026-09-01",
    )

    assert result["status"] == "PASS"
    assert result["row_count"] == 1
    assert result["fixtures"][0]["match_number"] == "周二001"
    assert result["fixtures"][0]["kickoff"] == "2026-09-02 00:30"


def test_membership_replay_accepts_direct_sales_row_without_schedule_row():
    page = probe.parse_jc_page(_page(), business_date="2026-08-31")
    page["today"] = "2026-09-01"
    result = probe._join_membership(page, {})

    assert result["accepted_fixture_count"] == 1
    fixture = result["accepted_fixtures"][0]
    assert fixture["jc_membership_source"] == "nowscore_public_jc_sales"
    assert fixture["jc_membership_evidence"]["source"] == "nowscore_public_jc_sales"
    assert result["missing_schedule_surface_count"] == 1


def test_membership_replay_adds_a32_only_as_optional_corroboration():
    page = probe.parse_jc_page(_page(), business_date="2026-08-31")
    page["today"] = "2026-09-01"
    surfaces = {
        "ft1": {
            "status": "PASS",
            "page": {"url": "https://live.nowscore.com/schedule.aspx?f=ft1"},
            "data": {"url": "https://live.nowscore.com/data/ft1.js"},
            "rows": probe.nowscore._raw_schedule_rows(_schedule_row(1001, "09-01", 1)),
        }
    }

    result = probe._join_membership(page, surfaces)
    fixture = result["accepted_fixtures"][0]
    assert result["accepted_fixture_count"] == 1
    assert result["a32_corroborated_count"] == 1
    assert fixture["a32_corroboration"]["predicate"] == "A[j][32] == 1"
    assert fixture["jc_membership_source"] == "nowscore_public_jc_sales"

    surfaces["ft1"]["rows"] = probe.nowscore._raw_schedule_rows(_schedule_row(1001, "09-01", 0))
    not_flagged = probe._join_membership(page, surfaces)
    assert not_flagged["accepted_fixture_count"] == 1
    assert not_flagged["not_flagged_count"] == 1


def test_direct_page_rows_are_available_without_explicit_schedule_rows():
    page = probe.parse_jc_page(_page(), business_date="2026-08-31")
    page["membership_replay"] = {"accepted_fixture_count": 0}

    assert probe._direct_page_rows_available([page]) is True


def test_gate_stays_pass_when_optional_live_surface_fails(monkeypatch):
    def cp_surface(business_date, fetched_at):
        result = probe.parse_jc_page(_page(), business_date=business_date)
        result.update({
            "business_date": business_date.isoformat(),
            "source_surface": probe.CP_BASE_URL.format(
                business_date=business_date.isoformat()
            ),
            "fetched_at": fetched_at,
        })
        return result

    monkeypatch.setattr(probe, "_cp_surface_result", cp_surface)
    monkeypatch.setattr(
        probe,
        "_schedule_surface",
        lambda surface, *, today, fetched_at: {
            "status": "FETCH_ERROR",
            "surface": surface,
            "rows": [],
        },
    )

    result = probe.run_probe(("2026-08-31",), today="2026-09-01")

    assert result["decision_gate"] == "PASS"
    assert result["pages"][0]["membership_replay"]["accepted_fixture_count"] == 1
    assert result["optional_schedule_pass"] is False

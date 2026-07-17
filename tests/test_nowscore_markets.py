import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.nowscore_markets import (
    handicap_number,
    parse_coach_page,
    parse_company_trend,
    parse_panlu_page,
    parse_referee_page,
    parse_analysis_data,
    parse_schedule_js,
    parse_three_in_one,
    resolve_match,
    _verified,
)
from market_intelligence import nowscore_trend_panel


SCHEDULE = """A[0]=[2912840,0,0,0,'瓦勒伦加',0,'Valerenga','奥勒松',0,'Aalesund FK','01:00','2026,6,17,01,00,00',0,0,0,0,0,0,0,0,0,0,0,'半/一',0,0,0,2.75];"""


MARKET_HTML = """
<input id="hide_scheduleId" value="2912840">
<input id="hide_matchTime" value="2026-07-17 01:00">
<div id="home"><a class="name">瓦勒伦加</a></div>
<div id="guest"><a class="name">奥勒松</a></div>
<table><tr class="datatr">
<td><a href="/odds/companyhistory.aspx?companyid=8">bet365</a></td>
<td>0.85</td><td>半/一</td><td>0.95</td><td>0.90</td><td>一</td><td>0.90</td>
<td>1.55</td><td>4.20</td><td>5.20</td><td>1.50</td><td>4.33</td><td>5.50</td>
<td>0.92</td><td>2.75</td><td>0.88</td><td>0.86</td><td>3</td><td>0.94</td>
</tr></table>
"""

ANALYSIS_JS = """
var h_data = [['26-07-12',22,'','#666',9,'opp',101,'home',2,1,'1-0'],['26-07-05',22,'','#666',101,'home',8,'opp',3,0,'1-0'],['26-06-28',22,'','#666',7,'opp',101,'home',1,1,'0-0']];
var a_data = [['26-07-11',22,'','#666',202,'away',6,'opp',2,2,'1-1'],['26-07-04',22,'','#666',5,'opp',202,'away',1,0,'0-0'],['26-06-27',22,'','#666',202,'away',4,'opp',0,1,'0-1']];
var next_value = [];
"""


class NowscoreMarketTests(unittest.TestCase):
    def test_sporttery_alias_resolves_mjallby_fixture_2912209(self):
        rows = [{
            "nowscore_id": 2912209,
            "home_team": "\u7c73\u4e9a\u5c14\u6bd4",
            "home_team_en": "Mjallby AIF",
            "away_team": "\u74e6\u65af\u7279\u62c9\u65af",
            "away_team_en": "Vasteras SK FK",
            "kickoff_local": "2026-07-18T01:00+08:00",
        }]
        match = resolve_match(
            "\u7c73\u4e9a\u5c14\u6bd4",
            "\u97e6\u65af\u7279\u7f57\u65af",
            "2026-07-18 01:00",
            rows,
        )
        self.assertEqual("EXACT_MATCH", match["status"])
        self.assertEqual(2912209, match["nowscore_id"])

    def test_schedule_and_exact_resolution(self):
        rows = parse_schedule_js(SCHEDULE)
        self.assertEqual(2912840, rows[0]["nowscore_id"])
        match = resolve_match("瓦勒伦加", "奥勒松", "2026-07-17 01:00", rows)
        self.assertEqual("EXACT_MATCH", match["status"])
        self.assertEqual(0, match["kickoff_difference_minutes"])

    def test_three_market_families_are_parsed(self):
        result = parse_three_in_one(MARKET_HTML)
        self.assertEqual(3, result["ouzhi"]["bookmakers"][0]["cid"])
        self.assertEqual(1.50, result["ouzhi"]["bookmakers"][0]["spf_current"]["home"])
        self.assertEqual(-1.0, result["yazhi"]["companies"][0]["current_handicap"])
        self.assertEqual(3.0, result["daxiao"]["companies"][0]["current_line"])

    def test_handicap_uses_home_team_perspective(self):
        self.assertEqual(-0.75, handicap_number("半/一"))
        self.assertEqual(0.75, handicap_number("受半/一"))

    def test_identity_mismatch_is_rejected(self):
        parsed = parse_three_in_one(MARKET_HTML)
        accepted, reasons = _verified(
            {"home": "奥勒松", "away": "瓦勒伦加", "kickoff": "2026-07-17 01:00"},
            parsed["identity"],
        )
        self.assertFalse(accepted)
        self.assertIn("HOME_TEAM_MISMATCH", reasons)
        self.assertIn("AWAY_TEAM_MISMATCH", reasons)

    def test_analysis_recent_form_is_oriented_to_each_target_team(self):
        result = parse_analysis_data(ANALYSIS_JS)
        form = result["recent_form"]
        self.assertEqual(101, result["team_ids"]["home"])
        self.assertEqual(202, result["team_ids"]["away"])
        self.assertEqual(5, form["home_overall"]["goals_for"])
        self.assertEqual(3, form["home_overall"]["goals_against"])
        self.assertEqual(1, form["home_home"]["matches"])
        self.assertEqual(1, form["away_away"]["matches"])

    def test_numeric_split_total_line_is_normalized(self):
        self.assertEqual(2.75, handicap_number("2.5/3"))

    def test_context_pages_are_structured(self):
        coach = parse_coach_page("""
        <table><tr><td>姓名：</td><td>主帅甲</td></tr><tr><td>生日：</td><td>1980-01-01</td></tr>
        <tr><td>姓名：</td><td>客帅乙</td></tr></table>
        <script>var hc_data=[['', '', 26, '', '联赛', 10, 6, 2, 2, 18, 9, 2.0, 0, 0, '1']]; var gc_data=[];</script>
        """)
        self.assertEqual("主帅甲", coach["home"]["name"])
        self.assertEqual(10, coach["home"]["coach_records"][0]["matches"])
        referee = parse_referee_page("""
        <table><tr><td>姓名：</td><td>裁判甲</td></tr><tr><td>国籍：</td><td>瑞典</td></tr>
        <tr><td>所有赛事</td><td>20</td><td>主场球队</td><td>8胜 5平 7负</td><td>10</td><td>2</td><td>0.1</td><td>40%</td></tr>
        <tr><td>客场球队</td><td>7胜 5平 8负</td><td>11</td><td>2.1</td><td>0.1</td><td>35%</td><td></td><td></td></tr></table>
        """)
        self.assertEqual("裁判甲", referee["name"])
        self.assertEqual(20, referee["summaries"][0]["matches"])
        panlu = parse_panlu_page("var a[0]=[1,'联赛','', '2026-07-01','主','客',10,20,2,1,1,0,'半球',1,0,'2.5'];")
        self.assertEqual(1, panlu["count"])

    def test_company_history_is_split_into_three_markets(self):
        trend = parse_company_trend("""
        <table><tr><th>时</th><th>比分</th><th>主</th><th>盘</th><th>客</th><th>变化</th><th>状</th></tr>
        <tr><td></td><td>-</td><td>0.85</td><td>半球</td><td>1.02</td><td>07-17 18:20</td><td>即</td></tr>
        <tr><th>时</th><th>比分</th><th>大</th><th>盘</th><th>小</th><th>变化</th><th>状</th></tr>
        <tr><td></td><td>-</td><td>0.82</td><td>2.5/3</td><td>1.05</td><td>07-17 17:34</td><td>即</td></tr>
        <tr><th>时</th><th>比分</th><th>主</th><th>和局</th><th>客</th><th>变化</th><th>状</th></tr>
        <tr><td></td><td>-</td><td>1.85</td><td>4.00</td><td>3.95</td><td>07-17 16:24</td><td>即</td></tr></table>
        """, 3, "2026-07-18 01:00", "皇冠")
        self.assertEqual(3, trend["snapshot_count"])
        self.assertEqual(2.75, trend["markets"]["total"][0]["line_number"])
        self.assertEqual("2026-07-17T16:24+08:00", trend["markets"]["one_x_two"][0]["captured_at"])

    def test_unknown_page_label_uses_public_source_company_name(self):
        trend = parse_company_trend("<table></table>", 35, "2026-07-18 01:00")
        self.assertEqual("Wewbet", trend["name"])

    def test_first_move_deduplicates_same_company_across_markets(self):
        rows = [
            {"source_company_id": 35, "name": "Wewbet", "markets": {
                "asian": [
                    {"captured_at": "2026-07-17T10:00+08:00", "home_water": 0.90, "line_number": -0.5, "away_water": 0.90},
                    {"captured_at": "2026-07-17T10:05+08:00", "home_water": 0.85, "line_number": -0.5, "away_water": 0.95},
                ],
                "one_x_two": [
                    {"captured_at": "2026-07-17T10:00+08:00", "home": 1.80, "draw": 3.5, "away": 4.2},
                    {"captured_at": "2026-07-17T10:05+08:00", "home": 1.85, "draw": 3.5, "away": 4.1},
                ],
            }},
        ]
        panel = nowscore_trend_panel(rows)
        self.assertEqual(1, len(panel["first_moves"]))
        self.assertEqual({"asian", "one_x_two"}, set(panel["first_moves"][0]["markets"]))


if __name__ == "__main__":
    unittest.main()

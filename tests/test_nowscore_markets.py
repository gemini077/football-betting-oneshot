import unittest

from scripts.nowscore_markets import (
    handicap_number,
    parse_analysis_data,
    parse_schedule_js,
    parse_three_in_one,
    resolve_match,
    _verified,
)


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


if __name__ == "__main__":
    unittest.main()

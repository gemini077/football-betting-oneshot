import unittest

from scripts.nowscore_markets import (
    handicap_number,
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


if __name__ == "__main__":
    unittest.main()

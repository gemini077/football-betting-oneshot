import unittest
import json
import tempfile
from pathlib import Path
import sys
from datetime import date
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.nowscore_markets import (
    handicap_number,
    parse_coach_page,
    parse_company_trend,
    parse_nowscore_jc_business_page,
    parse_panlu_page,
    parse_referee_page,
    parse_analysis_data,
    parse_schedule_js,
    fetch_nowscore_jc_schedule,
    fetch_schedule_bundle,
    parse_three_in_one,
    resolve_match,
    _verified,
    _identity,
)
from market_intelligence import nowscore_trend_panel
import scripts.nowscore_markets as nowscore_markets
import scripts.daily_schedule_workspace as daily_schedule_workspace


SCHEDULE = """A[0]=[2912840,0,0,0,'瓦勒伦加',0,'Valerenga','奥勒松',0,'Aalesund FK','01:00','2026,6,17,01,00,00',0,0,0,0,0,0,0,0,0,0,0,'半/一',0,0,0,2.75];"""

BF1_ONLY_SCHEDULE = """var A=Array(1);
A[0]=[1001,0,111,222,'主队',0,'Home FC','客队',0,'Away FC','23:00','2026,7,31,23,00,00',0,0,0,,,0,0,0,0,'','','',0,'','','',0,0,0,0];"""

SC1_FUTURE_SCHEDULE = """var A=Array(2);
A[0]=[2001,1,333,444,'主队',0,'Home FC','客队',0,'Away FC','01:00','09-01',0,0,0,,,0,0,0,0,'','','',0,'','','',0,0,0,0];
A[1]=[2002,1,555,666,'第二主队',0,'Second Home','第二客队',0,'Second Away','02:00','09-02',0,0,0,,,0,0,0,0,'','','',0,'','','',0,0,0,0];"""

SC2_FUTURE_SCHEDULE = """var A=Array(2);
A[0]=[2002,1,555,666,'第二主队',0,'Second Home','第二客队',0,'Second Away','02:00','09-02',0,0,0,,,0,0,0,0,'','','',0,'','','',0,0,0,0];
A[1]=[2002,1,555,666,'第二主队',0,'Second Home','第二客队',0,'Second Away','02:00','09-02',0,0,0,,,0,0,0,0,'','','',0,'','','',0,0,0,0];"""


def _jc_business_page(
    headers: list[tuple[str, str]],
    selected_date: str,
    *,
    row: str = "",
    selector: bool = True,
) -> str:
    header_rows = "".join(
        f'<tr class="niDate"><td><span id="ah_{group}"></span>{header_date} '
        f'(11:00--\u6b21\u65e511:00)</td></tr>'
        for group, header_date in headers
    )
    selector_html = (
        '<select onchange="location.href=\'?date=\'+this.options['
        'this.selectedIndex].value"><option value="2026-09-03">03</option>'
        '</select>'
        if selector
        else ""
    )
    return (
        f'<script>var SelDate = "{selected_date}";</script>{selector_html}'
        f"<table>{header_rows}{row}</table>"
    )


def _jc_business_row(group: str = "周三", kickoff: str = "2026-09-03 12:00") -> str:
    return (
        f'<tr id="row_1" name="{group}" matchid="sales-1" gamename="League">'
        '<td>001</td><td></td><td></td><td></td>'
        '<td><a id="HomeTeam_123">Home</a></td><td></td><td></td>'
        '<td>Away</td>'
        f'<td title="{kickoff}"></td></tr>'
    )


def _fetch_jc_business_page(page: str, business_date: str) -> dict:
    with patch.object(nowscore_markets, "_fetch_bytes", return_value=page.encode("utf-8")):
        return fetch_nowscore_jc_schedule(
            business_date,
            now=date(2026, 9, 1),
        )


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


def _trusted_jc_fixture(match_id: int = 123, business_date: str = "2026-09-01") -> dict:
    sales_url = (
        "https://cp.nowscore.com/buy/jingcai.aspx"
        f"?typeID=101&oddstype=2&date={business_date}"
    )
    return {
        "homeTeam": "Fixture Home",
        "awayTeam": "Fixture Away",
        "businessDate": business_date,
        "matchDate": business_date,
        "matchTime": "01:00:00",
        "matchNum": "周二001",
        "nowscoreId": match_id,
        "nowscore_id": match_id,
        "nowscoreMatchStatus": "EXACT_MATCH",
        "nowscoreMatchConfidence": 1.0,
        "jc_membership": "VERIFIED",
        "jc_membership_source": "nowscore_public_jc_sales",
        "source_surface": sales_url,
        "source_url": sales_url,
        "business_date_source": "nowscore_public_jc_sales",
        "business_date_source_url": sales_url,
        "match_number_source": "nowscore_public_jc_sales",
        "sales_row_id": "5510001",
        "fetched_at": f"{business_date}T12:00:00+08:00",
        "jc_membership_evidence": {
            "source": "nowscore_public_jc_sales",
            "source_surface": sales_url,
            "selected_date": business_date,
            "business_date": business_date,
            "nowscore_id": match_id,
            "match_number": "周二001",
            "sales_row_id": "5510001",
            "sales_window": "11:00--次日11:00",
        },
        "date_provenance": {
            "source_date_value": f"{business_date} 01:00",
            "expected_business_date": business_date,
            "business_date": business_date,
            "business_date_source": "nowscore_public_jc_sales",
            "business_date_source_url": sales_url,
            "sales_window": "11:00--次日11:00",
            "match_number": "周二001",
            "sales_row_id": "5510001",
        },
    }


def _fetch_explicit_market(
    page_identity: dict,
    *,
    fixture: dict | None = None,
    kickoff: str = "2026-09-01T01:00:00+08:00",
    binding: dict | None = None,
    home: str = "Fixture Home",
    away: str = "Fixture Away",
    explicit_id: int = 123,
) -> dict:
    parsed = {
        "identity": page_identity,
        "ouzhi": {"bookmakers": [], "total": 0},
        "yazhi": {"companies": [], "total": 0},
        "daxiao": {"companies": [], "total": 0},
    }

    def fetch(url, timeout=30):
        if "bf1.js" in url:
            return b""
        if "odds/match" in url:
            return b"market"
        if "analysisJs" in url:
            return b"analysis"
        raise AssertionError(url)

    with tempfile.TemporaryDirectory() as directory, \
            patch.object(nowscore_markets, "CACHE_ROOT", Path(directory)), \
            patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch), \
            patch.object(nowscore_markets, "parse_three_in_one", return_value=parsed), \
            patch.object(nowscore_markets, "parse_analysis_data", return_value={"recent_form": {"ready": True}}), \
            patch.object(nowscore_markets, "fetch_context_bundle", return_value={}), \
            patch.object(nowscore_markets, "lookup_provider_binding", return_value=binding), \
            patch.object(nowscore_markets, "record_binding"):
        return nowscore_markets.fetch_match_markets(
            home,
            away,
            kickoff,
            explicit_id=explicit_id,
            no_cache=True,
            fixture=fixture,
        )


def _current_universe_fixture(match_id: int) -> dict:
    for business_date in ("2026-09-01", "2026-09-02"):
        document = json.loads(
            (ROOT / "data" / "prediction_universe" / f"{business_date}.json").read_text(
                encoding="utf-8"
            )
        )
        for fixture in document.get("fixtures") or []:
            if int(fixture.get("nowscoreId") or 0) == match_id:
                return fixture
    raise AssertionError(f"fixture {match_id} not found in current universe")


class NowscoreMarketTests(unittest.TestCase):
    def test_future_unpublished_date_is_classified_from_published_headers(self):
        page = _jc_business_page(
            [("周一", "2026-09-01"), ("周二", "2026-09-02")],
            "2026-09-03",
        )

        result = _fetch_jc_business_page(page, "2026-09-03")

        self.assertFalse(result["success"])
        self.assertEqual("NOT_YET_PUBLISHED", result["status"])
        self.assertIsNone(result["business_date_contract"]["requested_header"])
        self.assertEqual(
            ["2026-09-01", "2026-09-02"],
            [header["date"] for header in result["business_date_contract"]["headers"]],
        )

    def test_farther_future_date_is_also_not_yet_published(self):
        page = _jc_business_page(
            [("周一", "2026-09-01"), ("周二", "2026-09-02")],
            "2026-09-04",
        )

        result = _fetch_jc_business_page(page, "2026-09-04")

        self.assertEqual("NOT_YET_PUBLISHED", result["status"])

    def test_future_publication_uses_headers_not_selected_date_echo(self):
        page = _jc_business_page(
            [("\u5468\u4e00", "2026-09-01"), ("\u5468\u4e8c", "2026-09-02")],
            "2026-09-02",
        )

        result = _fetch_jc_business_page(page, "2026-09-03")

        self.assertEqual("NOT_YET_PUBLISHED", result["status"])

    def test_network_failure_is_not_not_yet_published(self):
        with patch.object(nowscore_markets, "_fetch_bytes", side_effect=OSError("down")):
            result = fetch_nowscore_jc_schedule(
                "2026-09-03",
                now=date(2026, 9, 1),
            )

        self.assertFalse(result["success"])
        self.assertEqual("FETCH_ERROR", result["status"])

    def test_missing_already_published_date_is_contract_failure(self):
        page = _jc_business_page(
            [("周一", "2026-09-01"), ("周三", "2026-09-03")],
            "2026-09-02",
        )

        result = _fetch_jc_business_page(page, "2026-09-02")

        self.assertEqual("BUSINESS_DATE_CONTRACT_REJECTED", result["status"])
        self.assertNotEqual("NOT_YET_PUBLISHED", result["status"])

    def test_malformed_or_conflicting_publication_headers_fail_closed(self):
        cases = (
            _jc_business_page(
                [("周一", "2026-09-01"), ("周一", "2026-09-02")],
                "2026-09-03",
            ),
            _jc_business_page(
                [("周一", "not-a-date")],
                "2026-09-03",
            ),
            _jc_business_page(
                [("周一", "2026-09-01")],
                "2026-09-03",
                selector=False,
            ),
        )

        for page in cases:
            with self.subTest(page=page):
                result = _fetch_jc_business_page(page, "2026-09-03")
                self.assertEqual("BUSINESS_DATE_CONTRACT_REJECTED", result["status"])

    def test_published_date_with_valid_rows_keeps_success_contract(self):
        page = _jc_business_page(
            [("周三", "2026-09-03")],
            "2026-09-03",
            row=_jc_business_row(),
        )

        result = _fetch_jc_business_page(page, "2026-09-03")

        self.assertTrue(result["success"])
        self.assertEqual("OK", result["status"])
        self.assertEqual(1, len(result["matches"]))

    def test_verified_binding_survives_schedule_outage(self):
        parsed = {
            "identity": {"home_team": "A", "away_team": "B", "kickoff_local": "2026-07-20 03:00"},
            "ouzhi": {"bookmakers": [], "total": 0},
            "yazhi": {"companies": [], "total": 0},
            "daxiao": {"companies": [], "total": 0},
        }

        def fetch(url, timeout=30):
            if "bf1.js" in url or "analysisJs" in url:
                raise OSError("temporary")
            return b"market"

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(nowscore_markets, "CACHE_ROOT", Path(directory)), \
                patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch), \
                patch.object(nowscore_markets, "lookup_provider_binding", return_value={"id": "77"}), \
                patch.object(nowscore_markets, "parse_three_in_one", return_value=parsed), \
                patch.object(nowscore_markets, "_verified", return_value=(True, [])), \
                patch.object(nowscore_markets, "fetch_context_bundle", return_value={}), \
                patch.object(nowscore_markets, "record_binding"):
            result = nowscore_markets.fetch_match_markets("A", "B", "2026-07-20 03:00", no_cache=True)

        self.assertEqual("OK", result["status"])
        self.assertEqual("STORED_VERIFIED_BINDING", result["resolution"]["status"])
        self.assertEqual(77, result["nowscore_id"])

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

    def test_bf1_only_does_not_fetch_unneeded_future_surface(self):
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            return BF1_ONLY_SCHEDULE.encode("utf-8")

        with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
            result = fetch_schedule_bundle(now=date(2026, 8, 31))

        self.assertEqual("OK", result["status"])
        self.assertEqual([1001], [row["nowscore_id"] for row in result["matches"]])
        self.assertEqual(1, len(calls))
        self.assertIn("bf1.js", calls[0])
        self.assertNotIn("sc1.js", calls[0])

    def test_bf1_plus_one_future_day_uses_expected_date(self):
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            if "bf1.js" in url:
                return BF1_ONLY_SCHEDULE.encode("utf-8")
            if "sc1.js" in url:
                return SC1_FUTURE_SCHEDULE.encode("utf-8")
            raise AssertionError(url)

        with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
            result = fetch_schedule_bundle(
                required_dates={"2026-09-01"}, now=date(2026, 8, 31)
            )

        self.assertEqual("OK", result["status"])
        self.assertEqual([1001, 2001], [row["nowscore_id"] for row in result["matches"]])
        self.assertEqual("2026-09-01", result["matches"][1]["schedule_source_date"])
        self.assertEqual(333, result["matches"][1]["home_team_id"])
        self.assertEqual(444, result["matches"][1]["away_team_id"])
        self.assertEqual(1, result["future_surface"]["sources"][0]["diagnostics"]["source_date_mismatch"])
        self.assertEqual(2, len(calls))
        self.assertTrue(any("sc1.js" in url for url in calls))

    def test_future_date_beyond_seven_days_is_not_fetched(self):
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            return BF1_ONLY_SCHEDULE.encode("utf-8")

        with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
            result = fetch_schedule_bundle(
                required_dates={"2026-09-08"}, now=date(2026, 8, 31)
            )

        self.assertEqual("DEGRADED", result["status"])
        self.assertEqual(1, len(calls))
        self.assertEqual("FUTURE_OFFSET_OUT_OF_RANGE", result["future_surface"]["errors"][0]["error"])

    def test_bf1_plus_two_required_future_days_fetches_only_sc1_and_sc2(self):
        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            if "bf1.js" in url:
                return BF1_ONLY_SCHEDULE.encode("utf-8")
            if "sc1.js" in url:
                return SC1_FUTURE_SCHEDULE.encode("utf-8")
            if "sc2.js" in url:
                return SC2_FUTURE_SCHEDULE.encode("utf-8")
            raise AssertionError(url)

        with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
            result = fetch_schedule_bundle(
                required_dates={"2026-09-01", "2026-09-02"},
                now=date(2026, 8, 31),
            )

        self.assertEqual("OK", result["status"])
        self.assertEqual([1001, 2001, 2002], [row["nowscore_id"] for row in result["matches"]])
        self.assertEqual(1, result["duplicate_nowscore_id_count"])
        self.assertEqual(3, len(calls))
        self.assertTrue(any("sc1.js" in url for url in calls))
        self.assertTrue(any("sc2.js" in url for url in calls))
        self.assertFalse(any("sc3.js" in url for url in calls))

    def test_future_surface_failure_keeps_bf1_and_records_degraded_provenance(self):
        def fetch(url, timeout=30):
            if "bf1.js" in url:
                return BF1_ONLY_SCHEDULE.encode("utf-8")
            raise OSError("sc1 down")

        with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
            result = fetch_schedule_bundle(
                required_dates={"2026-09-01"}, now=date(2026, 8, 31)
            )

        self.assertEqual("DEGRADED", result["status"])
        self.assertEqual([1001], [row["nowscore_id"] for row in result["matches"]])
        self.assertTrue(result["future_surface"]["errors"])
        self.assertIn("sc1", result["future_surface"]["errors"][0]["surface"])

    def test_expected_date_mismatch_is_rejected_without_year_guessing(self):
        self.assertEqual([], parse_schedule_js(SC1_FUTURE_SCHEDULE, expected_date="2026-09-03"))
        rows = parse_schedule_js(SC1_FUTURE_SCHEDULE, expected_date="2026-09-01")
        self.assertEqual([2001], [row["nowscore_id"] for row in rows])
        self.assertEqual([], parse_schedule_js(SC1_FUTURE_SCHEDULE))

    def test_year_end_future_surface_uses_expected_year(self):
        text = """var A=Array(1);
A[0]=[3001,1,777,888,'跨年主队',0,'Year End Home','跨年客队',0,'New Year Away','00:10','01-01',0,0,0,,,0,0,0,0,'','','',0,'','','',0,0,0,0];"""

        rows = parse_schedule_js(text, expected_date="2027-01-01")
        self.assertEqual(1, len(rows))
        self.assertEqual("2027-01-01T00:10+08:00", rows[0]["kickoff_local"])
        self.assertEqual([], parse_schedule_js(text, expected_date="2026-01-02"))

        calls = []

        def fetch(url, timeout=30):
            calls.append(url)
            return BF1_ONLY_SCHEDULE.encode("utf-8") if "bf1.js" in url else text.encode("utf-8")

        with patch.object(nowscore_markets, "_fetch_bytes", side_effect=fetch):
            bundle = fetch_schedule_bundle(
                required_dates={"2027-01-01"}, now=date(2026, 12, 31)
            )

        self.assertEqual("OK", bundle["status"])
        self.assertEqual([3001], [row["nowscore_id"] for row in bundle["matches"] if row["nowscore_id"] == 3001])
        self.assertEqual(2, len(calls))
        self.assertTrue(any("sc1.js" in url for url in calls))

    def test_no_wrong_match_binding_after_date_filter(self):
        rows = parse_schedule_js(SC1_FUTURE_SCHEDULE, expected_date="2026-09-01")
        exact = resolve_match("主队", "客队", "2026-09-01 01:00", rows)
        wrong_date = resolve_match("第二主队", "第二客队", "2026-09-02 02:00", rows)

        self.assertEqual("EXACT_MATCH", exact["status"])
        self.assertEqual(2001, exact["nowscore_id"])
        self.assertEqual("NO_EXACT_MATCH", wrong_date["status"])

    def test_daily_intake_collects_match_dates_before_prebinding(self):
        payloads = [{
            "matches": [{
                "homeTeam": "主队",
                "awayTeam": "客队",
                "matchDate": "2026-09-01",
                "matchTime": "01:00",
            }],
        }]
        requested_dates = []
        bundle = {
            "status": "OK",
            "matches": parse_schedule_js(SC1_FUTURE_SCHEDULE, expected_date="2026-09-01"),
            "future_surface": {"required_dates": ["2026-09-01"], "errors": []},
            "provenance": {},
            "errors": [],
        }

        def fetch(required_dates):
            requested_dates.extend(required_dates)
            return bundle

        def prebind(home, away, kickoff, schedule, *, fixture=None):
            self.assertEqual("主队", home)
            self.assertEqual("客队", away)
            self.assertEqual("2026-09-01T01:00:00+08:00", kickoff)
            self.assertEqual([2001], [row["nowscore_id"] for row in schedule])
            self.assertIs(payloads[0]["matches"][0], fixture)
            return {"status": "EXACT_MATCH", "nowscore_id": 2001, "match_confidence": 1.0}

        with patch.object(daily_schedule_workspace, "fetch_nowscore_schedule", side_effect=fetch), \
                patch.object(daily_schedule_workspace, "prebind_match", side_effect=prebind):
            result = daily_schedule_workspace.attach_nowscore_bindings(payloads)

        row = payloads[0]["matches"][0]
        self.assertEqual(["2026-09-01"], requested_dates)
        self.assertEqual(2001, row["nowscoreId"])
        self.assertEqual("EXACT_MATCH", row["nowscoreMatchStatus"])
        self.assertEqual(1, result["bound"])
        self.assertEqual("OK", result["status"])

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

    def test_identity_parser_marks_missing_zero_and_unparseable_page_ids_unavailable(self):
        pages = (
            '<input id="hide_matchTime" value="2026-09-01 01:00">',
            '<input id="hide_scheduleId" value="0">',
            '<input id="hide_scheduleId" value="not-an-id">',
        )

        for html in pages:
            with self.subTest(html=html):
                identity = _identity(html)
                self.assertEqual(0, identity["nowscore_id"])
                self.assertEqual("UNAVAILABLE", identity["page_provider_id_availability_state"])
                self.assertEqual("PAGE_PROVIDER_ID_UNAVAILABLE", identity["page_provider_id_reason"])

    def test_ordinary_explicit_id_accepts_valid_identity_when_page_id_is_unavailable(self):
        for page_id in (None, 0, "not-an-id"):
            with self.subTest(page_id=page_id):
                result = _fetch_explicit_market(
                    {
                        "nowscore_id": page_id,
                        "kickoff_local": "2026/09/01 01:00",
                        "home_team": "Fixture Home",
                        "away_team": "Fixture Away",
                    }
                )

                self.assertEqual("OK", result["status"])
                self.assertEqual("UNAVAILABLE", result["page_provider_id_availability_state"])
                self.assertEqual("ORDINARY_EXPLICIT_ID", result["identity_verification"]["status"])
                self.assertIn(
                    "PAGE_PROVIDER_ID_UNAVAILABLE",
                    result["identity_verification"]["non_blocking_reasons"],
                )

    def test_ordinary_explicit_id_name_mismatch_still_fails_closed_without_page_id(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 0,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            }
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("HOME_TEAM_MISMATCH", result["identity_errors"])
        self.assertIn("AWAY_TEAM_MISMATCH", result["identity_errors"])
        self.assertNotIn("PROVIDER_ID_MISMATCH", result["identity_errors"])

    def test_trusted_jc_accepts_fuzzy_names_when_page_id_is_unavailable(self):
        for page_id in (None, 0, "not-an-id"):
            with self.subTest(page_id=page_id):
                result = _fetch_explicit_market(
                    {
                        "nowscore_id": page_id,
                        "kickoff_local": "2026/09/01 01:00",
                        "home_team": "Home Translation",
                        "away_team": "Away Translation",
                    },
                    fixture=_trusted_jc_fixture(),
                )

                self.assertEqual("OK", result["status"])
                self.assertTrue(result["identity_verification"]["trusted"])
                self.assertEqual("TRUSTED_JC_SAME_PROVIDER", result["identity_verification"]["status"])
                self.assertIn(
                    "PAGE_PROVIDER_ID_UNAVAILABLE",
                    result["identity_verification"]["non_blocking_reasons"],
                )

    def test_pr143_regression_ordinary_explicit_id_remains_accepted_with_page_id_unavailable(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": None,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Fixture Home",
                "away_team": "Fixture Away",
            }
        )

        self.assertEqual("OK", result["status"])
        self.assertNotIn("PROVIDER_ID_MISMATCH", result.get("identity_errors", []))

    def test_current_failure_cohort_synthetic_replay_preserves_trusted_and_ordinary_paths(self):
        cohorts = {
            "2026-09-01": (3008191, 3008193),
            "2026-09-02": (3000437, 3000436, 2995152),
        }
        repaired_by_pr143 = (3008194, 3008190, 3008192, 3008739)

        for business_date, match_ids in cohorts.items():
            for match_id in match_ids:
                with self.subTest(business_date=business_date, match_id=match_id):
                    fixture = _current_universe_fixture(match_id)
                    kickoff = f"{fixture['matchDate']}T{fixture['matchTime']}:00+08:00"
                    result = _fetch_explicit_market(
                        {
                            "nowscore_id": 0,
                            "kickoff_local": f"{fixture['matchDate'].replace('-', '/')} {fixture['matchTime']}",
                            "home_team": "Home Translation",
                            "away_team": "Away Translation",
                        },
                        fixture=fixture,
                        kickoff=kickoff,
                        home=fixture["homeTeam"],
                        away=fixture["awayTeam"],
                        explicit_id=match_id,
                    )
                    self.assertEqual("OK", result["status"])

        for match_id in repaired_by_pr143:
            with self.subTest(business_date="2026-09-01", match_id=match_id):
                fixture = _current_universe_fixture(match_id)
                kickoff = f"{fixture['matchDate']}T{fixture['matchTime']}:00+08:00"
                result = _fetch_explicit_market(
                    {
                        "nowscore_id": 0,
                        "kickoff_local": f"{fixture['matchDate'].replace('-', '/')} {fixture['matchTime']}",
                        "home_team": "Home Translation",
                        "away_team": "Away Translation",
                    },
                    fixture=fixture,
                    kickoff=kickoff,
                    home=fixture["homeTeam"],
                    away=fixture["awayTeam"],
                    explicit_id=match_id,
                )
                self.assertEqual("OK", result["status"])

    def test_trusted_jc_explicit_id_allows_translated_market_names(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=_trusted_jc_fixture(),
        )

        self.assertEqual("OK", result["status"])
        self.assertEqual(123, result["nowscore_id"])
        self.assertEqual("TRUSTED_JC_SAME_PROVIDER", result["identity_verification"]["status"])
        self.assertTrue(result["identity_verification"]["page_provider_id_corroborated"])
        self.assertTrue(result["quality"]["recent_form_complete"])

    def test_explicit_id_without_trusted_jc_provenance_still_rejects_name_mismatch(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            }
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("HOME_TEAM_MISMATCH", result["identity_errors"])
        self.assertIn("AWAY_TEAM_MISMATCH", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_on_provenance_id_mismatch(self):
        fixture = _trusted_jc_fixture()
        fixture["jc_membership_evidence"]["nowscore_id"] = 999
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=fixture,
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("PROVIDER_ID_MISMATCH", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_on_market_page_id_mismatch(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 999,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=_trusted_jc_fixture(),
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("PROVIDER_ID_MISMATCH", result["identity_errors"])
        self.assertFalse(result["identity_verification"]["page_provider_id_corroborated"])

    def test_trusted_jc_path_fails_closed_when_membership_evidence_is_missing(self):
        fixture = _trusted_jc_fixture()
        fixture.pop("jc_membership_evidence")
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=fixture,
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("JC_MEMBERSHIP_EVIDENCE_MISSING", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_when_membership_is_unverified(self):
        fixture = _trusted_jc_fixture()
        fixture["jc_membership"] = "UNVERIFIED"
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=fixture,
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("JC_MEMBERSHIP_UNVERIFIED", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_on_conflicting_stored_binding(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=_trusted_jc_fixture(),
            binding={"id": "999"},
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("PROVIDER_ID_MISMATCH", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_on_ambiguous_match_status(self):
        fixture = _trusted_jc_fixture()
        fixture["nowscoreMatchStatus"] = "AMBIGUOUS_MATCH"
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=fixture,
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("NOWSCORE_MATCH_NOT_EXACT", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_on_ambiguous_page_identity(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Same Team",
                "away_team": "Same Team",
            },
            fixture=_trusted_jc_fixture(),
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("AMBIGUOUS_IDENTITY", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_when_target_and_fixture_are_reversed(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=_trusted_jc_fixture(),
            home="Fixture Away",
            away="Fixture Home",
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("ORIENTATION_CONFLICT", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_on_reversed_orientation(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Fixture Away",
                "away_team": "Fixture Home",
            },
            fixture=_trusted_jc_fixture(),
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("ORIENTATION_CONFLICT", result["identity_errors"])

    def test_trusted_jc_path_uses_provider_team_ids_for_reversed_translations(self):
        fixture = _trusted_jc_fixture()
        fixture.update({"home_team_id": 10, "away_team_id": 20})
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "home_team_id": 20,
                "away_team_id": 10,
                "kickoff_local": "2026/09/01 01:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=fixture,
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("ORIENTATION_CONFLICT", result["identity_errors"])

    def test_trusted_jc_path_fails_closed_on_fixture_kickoff_conflict(self):
        result = _fetch_explicit_market(
            {
                "nowscore_id": 123,
                "kickoff_local": "2026/09/01 02:00",
                "home_team": "Home Translation",
                "away_team": "Away Translation",
            },
            fixture=_trusted_jc_fixture(),
            kickoff="2026-09-01T02:00:00+08:00",
        )

        self.assertEqual("IDENTITY_MISMATCH", result["status"])
        self.assertIn("KICKOFF_MISMATCH", result["identity_errors"])

    def test_analysis_recent_form_is_oriented_to_each_target_team(self):
        result = parse_analysis_data(ANALYSIS_JS)
        form = result["recent_form"]
        self.assertEqual(101, result["team_ids"]["home"])
        self.assertEqual(202, result["team_ids"]["away"])
        self.assertEqual(5, form["home_overall"]["goals_for"])
        self.assertEqual(3, form["home_overall"]["goals_against"])
        self.assertEqual(1, form["home_home"]["matches"])
        self.assertEqual(1, form["away_away"]["matches"])

        recent_matches = result["recent_matches"]
        self.assertEqual(3, len(recent_matches["home_team"]))
        self.assertEqual(3, len(recent_matches["away_team"]))
        self.assertEqual({
            "source_date": "26-07-12",
            "match_date": "2026-07-12",
            "home_team_id": 9,
            "home_team_name": "opp",
            "away_team_id": 101,
            "away_team_name": "home",
            "home_goals": 2,
            "away_goals": 1,
        }, recent_matches["home_team"][0])
        self.assertEqual({
            "source_date": "26-07-11",
            "match_date": "2026-07-11",
            "home_team_id": 202,
            "home_team_name": "away",
            "away_team_id": 6,
            "away_team_name": "opp",
            "home_goals": 2,
            "away_goals": 2,
        }, recent_matches["away_team"][0])

    def test_analysis_recent_matches_skip_short_and_unparseable_rows(self):
        text = ANALYSIS_JS.replace(
            "];\nvar a_data",
            ",['not-a-date',22,'','#666',101,'home',8,'opp',1,0,'1-0'],"
            "['26-06-21',22,'','#666','bad','home',101,'opp',1,0,'1-0'],"
            "['short']];\nvar a_data",
        )

        result = parse_analysis_data(text)

        home_matches = result["recent_matches"]["home_team"]
        self.assertEqual(4, len(home_matches))
        self.assertEqual("not-a-date", home_matches[-1]["source_date"])
        self.assertIsNone(home_matches[-1]["match_date"])
        self.assertNotIn("bad", {row["home_team_id"] for row in home_matches})

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
        trend = parse_company_trend("<table></table>", 22, "2026-07-18 01:00", "Nowscore-22")
        self.assertEqual("10BET", trend["name"])

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

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.nowscore_jc_handicap_mirror_audit import (  # noqa: E402
    DELIVERY_FAIL_CLOSED,
    DELIVERY_NOT_EXECUTABLE,
    DELIVERY_PARITY_PARTIAL,
    DELIVERY_PARITY_PROVEN,
    _decide_delivery,
    _history_quote_matches,
    bind_fixed_comparator,
    parse_nowscore_analysis_page,
    parse_nowscore_history_page,
)


def _analysis_page() -> str:
    return """
    <script>
      var scheduleId = 12345;
      var homeTeam = "Home FC";
      var guestTeam = "Away FC";
      var MatchTimeStamp = 1788685200000;
    </script>
    <div class="fenxiBar"><div class="up"></div>竞彩指数</div>
    <div class="contentBox"><table class="mytable">
      <tr onclick="GoJcUrl(1)">
        <td></td><td class="firstOdds">1.69</td><td class="firstOdds">3.55</td><td class="firstOdds">3.90</td>
        <td>1.62</td><td>3.68</td><td>4.16</td>
      </tr>
      <tr onclick="GoJcUrl(0)">
        <td>-1</td><td class="firstOdds">3.22</td><td class="firstOdds">3.40</td><td class="firstOdds">1.91</td>
        <td>3.15</td><td>3.30</td><td>1.97</td>
      </tr>
    </table></div>
    <div class="fenxiBar"><div class="up"></div>积分排名</div>
    """


def _history_page() -> str:
    return """
    <script>
      var jcOddsData = {"scheduleId":12345,"jcOddsDetails":[
        {"rf":-1,"win":3.15,"draw":3.3,"lose":1.97,"changeTime":"2026-09-06T06:08:45Z"},
        {"rf":-1,"win":3.22,"draw":3.4,"lose":1.91,"changeTime":"2026-09-04T01:50:18Z"}
      ]};
    </script>
    """


def _comparator_row() -> dict:
    return {
        "business_date": "2026-09-06",
        "sporttery_match_id": 2041296,
        "match_num": "001",
        "home_team": "Home FC",
        "away_team": "Away FC",
        "match_date": "2026-09-06",
        "match_time": "17:00:00",
        "goal_line": -1,
        "odds": {"home": 3.22, "draw": 3.40, "away": 1.91},
        "raw_row": {"hhad": {"updateDate": "2026-09-04", "updateTime": "09:50:21"}},
        "raw_row_sha256": "fixture-hash",
    }


def _fixture() -> dict:
    return {
        "businessDate": "2026-09-06",
        "matchNum": "001",
        "homeTeam": "Home FC",
        "awayTeam": "Away FC",
        "matchDate": "2026-09-06",
        "matchTime": "17:00",
        "nowscoreId": 12345,
        "nowscore_id": 12345,
        "jc_membership": "VERIFIED",
        "jc_membership_source": "nowscore_public_jc_sales",
        "nowscoreMatchStatus": "EXACT_MATCH",
        "nowscoreMatchConfidence": 1.0,
        "jc_membership_evidence": {"nowscore_id": 12345},
    }


def test_explicit_jc_handicap_row_and_history_link_are_parsed_separately_from_asian():
    result = parse_nowscore_analysis_page(_analysis_page(), expected_nowscore_id=12345)

    assert result["section_found"] is True
    assert result["identity_status"] == "EXACT_ID"
    assert len(result["handicap_rows"]) == 1
    row = result["handicap_rows"][0]
    assert row["line"] == -1
    assert row["first_quote"] == {"home": 3.22, "draw": 3.4, "away": 1.91}
    assert row["current_quote"] == {"home": 3.15, "draw": 3.3, "away": 1.97}
    assert result["history_url"].endswith("scheid=12345&oddsType=0")
    assert result["identity"]["kickoff_date"] == "2026-09-06"
    assert result["identity"]["kickoff_time"] == "17:00:00"


def test_generic_asian_row_without_explicit_jc_section_is_not_evidence():
    html = """
    <script>var scheduleId=12345; var homeTeam="Home FC"; var guestTeam="Away FC";</script>
    <div class="fenxiBar"><div class="up"></div>赛前指数</div>
    <table><tr onclick="GoUrl(1,0)"><td>亚</td><td>1</td><td>0.5/1</td><td>0.88</td></tr></table>
    """

    result = parse_nowscore_analysis_page(html, expected_nowscore_id=12345)

    assert result["section_found"] is False
    assert result["handicap_rows"] == []


def test_history_value_match_does_not_resolve_non_equal_update_timestamp():
    comparator = _comparator_row()
    comparator = {
        "goal_line": comparator["goal_line"],
        "official_odds": comparator["odds"],
        "raw_row": comparator["raw_row"],
    }
    history = parse_nowscore_history_page(_history_page(), expected_nowscore_id=12345)

    value_match, time_resolved, reason = _history_quote_matches(comparator, history)

    assert value_match is True
    assert time_resolved is False
    assert reason == "HISTORY_VALUE_MATCH_TIMESTAMP_UNRESOLVED"


def test_binding_uses_exact_identity_and_rejects_duplicate_or_missing_candidates():
    comparator = {"rows": [_comparator_row()]}
    universe = {"fixtures": [_fixture()]}
    bound = bind_fixed_comparator(comparator, universe)

    assert bound["exact_deterministic_identity_n"] == 1
    assert bound["ambiguous"] == 0
    assert bound["unmatched"] == 0
    assert bound["conflicts"] == 0
    assert bound["rows"][0]["nowscore_id"] == 12345

    ambiguous = bind_fixed_comparator(comparator, {"fixtures": [_fixture(), _fixture()]})
    assert ambiguous["exact_deterministic_identity_n"] == 0
    assert ambiguous["ambiguous"] == 1
    assert ambiguous["duplicates"] >= 1

    unmatched = bind_fixed_comparator(comparator, {"fixtures": [{**_fixture(), "matchNum": "002"}]})
    assert unmatched["unmatched"] == 1
    assert unmatched["exact_deterministic_identity_n"] == 0


def test_delivery_decision_preserves_http_block_and_conflict_precedence():
    binding = {"comparator_n": 1, "exact_deterministic_identity_n": 1, "conflicts": 0}
    rows = [{"line_status": "AVAILABLE", "line_parity": "MATCH"}]

    assert _decide_delivery(
        binding=binding, rows=rows, page_success_n=1, blocked_n=0, semantic_conflict=False
    ) == DELIVERY_PARITY_PROVEN
    assert _decide_delivery(
        binding=binding, rows=rows, page_success_n=0, blocked_n=1, semantic_conflict=False
    ) == DELIVERY_NOT_EXECUTABLE
    assert _decide_delivery(
        binding=binding, rows=rows, page_success_n=1, blocked_n=0, semantic_conflict=True
    ) == DELIVERY_FAIL_CLOSED
    assert _decide_delivery(
        binding=binding, rows=[{"line_status": "NOT_AVAILABLE", "line_parity": "UNRESOLVED"}],
        page_success_n=1, blocked_n=0, semantic_conflict=False,
    ) == DELIVERY_PARITY_PARTIAL

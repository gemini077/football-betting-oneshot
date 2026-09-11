import json
import sys
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nowscore_prematch_evidence as evidence  # noqa: E402
import nowscore_prematch_adapters as adapters  # noqa: E402
from nowscore_context_depth_audit import build_audit_report  # noqa: E402


TARGET = {
    "home": "HOME_TEAM",
    "away": "AWAY_TEAM",
    "identity_home": "HOME_TEAM",
    "identity_away": "AWAY_TEAM",
    "kickoff": "2099-01-02T12:00:00+08:00",
    "competition": "LEAGUE_A",
    "season": "2028",
}

STANDINGS_MARKER = '<div class="fenxiBar" data-competition="LEAGUE_A" data-season="2028">\u79ef\u5206\u6392\u540d</div>'


def _payload(body, surface="analysis_page"):
    return evidence.SurfacePayload(
        surface,
        f"https://example.invalid/{surface}",
        body,
        {
            "observed_at": "2098-12-31T12:00:00+08:00",
            "source_update_at": "2098-12-30T12:00:00+08:00",
            "http_status": 200,
        },
    )


def _standings_table(team, seed):
    return dedent(
        f"""
        <div class="resultBar">{team}</div>
        <table>
          <tr><th>\u5168\u573a</th><th>\u8d5b</th><th>\u80dc</th><th>\u5e73</th><th>\u8d1f</th><th>\u5f97</th><th>\u5931</th><th>\u51c0</th><th>\u79ef\u5206</th><th>\u6392\u540d</th></tr>
          <tr><td>\u603b</td><td>6</td><td>{seed}</td><td>2</td><td>2</td><td>8</td><td>7</td><td>1</td><td>11</td><td>4</td></tr>
          <tr><td>\u4e3b</td><td>3</td><td>2</td><td>1</td><td>0</td><td>5</td><td>2</td><td>3</td><td>7</td><td>2</td></tr>
          <tr><td>\u5ba2</td><td>3</td><td>1</td><td>1</td><td>1</td><td>3</td><td>5</td><td>-2</td><td>4</td><td>8</td></tr>
          <tr><td>\u8fd1</td><td>6</td><td>{seed}</td><td>2</td><td>2</td><td>8</td><td>7</td><td>1</td><td>11</td><td>0</td></tr>
        </table>
        """
    )


def _future_table(team, home, away, interval, date_value):
    return dedent(
        f"""
        <div class="resultBar">{team}</div>
        <table>
          <tr><th>\u65f6\u95f4</th><th>\u8d5b\u4e8b</th><th>\u4e3b\u961f</th><th></th><th>\u5ba2\u961f</th><th>\u95f4\u9694</th></tr>
          <tr><td>{date_value}</td><td>CUP_A</td><td>{home}</td><td>-</td><td>{away}</td><td>{interval}</td></tr>
        </table>
        """
    )


def _availability_table(team, kind, rows):
    return dedent(
        f"""
        <div class="subBar">{kind}</div>
        <div class="resultBar">{team}</div>
        <table>
          <tr><th>Position</th><th>Player</th></tr>
          {rows}
        </table>
        """
    )


def _valid_analysis_page():
    return (
        STANDINGS_MARKER
        + _standings_table("HOME_TEAM", 3)
        + _standings_table("AWAY_TEAM", 4)
        + '<div class="fenxiBar">\u672a\u6765\u4e09\u573a</div>'
        + _future_table("HOME_TEAM", "HOME_TEAM", "OPPONENT_A", "3\u5929", "2099-01-05")
        + _future_table("AWAY_TEAM", "OPPONENT_B", "AWAY_TEAM", "4\u5929", "2099-01-06")
        + '<div class="fenxiBar">\u4f24\u505c\u60c5\u51b5</div>'
        + _availability_table(
            "HOME_TEAM",
            "\u4f24\u5458",
            '<tr><td>Forward</td><td>PLAYER_A</td></tr><tr><td>Defender</td><td>PLAYER_B</td></tr>',
        )
        + _availability_table(
            "AWAY_TEAM",
            "\u505c\u8d5b",
            '<tr><td>Goalkeeper</td><td>PLAYER_C</td></tr>',
        )
        + '<div class="fenxiBar">\u5a92\u4f53\u5206\u6790</div>'
        + '<table><tr><td>PLAYER_MEDIA must not become a structured field</td></tr></table>'
    )


def _fields(body, target=TARGET, surface="analysis_page"):
    return adapters._markup_adapter(_payload(body, surface), target)["fields"]


def _recent_process_matrix(rows=None, left_header="近3场/近10场", right_header="近3场/近10场"):
    rows = rows or [
        ("2.3 / 3.6", "进球", "4 / 3.5"),
        ("1.3 / 1.2", "失球", "1 / 1.1"),
        ("18.7 / 13", "被射门", "12.7 / 11.8"),
        ("5.7 / 5.3", "角球", "9 / 7.7"),
        ("13.3 / 12.2", "犯规", "9.3 / 9.6"),
        ("54.3% / 56.3%", "控球率", "63.7% / 59.2%"),
    ]
    body_rows = "".join(
        f"<tr><td>{left}</td><td>{label}</td><td>{right}</td></tr>"
        for left, label, right in rows
    )
    return (
        '<div class="fenxiBar">技术统计</div>'
        '<div class="resultBar">近期</div>'
        "<table>"
        f"<tr><th>{left_header}</th><th></th><th>{right_header}</th></tr>"
        f"{body_rows}</table>"
    )


def test_field_specific_analysis_page_projection_parses_all_three_targets():
    fields = _fields(_valid_analysis_page())

    standings = fields["standings_context"]
    assert standings["state"] == "PRESENT"
    assert standings["semantic_state"] == "EXPLICIT_STANDINGS_TABLE_SIDE_BOUND"
    assert set(standings["value"]["teams"]) == {"home", "away"}
    assert standings["value"]["season"] == "2028"
    assert standings["value"]["teams"]["home"]["splits"]["total"]["points"] == 11
    assert standings["value"]["teams"]["away"]["splits"]["total"]["rank"] == 4

    future = fields["future_schedule_rest"]
    assert future["state"] == "PRESENT"
    assert future["value"]["future_fixture_count"] == 2
    assert [row["target_orientation"] for row in future["value"]["fixtures"]] == ["home", "away"]
    assert [row["interval_source"] for row in future["value"]["fixtures"]] == ["source_interval", "source_interval"]
    assert [row["interval_days"] for row in future["value"]["fixtures"]] == [3, 4]

    availability = fields["availability_summary"]
    assert availability["state"] == "PRESENT"
    assert availability["value"]["counts"]["home"]["injury"] == 2
    assert availability["value"]["counts"]["away"]["suspension"] == 1
    assert availability["value"]["position_category_counts"]["home"]["injury"] == {
        "forward": 1,
        "defender": 1,
    }
    serialized = json.dumps(availability, ensure_ascii=False)
    assert "PLAYER_A" not in serialized
    assert "PLAYER_B" not in serialized
    assert "PLAYER_C" not in serialized
    assert "PLAYER_MEDIA" not in serialized
    assert "media" not in serialized.casefold()


def test_strict_fields_do_not_promote_generic_aliases_or_media_prose():
    body = dedent(
        """
        <h2>Standings</h2>
        <p>\u672a\u6765\u4e09\u573a 2099-01-05 HOME_TEAM OPPONENT_A</p>
        <div class="fenxiBar">\u5a92\u4f53\u5206\u6790</div>
        <table><tr><td>2099-01-05 HOME_TEAM OPPONENT_A PLAYER_MEDIA</td></tr></table>
        """
    )
    fields = _fields(body)
    assert fields["standings_context"]["state"] == "ABSENT"
    assert fields["future_schedule_rest"]["state"] == "ABSENT"
    assert fields["availability_summary"]["state"] == "ABSENT"


def test_standings_wrong_team_abbreviation_duplicate_and_stale_markers_fail_closed():
    wrong = _valid_analysis_page().replace(
        '<div class="resultBar">HOME_TEAM</div>',
        '<div class="resultBar">HOME</div>',
        1,
    )
    wrong_field = _fields(wrong)["standings_context"]
    assert wrong_field["state"] == "PARSE_UNCERTAIN"
    assert wrong_field["reason_code"] == "STANDINGS_WRONG_TEAM_BINDING"

    duplicate = _valid_analysis_page().replace(
        STANDINGS_MARKER,
        STANDINGS_MARKER + _standings_table("HOME_TEAM", 9),
        1,
    )
    duplicate_field = _fields(duplicate)["standings_context"]
    assert duplicate_field["state"] == "PARSE_UNCERTAIN"
    assert duplicate_field["reason_code"] == "STANDINGS_DUPLICATE_SIDE_TABLE"

    stale = _valid_analysis_page().replace(
        STANDINGS_MARKER,
        '<div class="fenxiBar" data-competition="LEAGUE_A" data-season="2028">\u79ef\u5206\u6392\u540d-\u4e0a\u4e00\u8d5b\u5b63</div>',
        1,
    )
    assert _fields(stale)["standings_context"]["state"] == "ABSENT"


def test_standings_requires_source_backed_competition_and_season_context():
    unproven = _valid_analysis_page().replace(
        STANDINGS_MARKER,
        '<div class="fenxiBar">\u79ef\u5206\u6392\u540d</div>',
        1,
    )
    field = _fields(unproven)["standings_context"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["reason_code"] == "STANDINGS_SOURCE_COMPETITION_SEASON_UNPROVEN"

    cup_target = dict(TARGET, competition="CUP_A")
    domestic_table = _fields(_valid_analysis_page(), cup_target)["standings_context"]
    assert domestic_table["state"] == "PARSE_UNCERTAIN"
    assert domestic_table["reason_code"] == "STANDINGS_SOURCE_COMPETITION_SEASON_MISMATCH"

    stale_season = _fields(_valid_analysis_page(), dict(TARGET, season="2027"))["standings_context"]
    assert stale_season["state"] == "PARSE_UNCERTAIN"
    assert stale_season["reason_code"] == "STANDINGS_SOURCE_COMPETITION_SEASON_MISMATCH"


def test_future_orientation_and_interval_validation_fail_closed():
    deterministic_interval = _valid_analysis_page().replace(
        '<th>\u95f4\u9694</th>',
        '<th>source-gap</th>',
        2,
    )
    deterministic = _fields(deterministic_interval)["future_schedule_rest"]
    assert deterministic["state"] == "PRESENT"
    assert all(
        row["interval_source"] == "deterministic_date_interval"
        for row in deterministic["value"]["fixtures"]
    )

    malformed_interval = _valid_analysis_page().replace("3\u5929", "three-days", 1)
    field = _fields(malformed_interval)["future_schedule_rest"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["reason_code"] == "FUTURE_INTERVAL_MALFORMED"

    malformed_row = _valid_analysis_page().replace("OPPONENT_A", "", 1)
    field = _fields(malformed_row)["future_schedule_rest"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["reason_code"] == "FUTURE_ROW_MALFORMED"

    home_table_owned_by_away = _valid_analysis_page().replace(
        _future_table("HOME_TEAM", "HOME_TEAM", "OPPONENT_A", "3\u5929", "2099-01-05"),
        _future_table("HOME_TEAM", "OPPONENT_B", "AWAY_TEAM", "3\u5929", "2099-01-05"),
        1,
    )
    field = _fields(home_table_owned_by_away)["future_schedule_rest"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["reason_code"] == "FUTURE_ROW_TARGET_OWNER_MISMATCH"

    wrong_side = _valid_analysis_page().replace(
        '<div class="resultBar">AWAY_TEAM</div>',
        '<div class="resultBar">OTHER_TEAM</div>',
        2,
    )
    field = _fields(wrong_side)["future_schedule_rest"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["reason_code"] == "FUTURE_WRONG_TEAM_BINDING"


def test_availability_requires_unambiguous_side_and_does_not_persist_player_names():
    ambiguous = (
        '<div class="fenxiBar">\u4f24\u505c\u60c5\u51b5</div>'
        + '<div class="subBar">\u4f24\u5458</div>'
        + '<table><tr><td>Forward</td><td>PLAYER_A</td></tr></table>'
    )
    field = _fields(ambiguous)["availability_summary"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["reason_code"] == "AVAILABILITY_SIDE_BINDING_AMBIGUOUS"
    assert "PLAYER_A" not in json.dumps(field, ensure_ascii=False)

    only_injury = (
        '<div class="fenxiBar">\u4f24\u505c\u60c5\u51b5</div>'
        + _availability_table(
            "HOME_TEAM",
            "\u4f24\u5458",
            '<tr><td>Forward</td><td>PLAYER_A</td></tr>',
        )
    )
    field = _fields(only_injury)["availability_summary"]
    assert field["state"] == "PRESENT"
    assert field["value"]["counts"]["home"]["injury"] == 1
    assert "suspension" not in field["value"]["counts"]["home"]
    assert "suspension" not in field["value"]["counts"]["away"]

    explicit_empty = (
        '<div class="fenxiBar">\u4f24\u505c\u60c5\u51b5</div>'
        + '<div class="subBar">\u4f24\u5458</div>'
        + '<div class="resultBar">HOME_TEAM</div>'
        + '<table><tr><td>No data</td></tr></table>'
    )
    assert _fields(explicit_empty)["availability_summary"]["state"] == "SECTION_PRESENT_EMPTY"


def test_field_specific_parser_is_deterministic_and_uses_verified_identity_context():
    body = _valid_analysis_page()
    first = _fields(body)
    second = _fields(body)
    for field in ("standings_context", "future_schedule_rest", "availability_summary"):
        assert first[field] == second[field]

    parser_target = evidence._analysis_page_target(
        {
            "home": "HOME_ABBREVIATION",
            "away": "AWAY_ABBREVIATION",
            "kickoff": TARGET["kickoff"],
        },
        {
            "home_team": "HOME_TEAM",
            "away_team": "AWAY_TEAM",
            "home_team_id": 1,
            "away_team_id": 2,
        },
        {"league": "LEAGUE_A", "season": "2028"},
    )
    assert parser_target["identity_home"] == "HOME_TEAM"
    assert parser_target["competition"] == "LEAGUE_A"
    assert parser_target["season"] == "2028"
    assert _fields(body, parser_target)["standings_context"]["state"] == "PRESENT"


def test_recent_process_matrix_is_side_bound_and_keeps_near3_near10_separate():
    field = _fields(_recent_process_matrix(), surface="time_page")["recent_process_context"]

    assert field["state"] == "PRESENT"
    assert field["semantic_state"] == "EXPLICIT_RECENT_PROCESS_MATRIX_SIDE_BOUND"
    value = field["value"]
    assert value["metrics"] == ["shots_faced", "corners", "fouls", "possession"]
    assert value["side_binding"] == "SOURCE_LEFT_HOME_RIGHT_AWAY"
    assert value["teams"]["home"]["shots_faced"] == {
        "near3": 18.7,
        "near10": 13.0,
        "unit": "source_value",
    }
    assert value["teams"]["away"]["corners"]["near3"] == 9.0
    assert value["teams"]["away"]["corners"]["near10"] == 7.7
    assert value["teams"]["home"]["possession"]["unit"] == "percent"
    assert value["source_cross_checks"]["goals"]["home"]["near3"] == 2.3


def test_recent_process_header_side_missing_or_asymmetric_fails_closed():
    missing = _fields(
        _recent_process_matrix(right_header="近3场"),
        surface="time_page",
    )["recent_process_context"]
    assert missing["state"] == "PARSE_UNCERTAIN"
    assert missing["reason_code"] in {
        "RECENT_PROCESS_HEADER_MISSING",
        "RECENT_PROCESS_HEADER_ASYMMETRIC",
    }

    no_header = _fields(
        _recent_process_matrix(left_header="", right_header=""),
        surface="time_page",
    )["recent_process_context"]
    assert no_header["state"] == "PARSE_UNCERTAIN"
    assert no_header["reason_code"] == "RECENT_PROCESS_HEADER_MISSING"


def test_recent_process_duplicate_and_malformed_supported_rows_fail_closed():
    duplicate = _fields(
        _recent_process_matrix(rows=[
            ("18.7/13", "被射门", "12.7/11.8"),
            ("5.7/5.3", "角球", "9/7.7"),
            ("6.0/5.0", "角球", "8.0/7.0"),
        ]),
        surface="time_page",
    )["recent_process_context"]
    assert duplicate["state"] == "PARSE_UNCERTAIN"
    assert duplicate["reason_code"] == "RECENT_PROCESS_DUPLICATE_METRIC"

    malformed = _fields(
        _recent_process_matrix(rows=[
            ("18.7", "被射门", "12.7/11.8"),
            ("54.3%/56.3%", "控球率", "63.7%/59.2%"),
        ]),
        surface="time_page",
    )["recent_process_context"]
    assert malformed["state"] == "PARSE_UNCERTAIN"
    assert malformed["reason_code"] == "RECENT_PROCESS_METRIC_VALUE_MALFORMED"


def test_recent_process_arbitrary_numeric_market_table_and_media_prose_are_not_evidence():
    market = _fields(
        _recent_process_matrix(rows=[("0.95/-0.5", "赔率", "0.85/-0.5")]),
        surface="time_page",
    )["recent_process_context"]
    assert market["state"] == "PARSE_UNCERTAIN"
    assert market["reason_code"] == "RECENT_PROCESS_NO_SUPPORTED_METRICS"

    media = _fields(
        '<div class="fenxiBar">媒体分析</div><p>控球率 99%/1% and tactical prose</p>',
        surface="time_page",
    )["recent_process_context"]
    assert media["state"] == "ABSENT"


def test_recent_process_partial_metric_coverage_is_explicit_and_deterministic():
    body = _recent_process_matrix(rows=[
        ("18.7/13", "被射门", "12.7/11.8"),
        ("54.3%/56.3%", "控球率", "63.7%/59.2%"),
    ])
    first = _fields(body, surface="time_page")["recent_process_context"]
    second = _fields(body, surface="time_page")["recent_process_context"]
    assert first == second
    assert first["state"] == "PRESENT"
    assert first["value"]["metrics"] == ["shots_faced", "possession"]
    assert "corners" not in first["value"]["teams"]["home"]


def test_exact_head_audit_reports_field_coverage_and_boundary_proof():
    fields = _fields(_valid_analysis_page())
    natural = {
        "run": {"as_of": "2098-12-31T12:00:00+08:00", "max_matches": 1},
        "cohort": {"selected_fixture_count": 1},
        "matches": [{
            "nowscore_id": 123,
            "status": "OK",
            "identity_verification": {"trusted": True},
            "trusted_jc_provenance": {"trusted": True},
            "prematch_evidence": {"fields": fields},
        }],
        "rights": {
            "raw_bodies_persisted": False,
            "raw_html_js_persisted": False,
            "player_name_lists_persisted": False,
        },
        "change_boundary": {
            "model_math_changed": False,
            "champion_changed": False,
            "serving_changed": False,
            "ui_changed": False,
            "provider_selection_changed": False,
        },
    }
    report = build_audit_report(natural, exact_head="EXACT_HEAD")
    assert report["run"]["exact_head"] == "EXACT_HEAD"
    assert report["coverage"]["selected_fixture_count"] == 1
    for field in ("standings_context", "future_schedule_rest", "availability_summary"):
        assert report["coverage"]["fields"][field]["eligible_fixture_count"] == 1
        assert report["coverage"]["fields"][field]["present_count"] == 1
    proof = report["boundary_proof"]
    assert proof["identity_violation_count"] == 0
    assert proof["side_binding_violation_count"] == 0
    assert proof["raw_body_persistence_count"] == 0
    assert proof["media_analysis_promotion_count"] == 0
    assert proof["player_name_persistence_count"] == 0
    assert len(report["sanitized_records"]) == 3


def test_recent_process_audit_reports_metric_completeness_and_request_parity():
    fields = {
        **_fields(_valid_analysis_page()),
        **_fields(_recent_process_matrix(), surface="time_page"),
    }
    natural = {
        "run": {"as_of": "2098-12-31T12:00:00+08:00", "max_matches": 1},
        "cohort": {"selected_fixture_count": 1},
        "matches": [{
            "nowscore_id": 123,
            "status": "OK",
            "identity_verification": {"trusted": True},
            "trusted_jc_provenance": {"trusted": True},
            "prematch_evidence": {
                "fields": fields,
                "observations": [{"surface": surface} for surface in evidence.SURFACES],
            },
        }],
        "rights": {
            "raw_bodies_persisted": False,
            "raw_html_js_persisted": False,
            "player_name_lists_persisted": False,
        },
    }
    report = build_audit_report(natural, exact_head="EXACT_HEAD")
    recent = report["coverage"]["fields"]["recent_process_context"]
    assert recent["present_count"] == 1
    assert all(item["present_count"] == 1 for item in recent["metric_completeness"].values())
    assert report["request_count"]["actual_request_count"] == len(evidence.SURFACES)
    assert report["request_count"]["baseline_request_count"] == len(evidence.SURFACES)
    assert report["request_count"]["delta"] == 0
    assert report["request_count"]["surface_sequence_violation_count"] == 0
    assert len(report["sanitized_recent_process_records"]) == 1

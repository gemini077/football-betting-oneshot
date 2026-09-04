from copy import deepcopy
from datetime import timedelta, timezone
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from exact_score_external_benchmark_coverage_preflight import (  # noqa: E402
    MAX_CREDITS,
    PROBE_REGION,
    PreflightError,
    ProviderClient,
    READ_ONLY_CONTROLS,
    _base_summary,
    build_candidate_cohort,
    decide_preflight,
    match_candidate_to_events,
    parse_regulation_scoreline,
    probe_correct_score_payload,
    run_preflight,
    write_artifacts,
)


TZ = timezone(timedelta(hours=8))


def _fixture(
    match_id="500-001",
    *,
    match_date="2026-09-05",
    match_time="20:00",
    home="Alpha",
    away="Beta",
    league="Test League",
):
    return {
        "matchId": match_id,
        "matchDate": match_date,
        "matchTime": match_time,
        "league": league,
        "homeTeam": home,
        "awayTeam": away,
    }


def _event(
    event_id="event-1",
    *,
    sport_key="soccer_test",
    commence_time="2026-09-05T12:00:00Z",
    home="Alpha",
    away="Beta",
):
    return {
        "id": event_id,
        "sport_key": sport_key,
        "commence_time": commence_time,
        "home_team": home,
        "away_team": away,
    }


def test_future_candidates_are_unique_and_past_candidates_are_excluded():
    documents = [
        {
            "status": "READY",
            "fixtures": [
                _fixture("past", match_date="2026-09-03"),
                _fixture("future"),
            ],
        },
        {"status": "READY", "fixtures": [_fixture("future")]},
    ]

    cohort = build_candidate_cohort(
        documents,
        snapshot_at="2026-09-04T12:00:00+08:00",
    )

    assert cohort["candidate_count"] == 1
    assert [row["match_id"] for row in cohort["candidates"]] == ["future"]
    assert cohort["deduplicated_match_count"] == 1


def test_exact_identity_requires_ordered_team_aliases_and_kickoff():
    cohort = build_candidate_cohort(
        [{"status": "READY", "fixtures": [_fixture()]}],
        snapshot_at="2026-09-04T12:00:00+08:00",
    )
    candidate = cohort["candidates"][0]

    matched = match_candidate_to_events(candidate, [_event()])

    assert matched["identity_status"] == "EXACT_MATCH"
    assert matched["provider_event_id"] == "event-1"
    assert matched["provider_sport_key"] == "soccer_test"
    assert matched["kickoff_delta_seconds"] == 0.0


def test_ambiguous_identity_is_not_counted_as_exact():
    cohort = build_candidate_cohort(
        [{"status": "READY", "fixtures": [_fixture()]}],
        snapshot_at="2026-09-04T12:00:00+08:00",
    )
    candidate = cohort["candidates"][0]

    matched = match_candidate_to_events(candidate, [_event("event-1"), _event("event-2")])

    assert matched["identity_status"] == "IDENTITY_AMBIGUOUS_FAIL_CLOSED"
    assert matched["provider_event_id"] is None


def test_identity_matching_does_not_use_fuzzy_team_similarity():
    cohort = build_candidate_cohort(
        [{"status": "READY", "fixtures": [_fixture(home="Arsenal", away="Chelsea")]}],
        snapshot_at="2026-09-04T12:00:00+08:00",
    )
    candidate = cohort["candidates"][0]

    matched = match_candidate_to_events(
        candidate,
        [_event(home="Arsenall", away="Chelseaa")],
    )

    assert matched["identity_status"] == "NO_EVENT_MATCH"
    assert matched["provider_event_id"] is None
    assert matched["identity_basis"] == "exact_or_existing_alias_only"


def test_regulation_time_scoreline_parser_is_deterministic():
    assert parse_regulation_scoreline("1-0") == (1, 0)
    assert parse_regulation_scoreline(" 2 - 3 ") == (2, 3)
    assert parse_regulation_scoreline("1:4") == (1, 4)
    assert parse_regulation_scoreline("Home") is None
    assert parse_regulation_scoreline("Any Other") is None
    assert parse_regulation_scoreline("1-0 (AET)") is None


def test_malformed_non_score_outcomes_do_not_count_as_correct_score_coverage():
    observation = probe_correct_score_payload(
        {
            "id": "event-1",
            "bookmakers": [
                {
                    "key": "bookmaker-1",
                    "title": "Bookmaker 1",
                    "last_update": "2026-09-04T12:01:00Z",
                    "markets": [
                        {
                            "key": "correct_score",
                            "last_update": "2026-09-04T12:01:00Z",
                            "outcomes": [
                                {"name": "Home", "price": 2.0},
                                {"name": "Any Other", "price": 5.0},
                            ],
                        }
                    ],
                }
            ],
        }
    )

    assert observation["correct_score_returned"] is True
    assert observation["correct_score_covered"] is False
    assert observation["parseable_outcome_count"] == 0
    assert observation["bookmaker_count"] == 1


def test_credit_cap_prevents_the_101st_event_odds_probe():
    calls = []

    def transport(path, params):
        calls.append((path, dict(params)))
        return {"id": "event", "bookmakers": []}, {"x-requests-last": "1"}

    client = ProviderClient("SECRET-API-KEY", transport=transport)
    for index in range(MAX_CREDITS):
        client.probe_event_odds("soccer_test", f"event-{index}")

    with pytest.raises(PreflightError, match="credit cap"):
        client.probe_event_odds("soccer_test", "event-101")

    assert len(calls) == MAX_CREDITS
    assert client.credits_reserved == MAX_CREDITS
    assert all(call[1]["regions"] == PROBE_REGION for call in calls)
    assert all(call[1]["markets"] == "correct_score" for call in calls)


def test_api_key_is_not_serialized_and_read_only_controls_are_explicit(tmp_path):
    secret = "SECRET-API-KEY"
    cohort = build_candidate_cohort(
        [{"status": "READY", "fixtures": [_fixture()]}],
        snapshot_at="2026-09-04T12:00:00+08:00",
    )
    summary = _base_summary(cohort, current_ref="fixture-ref")
    summary["source"]["request_secret"] = secret
    paths = write_artifacts(summary, tmp_path, secret=secret)
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in paths.values())

    assert secret not in serialized
    assert all(value is False for key, value in READ_ONLY_CONTROLS.items() if key != "read_only_preflight")
    assert READ_ONLY_CONTROLS["read_only_preflight"] is True


def test_candidate_build_is_read_only_for_fixture_input():
    documents = [{"status": "READY", "fixtures": [_fixture()]}]
    before = deepcopy(documents)

    build_candidate_cohort(documents, snapshot_at="2026-09-04T12:00:00+08:00")

    assert documents == before


def test_decision_requires_exact_and_parseable_coverage_under_the_cap():
    assert decide_preflight(
        candidate_count=12,
        exact_match_count=10,
        correct_score_covered_count=10,
        credits_used=10,
        kickoff_only_overlap_count=0,
    ) == "CORRECT_SCORE_BENCHMARK_PILOT_READY"
    assert decide_preflight(
        candidate_count=12,
        exact_match_count=5,
        correct_score_covered_count=5,
        credits_used=5,
        kickoff_only_overlap_count=10,
    ) == "IDENTITY_MAPPING_NOT_READY"
    assert decide_preflight(
        candidate_count=12,
        exact_match_count=5,
        correct_score_covered_count=5,
        credits_used=5,
        kickoff_only_overlap_count=0,
    ) == "PROVIDER_COVERAGE_INSUFFICIENT"


def test_preflight_probes_only_exact_events_and_keeps_provider_data_out_of_output(tmp_path):
    universe_root = tmp_path / "prediction_universe"
    universe_root.mkdir()
    (universe_root / "2026-09-05.json").write_text(
        json.dumps({"status": "READY", "fixtures": [_fixture()]}),
        encoding="utf-8",
    )
    calls = []

    def transport(path, params):
        calls.append((path, dict(params)))
        if path == "/v4/sports":
            return [{"key": "soccer_test", "group": "Soccer", "active": True}], {}
        if path == "/v4/sports/soccer_test/events":
            return [_event()], {}
        assert path == "/v4/sports/soccer_test/events/event-1/odds"
        assert params["regions"] == PROBE_REGION
        assert params["markets"] == "correct_score"
        return {
            "id": "event-1",
            "bookmakers": [{
                "key": "bookmaker-1",
                "markets": [{
                    "key": "correct_score",
                    "outcomes": [{"name": "1-0", "price": 6.0}],
                }],
            }],
        }, {"x-requests-last": "1"}

    summary = run_preflight(
        universe_root=universe_root,
        current_ref="fixture-ref",
        snapshot_at="2026-09-04T12:00:00+08:00",
        api_key="SECRET-API-KEY",
        client=ProviderClient("SECRET-API-KEY", transport=transport),
    )

    assert [path for path, _ in calls] == [
        "/v4/sports",
        "/v4/sports/soccer_test/events",
        "/v4/sports/soccer_test/events/event-1/odds",
    ]
    assert summary["probes"]["exact_match_count"] == 1
    assert summary["probes"]["correct_score_covered_count"] == 1
    assert summary["credits"]["credits_used"] == 1
    assert summary["final_decision"] == "PROVIDER_COVERAGE_INSUFFICIENT"
    assert "SECRET-API-KEY" not in json.dumps(summary)

from copy import deepcopy
from datetime import timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from exact_score_reep_identity_bridge_preflight import (  # noqa: E402
    BASELINE_PR179_CANDIDATE_COUNT,
    KICKOFF_TOLERANCE_SECONDS,
    MAX_CREDITS,
    PreflightError,
    ProviderClient,
    ReepIdentityRegister,
    build_candidate_cohort,
    bridge_candidate_to_events,
    decide_preflight,
    load_release_provenance,
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
    home="甲队",
    away="乙队",
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
    home="Alpha FC",
    away="Beta FC",
    competition=None,
):
    event = {
        "id": event_id,
        "sport_key": sport_key,
        "commence_time": commence_time,
        "home_team": home,
        "away_team": away,
    }
    if competition is not None:
        event["competition"] = competition
    return event


def _register(*, competition_rows=None, extra_team_rows=None, extra_alias_rows=None):
    team_rows = [
        {"reep_id": "rt-home", "status": "active", "label": "Alpha FC", "gender": "men", "country": "X"},
        {"reep_id": "rt-away", "status": "active", "label": "Beta FC", "gender": "men", "country": "X"},
    ]
    team_rows.extend(extra_team_rows or [])
    alias_rows = [
        {"reep_id": "rt-home", "alias": "甲队", "kind": "provider-name", "rank": "1", "language": "zh"},
        {"reep_id": "rt-away", "alias": "乙队", "kind": "provider-name", "rank": "1", "language": "zh"},
    ]
    alias_rows.extend(extra_alias_rows or [])
    return ReepIdentityRegister.from_rows(
        team_rows=team_rows,
        alias_rows=alias_rows,
        competition_rows=competition_rows or [],
    )


def test_future_candidates_are_unique_and_baseline_delta_is_explicit():
    documents = [
        {"status": "READY", "fixtures": [_fixture("past", match_date="2026-09-03"), _fixture("future")]},
        {"status": "READY", "fixtures": [_fixture("future")]},
    ]

    cohort = build_candidate_cohort(documents, snapshot_at="2026-09-04T12:00:00+08:00")

    assert cohort["candidate_count"] == 1
    assert [row["match_id"] for row in cohort["candidates"]] == ["future"]
    assert cohort["baseline_pr179_candidate_count"] == BASELINE_PR179_CANDIDATE_COUNT
    assert cohort["current_main_delta"] == 1 - BASELINE_PR179_CANDIDATE_COUNT


def test_exact_typed_alias_on_both_sides_resolves_same_reep_id():
    register = _register()

    home = register.resolve_team("甲队")
    provider_home = register.resolve_team("Alpha FC")

    assert home["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
    assert provider_home["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
    assert home["reep_id"] == provider_home["reep_id"] == "rt-home"
    assert home["alias_kind"] == "provider-name"
    assert home["language"] == "zh"


def test_existing_confirmed_alias_surface_preserves_evidence():
    register = ReepIdentityRegister.from_rows(
        team_rows=[{"reep_id": "rt-home", "status": "active", "label": "Alpha FC"}],
        existing_alias_rows=[{
            "canonical": "甲队",
            "aliases": ["Alpha FC"],
            "evidence": "confirmed_existing_bridge_fixture",
        }],
    )

    resolution = register.resolve_team("甲队")

    assert resolution["resolution_status"] == "UNIQUE_EXACT_REEP_ID"
    assert resolution["reep_id"] == "rt-home"
    assert resolution["matching_surface"] == "existing_data_team_aliases"
    assert resolution["existing_alias_evidence"] == "confirmed_existing_bridge_fixture"


def test_exact_name_collision_without_context_fails_closed():
    register = _register(
        extra_team_rows=[
            {"reep_id": "rt-other", "status": "active", "label": "City", "gender": "men", "country": "Y"},
            {"reep_id": "rt-city-w", "status": "active", "label": "City", "gender": "women", "country": "Y"},
        ],
        extra_alias_rows=[
            {"reep_id": "rt-other", "alias": "City", "kind": "provider-name", "rank": "1", "language": "en"},
            {"reep_id": "rt-city-w", "alias": "City", "kind": "provider-name", "rank": "1", "language": "en"},
        ],
    )

    resolution = register.resolve_team("City")

    assert resolution["resolution_status"] == "AMBIGUOUS_REEP_MATCH_FAIL_CLOSED"
    assert resolution["reep_id"] is None
    assert set(resolution["candidate_reep_ids"]) == {"rt-city-w", "rt-other"}


def test_fuzzy_translation_and_generated_transliteration_do_not_resolve():
    register = _register()

    assert register.resolve_team("Alpha FС")["resolution_status"] == "NO_REEP_MATCH"  # Cyrillic С.
    assert register.resolve_team("Alphaa FC")["resolution_status"] == "NO_REEP_MATCH"
    assert register.resolve_team("甲队翻译")["resolution_status"] == "NO_REEP_MATCH"


def test_reversed_home_away_cannot_match():
    cohort = build_candidate_cohort(
        [{"status": "READY", "fixtures": [_fixture()]}],
        snapshot_at="2026-09-04T12:00:00+08:00",
    )
    result = bridge_candidate_to_events(
        cohort["candidates"][0],
        [_event(home="Beta FC", away="Alpha FC")],
        _register(),
    )

    assert result["identity_status"] == "NO_EVENT_MATCH"
    assert result["reason_code"] == "REVERSED_HOME_AWAY"
    assert result["provider_event_id"] is None


def test_competition_contradiction_cannot_count_as_exact():
    register = _register(
        competition_rows=[
            {"reep_id": "rl-a", "status": "active", "label": "Competition A", "gender": "men", "country": "X"},
            {"reep_id": "rl-b", "status": "active", "label": "Competition B", "gender": "men", "country": "X"},
        ]
    )
    cohort = build_candidate_cohort(
        [{"status": "READY", "fixtures": [_fixture(league="Competition A")]}],
        snapshot_at="2026-09-04T12:00:00+08:00",
    )
    result = bridge_candidate_to_events(
        cohort["candidates"][0],
        [_event(competition="Competition B")],
        register,
    )

    assert result["identity_status"] == "NO_EVENT_MATCH"
    assert result["reason_code"] == "COMPETITION_CONTRADICTION"
    assert result["competition_context_status"] == "CONTRADICTORY"


def test_regulation_scoreline_parser_is_deterministic():
    assert parse_regulation_scoreline("1-0") == (1, 0)
    assert parse_regulation_scoreline(" 2 - 3 ") == (2, 3)
    assert parse_regulation_scoreline("1:4") == (1, 4)
    assert parse_regulation_scoreline("Home") is None
    assert parse_regulation_scoreline("Any Other") is None
    assert parse_regulation_scoreline("1-0 (AET)") is None


def test_malformed_non_score_outcomes_do_not_count_as_coverage():
    observation = probe_correct_score_payload(
        {
            "id": "event-1",
            "bookmakers": [{
                "key": "bookmaker-1",
                "last_update": "2026-09-04T12:01:00Z",
                "markets": [{
                    "key": "correct_score",
                    "outcomes": [
                        {"name": "Home", "price": 2.0},
                        {"name": "Any Other", "price": 5.0},
                    ],
                }],
            }],
        }
    )

    assert observation["correct_score_returned"] is True
    assert observation["correct_score_covered"] is False
    assert observation["parseable_outcome_count"] == 0


def test_only_exact_identity_triggers_correct_score_probe():
    universe_root = ROOT / "tests" / "fixtures" / "does-not-exist"
    register = _register()
    calls = []

    def transport(path, params):
        calls.append((path, dict(params)))
        if path == "/v4/sports":
            return [{"key": "soccer_test", "group": "Soccer", "active": True}], {}
        if path == "/v4/sports/soccer_test/events":
            return [_event(), _event("event-no", home="Unknown", away="Unknown")], {}
        assert path == "/v4/sports/soccer_test/events/event-1/odds"
        assert params["regions"] == "eu"
        assert params["markets"] == "correct_score"
        return {"id": "event-1", "bookmakers": [{
            "key": "bookmaker-1",
            "markets": [{"key": "correct_score", "outcomes": [{"name": "1-0", "price": 6.0}]}],
        }]}, {"x-requests-last": "1"}

    # Use a temporary canonical universe so the fixture remains isolated.
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "prediction_universe"
        root.mkdir()
        (root / "2026-09-05.json").write_text(
            json.dumps({"status": "READY", "fixtures": [_fixture()]}),
            encoding="utf-8",
        )
        summary = run_preflight(
            universe_root=root,
            current_ref="fixture-ref",
            snapshot_at="2026-09-04T12:00:00+08:00",
            api_key="SECRET-API-KEY",
            reep_register=register,
            client=ProviderClient("SECRET-API-KEY", transport=transport),
        )

    assert [path for path, _ in calls] == [
        "/v4/sports",
        "/v4/sports/soccer_test/events",
        "/v4/sports/soccer_test/events/event-1/odds",
    ]
    assert summary["probes"]["exact_event_identity_count"] == 1
    assert summary["probes"]["correct_score_covered_count"] == 1
    assert summary["credits"]["credits_used"] == 1
    assert summary["final_decision"] == "REEP_IDENTITY_COVERAGE_INSUFFICIENT"
    assert "SECRET-API-KEY" not in json.dumps(summary)


def test_credit_cap_prevents_the_101st_probe():
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
    assert all(call[1]["regions"] == "eu" for call in calls)
    assert all(call[1]["markets"] == "correct_score" for call in calls)


def test_release_provenance_is_verified_from_official_checksums(tmp_path):
    payloads = {
        "LICENSE.txt": b"CC0 1.0 Universal\n",
        "schema.json": b'{"files": {}}\n',
        "csv/teams.csv.gz": gzip.compress(b"reep_id,status,label,gender,country\nrt-1,active,Alpha,men,X\n"),
        "csv/aliases.csv.gz": gzip.compress(b"reep_id,alias,kind,rank,language\nrt-1,Alpha FC,provider-name,1,en\n"),
        "csv/competitions.csv.gz": gzip.compress(b"reep_id,status,label,gender,country\nrl-1,active,League,men,X\n"),
        "csv/redirects.csv.gz": gzip.compress(b"from_id,to_id,reason\n"),
    }
    file_meta = {}
    checksums = []
    for name, content in payloads.items():
        path = tmp_path / name.replace("/", "_")
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        file_meta[name] = {"bytes": len(content), "sha256": digest, "url": f"https://data.reep.football/releases/test/{name}"}
        checksums.append(f"{digest}  {name}")
    checksum_text = "\n".join(checksums) + "\n"
    (tmp_path / "checksums.txt").write_bytes(checksum_text.encode("utf-8"))
    file_meta["checksums.txt"] = {
        "bytes": len(checksum_text.encode("utf-8")),
        "sha256": hashlib.sha256(checksum_text.encode("utf-8")).hexdigest(),
        "url": "https://data.reep.football/releases/test/checksums.txt",
    }
    file_meta["schema.json"]["role"] = "metadata"
    file_meta["checksums.txt"]["role"] = "metadata"
    manifest = {
        "stamp": "test",
        "schema_version": "bridge-register-v1",
        "projection_mode": "public_bridge_v1",
        "release_schema_version": "bridge-register-v1",
        "tier": "public_bridge_v1",
        "licence": {"spdx": "CC0-1.0", "url": "https://creativecommons.org/publicdomain/zero/1.0/", "file": "LICENSE.txt"},
        "files": {name: {**meta, "role": "canonical_csv" if name.endswith(".gz") else "metadata"} for name, meta in file_meta.items()},
    }
    latest = {
        "schema_version": "reep-public-release-latest-v1",
        "stamp": manifest["stamp"],
        "release_tier": "public_bridge_v1",
        "release_schema_version": "bridge-register-v1",
        "manifest_url": "https://data.reep.football/releases/test/release.json",
        "manifest_sha256": "fixture-manifest-sha",
    }

    provenance = load_release_provenance(
        latest=latest,
        manifest=manifest,
        cache_dir=tmp_path,
        local_files={name: tmp_path / name.replace("/", "_") for name in payloads},
        checksums_path=tmp_path / "checksums.txt",
    )

    assert provenance["release_stamp"] == "test"
    assert provenance["access_status"] == "BOUNDED_CSV_READY"
    assert all(row["locally_verified"] for row in provenance["files"].values())
    assert provenance["duckdb_downloaded"] is False


def test_artifact_redacts_secret_and_declares_read_only_controls(tmp_path):
    register = _register()
    documents = [{"status": "READY", "fixtures": [_fixture()]}]
    before = deepcopy(documents)
    cohort = build_candidate_cohort(documents, snapshot_at="2026-09-04T12:00:00+08:00")
    summary = {
        "schema_version": "fixture",
        "milestone": "EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1",
        "candidate_cohort": cohort,
        "source": {"request_secret": "SECRET-API-KEY"},
        "controls": {
            "read_only_preflight": True,
            "result_network_fetch": False,
            "historical_backfill": False,
            "manual_identity_assignment": False,
            "fuzzy_matching": False,
            "frozen_prediction_modified": False,
            "authoritative_result_modified": False,
            "model_modified": False,
            "serving_modified": False,
        },
        "probes": {"candidate_results": []},
    }
    paths = write_artifacts(summary, tmp_path, secret="SECRET-API-KEY")
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in paths.values())

    assert "SECRET-API-KEY" not in serialized
    assert documents == before
    assert register.resolve_team("Alpha FC")["resolution_status"] == "UNIQUE_EXACT_REEP_ID"


def test_decision_has_only_issue_180_values():
    assert decide_preflight(exact_event_identity_count=10, correct_score_covered_count=10, credits_used=10) == "REEP_IDENTITY_AND_CORRECT_SCORE_PILOT_READY"
    assert decide_preflight(exact_event_identity_count=10, correct_score_covered_count=9, credits_used=10) == "REEP_IDENTITY_BRIDGE_USEFUL_COVERAGE_NOT_ENOUGH"
    assert decide_preflight(exact_event_identity_count=9, correct_score_covered_count=9, credits_used=9) == "REEP_IDENTITY_COVERAGE_INSUFFICIENT"
    assert decide_preflight(exact_event_identity_count=10, correct_score_covered_count=10, credits_used=101) == "FAIL_CLOSED"

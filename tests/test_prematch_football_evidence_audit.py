from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.prematch_football_evidence_audit import (
    MAX_REQUESTS,
    ApiFootballClient,
    ProviderResponse,
    RequestBudget,
    RequestBudgetExceeded,
    declare_cohort,
    resolve_provider_fixture,
    run_bounded_audit,
    summarize_prematch_payload,
)


UTC = timezone.utc
AS_OF = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 9, 10, 16, 45, tzinfo=UTC)


def _source_row(
    *,
    match_id: int = 1001,
    home: str = "Alpha United",
    away: str = "Beta City",
    kickoff: datetime = KICKOFF,
    provider_hints: bool = True,
) -> dict:
    local = kickoff.astimezone(timezone(timedelta(hours=8)))
    business_date = local.date().isoformat()
    match_number = f"周四{match_id:03d}"
    source_url = "https://fixture.test/nowscore"
    row = {
        "matchId": str(match_id),
        "nowscoreId": match_id,
        "nowscore_id": match_id,
        "matchDate": local.date().isoformat(),
        "matchTime": local.strftime("%H:%M"),
        "league": "欧冠杯",
        "homeTeam": home,
        "awayTeam": away,
        "businessDate": business_date,
        "nowscoreMatchStatus": "EXACT_MATCH",
        "nowscoreMatchConfidence": 1.0,
        "jc_membership": "VERIFIED",
        "jc_membership_source": "nowscore_public_jc_sales",
        "source_surface": source_url,
        "source_url": source_url,
        "business_date_source": "nowscore_public_jc_sales",
        "business_date_source_url": source_url,
        "matchNum": match_number,
        "match_number_source": "nowscore_public_jc_sales",
        "sales_row_id": str(match_id),
        "fetched_at": "2026-09-09T00:00:00+08:00",
        "jc_membership_evidence": {
            "source": "nowscore_public_jc_sales",
            "source_surface": source_url,
            "selected_date": business_date,
            "business_date": business_date,
            "match_number": match_number,
            "sales_row_id": str(match_id),
            "nowscore_id": match_id,
            "sales_window": "11:00--次日11:00",
        },
        "date_provenance": {
            "business_date": business_date,
            "expected_business_date": business_date,
            "business_date_source": "nowscore_public_jc_sales",
            "business_date_source_url": source_url,
            "match_number": match_number,
            "sales_row_id": str(match_id),
            "sales_window": "11:00--次日11:00",
        },
    }
    if provider_hints:
        row["api_football"] = {
            "fixture_id": "9001",
            "league_id": 2,
            "home": {"team_id": "101", "name": home},
            "away": {"team_id": "202", "name": away},
        }
    return row


def _provider_fixture(
    *,
    fixture_id: str = "9001",
    home: str = "Alpha United",
    away: str = "Beta City",
    home_id: str = "101",
    away_id: str = "202",
    date_value: str = "2026-09-10T16:45:00+00:00",
) -> dict:
    return {
        "fixture": {
            "id": fixture_id,
            "date": date_value,
            "status": {"short": "NS"},
        },
        "league": {"id": 2, "season": 2026, "round": "Group stage"},
        "teams": {
            "home": {"id": home_id, "name": home},
            "away": {"id": away_id, "name": away},
        },
    }


def _write_cohort(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / "cohort.json"
    path.write_text(
        json.dumps({"status": "READY", "fixtures": list(rows)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class RecordingClient:
    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict) -> ProviderResponse:
        self.calls.append((path, dict(params)))
        payload = self.responses.get(path, {"errors": {}})
        return ProviderResponse(
            payload=payload,
            acquired_at=AS_OF,
            response_sha256="a" * 64,
            http_status=200,
        )


def test_declare_cohort_is_future_only_and_one_match_one_observation(tmp_path: Path):
    future = _source_row()
    past = _source_row(
        match_id=1002,
        kickoff=datetime(2026, 9, 8, 16, 45, tzinfo=UTC),
    )
    declaration = declare_cohort(_write_cohort(tmp_path, future, past), as_of=AS_OF)

    assert len(declaration.matches) == 1
    assert declaration.future_rows == 1
    assert declaration.excluded_past_rows == 1
    assert declaration.public_summary()["future_only"] is True
    assert declaration.public_summary()["one_match_one_observation"] is True


def test_duplicate_canonical_match_fails_closed(tmp_path: Path):
    row = _source_row()
    declaration = declare_cohort(_write_cohort(tmp_path, row, dict(row)), as_of=AS_OF)

    assert declaration.duplicate_match_count == 1
    assert declaration.valid is False
    assert declaration.public_summary()["one_match_one_observation"] is False


def test_exact_identity_success_and_ambiguous_identity_fail_closed(tmp_path: Path):
    declaration = declare_cohort(_write_cohort(tmp_path, _source_row()), as_of=AS_OF)
    target = declaration.matches[0]
    exact = resolve_provider_fixture(target, [_provider_fixture()])
    ambiguous = resolve_provider_fixture(
        replace(target, provider_fixture_id=None),
        [_provider_fixture(), _provider_fixture(fixture_id="9002")],
    )

    assert exact["status"] == "EXACT_MATCH"
    assert exact["kickoff_delta_minutes"] == 0.0
    assert ambiguous["status"] == "AMBIGUOUS_MATCH"
    assert "candidate" not in ambiguous


def test_matching_does_not_use_fuzzy_or_result_aware_fields(tmp_path: Path):
    row = _source_row(
        home="Alfa United",
        away="Beta City",
        provider_hints=False,
    )
    declaration = declare_cohort(_write_cohort(tmp_path, row), as_of=AS_OF)
    target = declaration.matches[0]
    candidate = _provider_fixture(home="Alpha United", away="Beta City")
    candidate["goals"] = {"home": 0, "away": 9}

    result = resolve_provider_fixture(target, [candidate])

    assert result["status"] != "EXACT_MATCH"


def test_coverage_flags_suppress_unsupported_endpoint_calls(tmp_path: Path):
    cohort = _write_cohort(tmp_path, _source_row())
    client = RecordingClient(
        {
            "/fixtures": {"response": [_provider_fixture()]},
            "/leagues": {
                "response": [
                    {
                        "seasons": [
                            {
                                "season": 2026,
                                "coverage": {
                                    "fixtures": False,
                                    "lineups": False,
                                    "injuries": False,
                                    "odds": True,
                                    "statistics_fixtures": False,
                                },
                            }
                        ]
                    }
                ]
            },
            "/odds": {"response": []},
        }
    )

    result = run_bounded_audit(cohort, api_key="SECRET", as_of=AS_OF, client=client)
    paths = [path for path, _params in client.calls]

    assert result["decision"] == "COVERAGE_TOO_THIN"
    assert "/odds" in paths
    assert "/fixtures/lineups" not in paths
    assert "/injuries" not in paths
    assert "/fixtures/statistics" not in paths


def test_request_budget_and_rate_cap_are_enforced():
    clock = [0.0]

    def monotonic() -> float:
        return clock[0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    budget = RequestBudget(monotonic=monotonic, sleep=sleep)
    for _ in range(MAX_REQUESTS):
        budget.reserve()

    assert budget.used == MAX_REQUESTS
    assert budget.waited_seconds >= 60.0
    with pytest.raises(RequestBudgetExceeded):
        budget.reserve()


def test_missing_key_returns_explicit_secret_gate_without_requests(tmp_path: Path):
    result = run_bounded_audit(
        _write_cohort(tmp_path, _source_row()),
        api_key=None,
        as_of=AS_OF,
    )

    assert result["decision"] == "FOUNDER_SECRET_REQUIRED"
    assert result["requests"]["used"] == 0
    assert result["api_key_persisted"] is False


def test_post_kickoff_current_match_payload_is_suppressed():
    summary = summarize_prematch_payload(
        "events",
        {"response": [{"time": {"elapsed": 12}, "goals": {"home": 1, "away": 0}}]},
        target_kickoff=KICKOFF,
        acquired_at=KICKOFF - timedelta(minutes=20),
    )

    assert summary["provider_row_count"] == 1
    assert summary["usable_prematch_row_count"] == 0
    assert summary["post_kickoff_suppressed_row_count"] == 1


def test_post_kickoff_timestamp_suppresses_only_its_own_row():
    summary = summarize_prematch_payload(
        "odds",
        {
            "response": [
                {"update": "2026-09-10T15:00:00+00:00", "values": ["pre-kickoff"]},
                {"update": "2026-09-10T17:00:00+00:00", "values": ["post-kickoff"]},
            ]
        },
        target_kickoff=KICKOFF,
        acquired_at=KICKOFF - timedelta(minutes=20),
    )

    assert summary["usable_prematch_row_count"] == 1
    assert summary["post_kickoff_suppressed_row_count"] == 1


def test_public_summary_contains_no_key_or_raw_provider_response(tmp_path: Path):
    cohort = _write_cohort(tmp_path, _source_row())
    secret = "SECRET_PAYLOAD"
    client = RecordingClient(
        {
            "/fixtures": {"response": [_provider_fixture()], "echo": secret},
            "/leagues": {"errors": {"message": secret}},
        }
    )

    result = run_bounded_audit(cohort, api_key=secret, as_of=AS_OF, client=client)
    serialized = json.dumps(result, ensure_ascii=False)

    assert secret not in serialized
    assert "provider_fixture_id" not in serialized
    assert "echo" not in serialized
    assert result["raw_provider_responses_written"] is False


def test_network_client_sends_key_only_as_header():
    class Response:
        status = 200

        def read(self) -> bytes:
            return b'{"response": [], "errors": {}}'

        def close(self) -> None:
            pass

    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return Response()

    client = ApiFootballClient(
        "HEADER_ONLY_SECRET",
        opener=opener,
        budget=RequestBudget(max_requests=1),
    )
    client.get("/fixtures", {"date": "2026-09-10"})

    assert "HEADER_ONLY_SECRET" not in captured["url"]
    assert captured["headers"]["X-apisports-key"] == "HEADER_ONLY_SECRET"

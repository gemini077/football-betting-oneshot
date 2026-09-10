from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.nowscore_prematch_evidence_audit import (
    ALLOWED_STATES,
    FIELD_NAMES,
    NowscorePublicClient,
    ObservationMetadata,
    SURFACE_NAMES,
    declare_cohort,
    run_bounded_audit,
    summarize_surface,
    validate_same_id_identity,
)
from scripts.prediction_universe import TRUSTED_NOWSCORE_JC_SALES_WINDOW


UTC = timezone.utc
SHANGHAI = timezone(timedelta(hours=8))
AS_OF = datetime(2026, 9, 10, 12, 0, tzinfo=SHANGHAI)
KICKOFF = datetime(2026, 9, 11, 0, 45, tzinfo=SHANGHAI)


def _source_row(
    *,
    nowscore_id: int = 3073166,
    kickoff: datetime = KICKOFF,
    home_team: str = "主队 Alpha",
    away_team: str = "客队 Beta",
    home_team_id: int | None = None,
    away_team_id: int | None = None,
) -> dict:
    source_url = "https://fixture.test/nowscore-jc"
    business_date = "2026-09-10"
    match_number = "周四001"
    row = {
        "matchId": str(nowscore_id),
        "nowscoreId": nowscore_id,
        "nowscore_id": nowscore_id,
        "matchDate": kickoff.astimezone(SHANGHAI).date().isoformat(),
        "matchTime": kickoff.astimezone(SHANGHAI).strftime("%H:%M"),
        "league": "测试联赛",
        "homeTeam": home_team,
        "awayTeam": away_team,
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
        "sales_row_id": str(nowscore_id),
        "fetched_at": "2026-09-10T11:00:00+08:00",
        "jc_membership_evidence": {
            "source": "nowscore_public_jc_sales",
            "source_surface": source_url,
            "selected_date": business_date,
            "business_date": business_date,
            "match_number": match_number,
            "sales_row_id": str(nowscore_id),
            "nowscore_id": nowscore_id,
            "sales_window": TRUSTED_NOWSCORE_JC_SALES_WINDOW,
        },
        "date_provenance": {
            "business_date": business_date,
            "expected_business_date": business_date,
            "business_date_source": "nowscore_public_jc_sales",
            "business_date_source_url": source_url,
            "match_number": match_number,
            "sales_row_id": str(nowscore_id),
            "sales_window": TRUSTED_NOWSCORE_JC_SALES_WINDOW,
        },
    }
    if home_team_id is not None:
        row["home_team_id"] = home_team_id
    if away_team_id is not None:
        row["away_team_id"] = away_team_id
    return row


def _write_cohort(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / "cohort.json"
    path.write_text(json.dumps({"status": "READY", "fixtures": list(rows)}, ensure_ascii=False), encoding="utf-8")
    return path


def _target(tmp_path: Path, row: dict | None = None):
    return declare_cohort(_write_cohort(tmp_path, row or _source_row()), as_of=AS_OF).matches[0]


def _market_html(
    *,
    nowscore_id: int = 3073166,
    kickoff: str = "2026-09-11 00:45",
    home: str = "主队 Alpha",
    away: str = "客队 Beta",
) -> bytes:
    return f"""
    <input id="hide_scheduleId" value="{nowscore_id}">
    <input id="hide_matchTime" value="{kickoff}">
    <div id="home"><a class="name">{home}</a></div>
    <div id="guest"><a class="name">{away}</a></div>
    <div>欧赔 亚盘 大小球</div>
    """.encode("utf-8")


def _metadata(
    surface: str,
    *,
    observed_at: datetime = AS_OF,
    http_status: int | None = 200,
    error_code: str | None = None,
    source_update_at: datetime | None = None,
) -> ObservationMetadata:
    return ObservationMetadata(
        surface=surface,
        request_started_at=observed_at - timedelta(seconds=2),
        response_at=observed_at - timedelta(seconds=1),
        observed_at=observed_at,
        http_status=http_status,
        content_sha256="a" * 64,
        content_length=32,
        source_update_at=source_update_at,
        source_update_basis="HTTP_LAST_MODIFIED" if source_update_at else "NOT_EXPOSED",
        error_code=error_code,
    )


class FakeClient:
    def __init__(self, bodies: dict[str, bytes] | None = None, statuses: dict[str, int] | None = None):
        self.bodies = bodies or {}
        self.statuses = statuses or {}
        self.calls: list[tuple[str, str]] = []

    def fetch(self, surface: str, url: str) -> tuple[ObservationMetadata, bytes]:
        self.calls.append((surface, url))
        status = self.statuses.get(surface, 200)
        error_code = f"HTTP_{status}" if status >= 400 else None
        return _metadata(surface, http_status=status, error_code=error_code), self.bodies.get(surface, b"<html></html>")


def test_natural_cohort_keeps_only_future_trusted_nowscore_rows(tmp_path: Path):
    declaration = declare_cohort(
        _write_cohort(
            tmp_path,
            _source_row(),
            _source_row(nowscore_id=3073167, kickoff=datetime(2026, 9, 9, 12, 0, tzinfo=SHANGHAI)),
        ),
        as_of=AS_OF,
    )

    assert len(declaration.matches) == 1
    assert declaration.future_rows == 1
    assert declaration.excluded_nonfuture_rows == 1
    assert declaration.public_summary()["future_only"] is True
    assert declaration.public_summary()["one_match_one_observation"] is True


def test_duplicate_same_id_is_not_collapsed_into_a_valid_observation(tmp_path: Path):
    row = _source_row()
    declaration = declare_cohort(_write_cohort(tmp_path, row, dict(row)), as_of=AS_OF)

    assert declaration.duplicate_match_count == 1
    assert declaration.valid is False


def test_wrong_nowscore_id_or_kickoff_is_a_conflict(tmp_path: Path):
    target = _target(tmp_path)
    wrong_id = validate_same_id_identity(
        target,
        {"nowscore_id": target.nowscore_id + 1, "kickoff_local": "2026-09-11 00:45", "home_team": target.home_team, "away_team": target.away_team},
    )
    wrong_time = validate_same_id_identity(
        target,
        {"nowscore_id": target.nowscore_id, "kickoff_local": "2026-09-11 01:45", "home_team": target.home_team, "away_team": target.away_team},
    )

    assert wrong_id["state"] == "CONFLICT"
    assert "PAGE_ID_MISMATCH" in wrong_id["reason_codes"]
    assert wrong_time["state"] == "CONFLICT"
    assert "KICKOFF_MISMATCH" in wrong_time["reason_codes"]

    result = run_bounded_audit(
        _write_cohort(tmp_path, _source_row()),
        as_of=AS_OF,
        client=FakeClient({"market_context": _market_html(nowscore_id=target.nowscore_id + 1)}),
    )
    assert result["decision"] == "FAIL_CLOSED"
    assert [surface for surface, _url in result["matches"][0]["surfaces"].items()] == ["market_context"]


def test_same_provider_name_variants_are_diagnostics_not_conflicts(tmp_path: Path):
    target = _target(tmp_path, _source_row(home_team="拜仁", away_team="曼联"))
    result = validate_same_id_identity(
        target,
        {
            "nowscore_id": target.nowscore_id,
            "page_provider_id": target.nowscore_id,
            "kickoff_local": "2026-09-11 00:45",
            "home_team": "拜仁慕尼黑",
            "away_team": "曼彻斯特联",
        },
    )

    assert result["state"] == "PRESENT"
    assert "HOME_TEAM_MISMATCH" not in result["reason_codes"]
    assert "AWAY_TEAM_MISMATCH" not in result["reason_codes"]


def test_name_variant_identity_reaches_richer_surfaces(tmp_path: Path):
    cohort = _write_cohort(tmp_path, _source_row(home_team="拜仁", away_team="曼联"))
    client = FakeClient(
        {
            "market_context": _market_html(home="拜仁慕尼黑", away="曼彻斯特联"),
        }
    )

    result = run_bounded_audit(cohort, as_of=AS_OF, client=client)

    assert result["matches"][0]["identity"]["state"] == "PRESENT"
    assert [surface for surface, _url in client.calls] == list(SURFACE_NAMES)


def test_reversed_same_provider_sides_still_fail_closed(tmp_path: Path):
    target = _target(tmp_path)
    result = validate_same_id_identity(
        target,
        {
            "nowscore_id": target.nowscore_id,
            "page_provider_id": target.nowscore_id,
            "kickoff_local": "2026-09-11 00:45",
            "home_team": target.away_team,
            "away_team": target.home_team,
        },
    )

    assert result["state"] == "CONFLICT"
    assert "ORIENTATION_CONFLICT" in result["reason_codes"]


def test_page_provider_id_disagreement_fails_closed(tmp_path: Path):
    target = _target(tmp_path)
    result = validate_same_id_identity(
        target,
        {
            "nowscore_id": target.nowscore_id,
            "page_provider_id": target.nowscore_id + 1,
            "kickoff_local": "2026-09-11 00:45",
            "home_team": target.home_team,
            "away_team": target.away_team,
        },
    )

    assert result["state"] == "CONFLICT"
    assert "PAGE_ID_MISMATCH" in result["reason_codes"]
    assert "PAGE_PROVIDER_ID_MISMATCH" in result["reason_codes"]


def test_existing_provider_team_ids_fail_closed_for_unrelated_page_identity(tmp_path: Path):
    target = _target(
        tmp_path,
        _source_row(
            home_team="Known Home",
            away_team="Known Away",
            home_team_id=10,
            away_team_id=20,
        ),
    )
    result = validate_same_id_identity(
        target,
        {
            "nowscore_id": target.nowscore_id,
            "page_provider_id": target.nowscore_id,
            "kickoff_local": "2026-09-11 00:45",
            "home_team": "Unrelated Home",
            "away_team": "Unrelated Away",
            "home_team_id": 99,
            "away_team_id": 100,
        },
    )

    assert result["state"] == "CONFLICT"
    assert "HOME_TEAM_ID_MISMATCH" in result["reason_codes"]
    assert "AWAY_TEAM_ID_MISMATCH" in result["reason_codes"]


def test_post_kickoff_observation_cannot_be_used_as_prematch_evidence(tmp_path: Path):
    target = _target(tmp_path)
    summary = summarize_surface(
        target,
        "analysis_page",
        "<h2>近期战绩</h2><div>post-kickoff content</div>".encode(),
        _metadata("analysis_page", observed_at=KICKOFF + timedelta(minutes=1)),
    )

    assert summary["chronology"]["relation"] == "AFTER_KICKOFF"
    assert summary["chronology"]["prematch_eligible"] is False
    assert all(item["prematch_eligible"] is False for item in summary["fields"].values())
    assert all(item["state"] == "CONFLICT" for item in summary["fields"].values())


def test_explicit_source_update_after_kickoff_is_not_prematch(tmp_path: Path):
    target = _target(tmp_path)
    summary = summarize_surface(
        target,
        "analysis_page",
        "<h2>recent form</h2>".encode(),
        _metadata(
            "analysis_page",
            source_update_at=KICKOFF + timedelta(minutes=1),
        ),
    )

    assert summary["chronology"]["relation"] == "CROSSED_KICKOFF"
    assert summary["chronology"]["prematch_eligible"] is False


def test_empty_injury_section_is_distinct_from_absent_section(tmp_path: Path):
    target = _target(tmp_path)
    empty = summarize_surface(
        target,
        "analysis_page",
        "<h2>伤停</h2><div>暂无数据</div>".encode(),
        _metadata("analysis_page"),
    )
    absent = summarize_surface(
        target,
        "analysis_page",
        "<h2>近期战绩</h2><div>有数据</div>".encode(),
        _metadata("analysis_page"),
    )

    assert empty["fields"]["injuries"]["state"] == "SECTION_PRESENT_EMPTY"
    assert absent["fields"]["injuries"]["state"] == "ABSENT"


def test_unlabelled_lineup_does_not_get_confirmed_or_predicted_semantics(tmp_path: Path):
    target = _target(tmp_path)
    summary = summarize_surface(
        target,
        "time_page",
        "<h2>首发阵容</h2><ul><li>player content</li></ul>".encode(),
        _metadata("time_page"),
    )

    lineup = summary["fields"]["lineup_state"]
    assert lineup["state"] == "PRESENT"
    assert lineup["semantic_state"] == "UNLABELLED"
    assert lineup["semantic_state"] not in {"CONFIRMED", "PREDICTED"}


def test_login_gated_page_is_recorded_without_bypass(tmp_path: Path):
    cohort = _write_cohort(tmp_path, _source_row())
    client = FakeClient(
        bodies={"market_context": "<html>请登录后查看</html>".encode()},
        statuses={"market_context": 403},
    )

    result = run_bounded_audit(cohort, as_of=AS_OF, client=client)

    assert result["decision"] == "ACCESS_OR_RIGHTS_BOUNDARY_BLOCKED"
    assert result["matches"][0]["surfaces"]["market_context"]["publication"]["state"] == "ACCESS_GATED"
    assert [surface for surface, _url in client.calls] == ["market_context"]


def test_observed_at_is_not_relabelled_as_source_update_timestamp():
    class Response:
        status = 200
        headers = {}

        def read(self) -> bytes:
            return b"<html>public</html>"

        def close(self) -> None:
            pass

    times = iter(
        [
            datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
            datetime(2026, 9, 10, 4, 0, 1, tzinfo=UTC),
            datetime(2026, 9, 10, 4, 0, 2, tzinfo=UTC),
        ]
    )
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return Response()

    client = NowscorePublicClient(opener=opener, clock=lambda: next(times), max_requests=1)
    metadata, _body = client.fetch("analysis_page", "https://m.nowscore.com/Analy/Analysis/3073166.htm")

    assert metadata.source_update_at is None
    assert metadata.source_update_basis == "NOT_EXPOSED"
    assert metadata.observed_at.isoformat() not in {metadata.request_started_at.isoformat(), metadata.response_at.isoformat()}
    assert "cookie" not in {key.casefold() for key in captured["headers"]}
    assert "authorization" not in {key.casefold() for key in captured["headers"]}
    assert "3073166" in captured["url"]


def test_raw_page_content_names_and_prose_never_enter_public_artifact(tmp_path: Path):
    secret_name = "RAW_PLAYER_NAME_SHOULD_NOT_APPEAR"
    secret_prose = "RAW_MEDIA_ANALYSIS_PROSE_SHOULD_NOT_APPEAR"
    cohort = _write_cohort(tmp_path, _source_row())
    client = FakeClient(
        bodies={
            "market_context": _market_html(),
            "analysis_page": f"<h2>伤停</h2><div>{secret_name} {secret_prose}</div>".encode(),
            "time_page": f"<h2>首发阵容</h2><li>{secret_name}</li>".encode(),
        }
    )

    result = run_bounded_audit(cohort, as_of=AS_OF, client=client)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

    assert secret_name not in serialized
    assert secret_prose not in serialized
    assert result["public_raw_content_persisted"] is False
    assert result["source_prose_or_names_persisted"] is False


def test_public_contract_keeps_same_source_research_out_of_production(tmp_path: Path):
    result = run_bounded_audit(
        _write_cohort(tmp_path, _source_row()),
        as_of=AS_OF,
        client=FakeClient({"market_context": _market_html()}),
    )

    assert set(result["decision"] for _ in [0]) <= {"SAME_SOURCE_EVIDENCE_CAPABILITY_READY", "COVERAGE_TOO_THIN", "CHRONOLOGY_NOT_PROVABLE", "ACCESS_OR_RIGHTS_BOUNDARY_BLOCKED", "FAIL_CLOSED"}
    assert set(FIELD_NAMES).issubset(result["field_aggregate"])
    assert result["source_is_production"] is False
    assert result["model_change_allowed"] is False
    assert result["champion_change_allowed"] is False
    assert result["serving_change_allowed"] is False
    assert result["ui_change_allowed"] is False
    assert set(ALLOWED_STATES) == {"PRESENT", "SECTION_PRESENT_EMPTY", "ABSENT", "ACCESS_GATED", "PARSE_UNCERTAIN", "CONFLICT"}


def test_network_client_does_not_persist_body_or_authentication():
    class Response:
        status = 200
        headers = {"last-modified": "Wed, 10 Sep 2026 04:00:00 GMT"}

        def read(self) -> bytes:
            return b"<html>public</html>"

        def close(self) -> None:
            pass

    client = NowscorePublicClient(opener=lambda request, timeout: Response(), max_requests=1)
    metadata, body = client.fetch("market_context", "https://live.nowscore.com/odds/match/3073166.htm")

    assert body == b"<html>public</html>"
    assert metadata.source_update_at == datetime(2026, 9, 10, 4, 0, tzinfo=UTC)
    assert metadata.content_sha256 == "a" * 64 or len(metadata.content_sha256 or "") == 64

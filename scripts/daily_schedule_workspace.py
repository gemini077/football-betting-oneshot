#!/usr/bin/env python3
"""Refresh the public Nowscore JC universe and rebuild the unified workspace."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from match_workspace import ROOT, build
from nowscore_markets import (
    fetch_nowscore_jc_schedule,
    fetch_schedule_bundle as fetch_nowscore_schedule,
    prebind_match,
)

try:
    from prediction_universe import update_prediction_universe
except ImportError:  # package imports used by tests
    from scripts.prediction_universe import update_prediction_universe

try:
    from base_prediction_jobs import sync_base_prediction_jobs
except ImportError:  # package imports used by tests
    from scripts.base_prediction_jobs import sync_base_prediction_jobs


NOT_YET_PUBLISHED = "NOT_YET_PUBLISHED"


def _kickoff(row: dict) -> str:
    match_date = str(row.get("matchDate") or row.get("businessDate") or "")[:10]
    match_time = str(row.get("matchTime") or "")[:5]
    return f"{match_date}T{match_time}:00+08:00" if match_date and match_time else ""


def _payload_is_successful(payload: dict) -> bool:
    """Accept both provider payloads and already-normalized READY snapshots."""
    if payload.get("success") is True:
        return True
    rows = payload.get("matches") or payload.get("fixtures")
    return bool(rows) and str(payload.get("status") or "").upper() in {
        "READY", "OK",
    }


def _payload_is_not_yet_published(payload: dict) -> bool:
    contract = payload.get("business_date_contract")
    return (
        payload.get("source") == "nowscore_public_jc"
        and payload.get("success") is False
        and payload.get("status") == NOT_YET_PUBLISHED
        and payload.get("matches") == []
        and isinstance(contract, dict)
        and contract.get("publication_status") == NOT_YET_PUBLISHED
    )


def _source_state(payload: dict) -> dict:
    return {
        "business_date": payload.get("business_date") or payload.get("date"),
        "source": payload.get("source"),
        "status": payload.get("status"),
        "success": payload.get("success") is True,
        "fetched_at": payload.get("fetched_at") or payload.get("fetch_time"),
        "error": payload.get("error"),
        "business_date_contract": payload.get("business_date_contract"),
        "diagnostics": payload.get("diagnostics", {}),
    }


def _required_nowscore_dates(payloads: list[dict]) -> list[str]:
    dates: set[str] = set()
    for payload in payloads:
        for row in payload.get("matches") or []:
            match_date = str(row.get("matchDate") or "").strip()
            if not match_date:
                kickoff = str(row.get("kickoff_local") or "").strip()
                match_date = kickoff[:10] if kickoff else ""
            if match_date:
                dates.add(match_date)
    return sorted(dates)


def _nowscore_schedule_payload(business_date: str, fetched: dict) -> dict:
    """Map verified Nowscore JC rows to the canonical schedule contract."""
    fetched_at = str(
        fetched.get("fetched_at")
        or fetched.get("fetch_time")
        or datetime.now().astimezone().isoformat()
    )
    source_rows = list(fetched.get("matches") or []) if isinstance(fetched, dict) else []
    matches: list[dict] = []
    invalid_rows = 0
    sales_url = str(
        fetched.get("business_date_source_url") or fetched.get("url") or ""
    )
    contract = fetched.get("business_date_contract") if isinstance(fetched, dict) else None
    contract_valid = bool(
        isinstance(contract, dict)
        and contract.get("valid") is True
        and contract.get("surface") == "nowscore_public_jc_sales"
        and contract.get("date_anchor") == "SelDate + niDate header date"
        and contract.get("sales_window") == "11:00--次日11:00"
        and contract.get("selected_date") == business_date
        and contract.get("requested_date") == business_date
        and fetched.get("source") == "nowscore_public_jc"
        and fetched.get("primary_source") == "nowscore_public_jc_sales"
        and fetched.get("business_date_source") == "nowscore_public_jc_sales"
        and fetched.get("business_date_source_url") == sales_url
        and sales_url == str(fetched.get("url") or "")
    )
    for source_row in source_rows:
        if not isinstance(source_row, dict):
            invalid_rows += 1
            continue
        nowscore_id = source_row.get("nowscore_id")
        kickoff = str(source_row.get("kickoff_local") or "")
        date_provenance = source_row.get("date_provenance") or {}
        try:
            datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            valid_kickoff = bool(kickoff)
        except ValueError:
            valid_kickoff = False
        if (
            nowscore_id in (None, "")
            or not valid_kickoff
            or source_row.get("business_date") != business_date
            or source_row.get("business_date_source") != "nowscore_public_jc_sales"
            or source_row.get("business_date_source_url") != sales_url
            or source_row.get("jc_membership") != "VERIFIED"
            or source_row.get("jc_membership_source") != "nowscore_public_jc_sales"
            or source_row.get("match_number") in (None, "")
            or source_row.get("sales_row_id") in (None, "")
            or source_row.get("source_surface") != sales_url
            or source_row.get("source_url") != sales_url
            or date_provenance.get("business_date") != business_date
            or date_provenance.get("business_date_source")
            != "nowscore_public_jc_sales"
            or date_provenance.get("sales_window") != "11:00--次日11:00"
        ):
            invalid_rows += 1
            continue
        row = {
            "matchId": str(nowscore_id),
            "nowscoreId": int(nowscore_id),
            "nowscore_id": int(nowscore_id),
            "homeTeam": source_row.get("home_team"),
            "awayTeam": source_row.get("away_team"),
            "homeTeamEn": source_row.get("home_team_en"),
            "awayTeamEn": source_row.get("away_team_en"),
            "businessDate": business_date,
            "matchDate": kickoff[:10],
            "matchTime": kickoff[11:16],
            "jc_membership": "VERIFIED",
            "jc_membership_source": "nowscore_public_jc_sales",
            "jc_membership_evidence": source_row.get("jc_membership_evidence"),
            "source_surface": source_row.get("source_surface"),
            "source_url": source_row.get("source_url"),
            "business_date_source": source_row.get("business_date_source"),
            "business_date_source_url": source_row.get("business_date_source_url"),
            "fetched_at": source_row.get("fetched_at") or fetched_at,
            "date_provenance": source_row.get("date_provenance"),
            "schedule_source_date": source_row.get("schedule_source_date"),
            "schedule_source_date_format": source_row.get("schedule_source_date_format"),
        }
        if source_row.get("match_number") not in (None, ""):
            row["matchNum"] = source_row["match_number"]
        if source_row.get("match_number_source") not in (None, ""):
            row["match_number_source"] = source_row["match_number_source"]
        if source_row.get("sales_row_id") not in (None, ""):
            row["sales_row_id"] = source_row["sales_row_id"]
        if source_row.get("cansale") not in (None, ""):
            row["cansale"] = source_row["cansale"]
        if source_row.get("a32_corroboration") not in (None, ""):
            row["a32_corroboration"] = source_row["a32_corroboration"]
        if source_row.get("a32_corroboration_status") not in (None, ""):
            row["a32_corroboration_status"] = source_row["a32_corroboration_status"]
        if source_row.get("league") not in (None, ""):
            row["league"] = source_row["league"]
        matches.append(row)

    source_success = fetched.get("success") is True if isinstance(fetched, dict) else False
    duplicate_free = all(
        int(fetched.get(key) or 0) == 0
        for key in (
            "duplicate_nowscore_id_count",
            "duplicate_sales_row_id_count",
            "duplicate_match_number_count",
            "ambiguous_nowscore_id_count",
        )
    ) if isinstance(fetched, dict) else False
    success = (
        source_success
        and contract_valid
        and duplicate_free
        and bool(matches)
        and invalid_rows == 0
    )
    return {
        "source": "nowscore_public_jc",
        "primary_source": "nowscore_public_jc_sales",
        "schedule_scope": "jc",
        "url": fetched.get("url"),
        "source_surface": fetched.get("source_surface"),
        "business_date_source": fetched.get("business_date_source"),
        "business_date_source_url": fetched.get("business_date_source_url"),
        "backing_data_url": fetched.get("backing_data_url"),
        "surface": fetched.get("surface"),
        "date": business_date,
        "business_date": business_date,
        "fetch_time": fetched_at,
        "fetched_at": fetched_at,
        "success": success,
        "status": "OK" if success else str(fetched.get("status") or "CONTRACT_REJECTED"),
        "publication_status": fetched.get("publication_status"),
        "error": "INVALID_NOWSCORE_JC_ROW" if invalid_rows else fetched.get("error"),
        "matches": matches if success else [],
        "jc_contract": fetched.get("jc_contract"),
        "business_date_contract": contract,
        "jc_flagged_row_count": fetched.get("jc_flagged_row_count", 0),
        "duplicate_nowscore_id_count": fetched.get("duplicate_nowscore_id_count", 0),
        "ambiguous_nowscore_id_count": fetched.get("ambiguous_nowscore_id_count", 0),
        "diagnostics": fetched.get("diagnostics", {}),
    }


def _payload_nowscore_schedule_rows(payloads: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for payload in payloads:
        if payload.get("source") != "nowscore_public_jc":
            continue
        for row in payload.get("matches") or []:
            nowscore_id = row.get("nowscoreId") or row.get("nowscore_id")
            if nowscore_id in (None, ""):
                continue
            rows.append({
                "nowscore_id": int(nowscore_id),
                "home_team": row.get("homeTeam") or row.get("home_team") or "",
                "away_team": row.get("awayTeam") or row.get("away_team") or "",
                "home_team_en": row.get("homeTeamEn") or row.get("home_team_en") or "",
                "away_team_en": row.get("awayTeamEn") or row.get("away_team_en") or "",
                "kickoff_local": _kickoff(row),
            })
    return rows


def attach_nowscore_bindings(payloads: list[dict]) -> dict:
    """Resolve every fixture once during schedule intake, before analysis is requested."""
    required_dates = _required_nowscore_dates(payloads)
    public_jc_rows = _payload_nowscore_schedule_rows(payloads)
    has_public_jc_payload = any(
        payload.get("source") == "nowscore_public_jc" for payload in payloads
    )
    if has_public_jc_payload:
        # Current-universe binding is self-contained: the same verified
        # Nowscore JC rows that created the payload are the identity input.
        provider_schedule = public_jc_rows
        fetched = {
            "status": "OK_PUBLIC_JC" if public_jc_rows else "NO_PUBLIC_JC_ROWS",
            "schedule_count": len(provider_schedule),
            "source": "nowscore_public_jc",
        }
        schedule_status = fetched["status"]
    else:
        try:
            fetched = fetch_nowscore_schedule(required_dates)
        except Exception as error:
            return {
                "status": "FETCH_ERROR",
                "error": f"{type(error).__name__}: {error}",
                "bound": 0,
                "required_dates": required_dates,
            }
        if isinstance(fetched, dict):
            provider_schedule = list(fetched.get("matches") or [])
            schedule_status = str(fetched.get("status") or "OK")
        else:
            # Keep compatibility with callers/tests that provide the legacy list API.
            provider_schedule = list(fetched or [])
            fetched = {"status": "OK", "schedule_count": len(provider_schedule)}
            schedule_status = "OK"
    bound = ambiguous = missing = 0
    for payload in payloads:
        for row in payload.get("matches") or []:
            resolved = prebind_match(
                row.get("homeTeam") or "",
                row.get("awayTeam") or "",
                _kickoff(row),
                provider_schedule,
                fixture=row,
            )
            status = str(resolved.get("status") or "")
            row["nowscoreMatchStatus"] = status
            row["nowscoreMatchConfidence"] = resolved.get("match_confidence")
            if resolved.get("nowscore_id"):
                row["nowscoreId"] = int(resolved["nowscore_id"])
                row["nowscoreProviderHome"] = resolved.get("home_team")
                row["nowscoreProviderAway"] = resolved.get("away_team")
                bound += 1
            elif status in {"AMBIGUOUS_MATCH", "LOW_CONFIDENCE_MATCH"}:
                ambiguous += 1
            else:
                missing += 1
    result = {
        "status": schedule_status,
        "schedule_count": len(provider_schedule),
        "bound": bound,
        "ambiguous": ambiguous,
        "missing": missing,
        "required_dates": required_dates,
    }
    for key in ("future_surface", "provenance", "errors", "source"):
        if key in fetched:
            result[key] = fetched[key]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="每日体彩赛程更新（不自动分析）")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--fetch-only", action="store_true", help="只刷新赛程数据，由后续步骤统一重建页面")
    args = parser.parse_args()
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "data" / "schedule_updates" / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    base_date = date.fromisoformat(args.date)
    payloads = []
    schedule_paths = []
    for offset in (0, 1):
        business_date = (base_date + timedelta(days=offset)).isoformat()
        fetched = fetch_nowscore_jc_schedule(business_date, now=now)
        payload = _nowscore_schedule_payload(business_date, fetched)
        payloads.append(payload)
    nowscore_binding = attach_nowscore_bindings(payloads)
    universe_snapshots = []
    base_job_snapshots = []
    for offset, payload in enumerate(payloads):
        business_date = (base_date + timedelta(days=offset)).isoformat()
        payload["nowscore_binding"] = nowscore_binding
        universe = update_prediction_universe(business_date, payload)
        if payload.get("status") == NOT_YET_PUBLISHED:
            base_jobs = {
                "status": "SKIPPED",
                "reason": "UNIVERSE_NOT_YET_PUBLISHED",
                "fixture_count": 0,
                "job_count": 0,
                "pending_count": 0,
                "missed_prematch_count": 0,
            }
        else:
            base_jobs = sync_base_prediction_jobs(business_date)
        universe_snapshots.append({
            "date": business_date,
            "path": str(ROOT / "data" / "prediction_universe" / f"{business_date}.json"),
            "status": universe.get("status"),
            "source": universe.get("source"),
            "fetched_at": universe.get("fetched_at"),
            "source_fixture_count": universe.get("source_fixture_count", 0),
            "fixture_count": universe.get("fixture_count", 0),
            "excluded_cross_date_count": universe.get("excluded_cross_date_count", 0),
        })
        base_job_snapshots.append({
            "date": business_date,
            "status": base_jobs.get("status"),
            "reason": base_jobs.get("reason"),
            "fixture_count": base_jobs.get("fixture_count", 0),
            "job_count": base_jobs.get("job_count", 0),
            "pending_count": base_jobs.get("pending_count", 0),
            "missed_prematch_count": base_jobs.get("missed_prematch_count", 0),
            "coverage_registry_digest": base_jobs.get("coverage_registry_digest"),
            "coverage_summary": base_jobs.get("coverage_summary", {}),
        })
        schedule_path = output_dir / f"{stamp}_nowscore_jc_{business_date}.json"
        schedule_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        schedule_paths.append(schedule_path)
    match_ids = {
        str(row.get("matchId") or "|".join(str(row.get(key) or "") for key in ("matchNum", "homeTeam", "awayTeam")))
        for payload in payloads
        for row in payload.get("matches") or []
    }
    successful_payloads = [payload for payload in payloads if _payload_is_successful(payload)]
    business_dates = [
        str(payload.get("business_date") or payload.get("date") or "")
        for payload in payloads
    ]
    source_states = [_source_state(payload) for payload in payloads]
    if payloads and not successful_payloads and all(
        _payload_is_not_yet_published(payload) for payload in payloads
    ):
        print(json.dumps({
            "date": args.date,
            "status": NOT_YET_PUBLISHED,
            "business_dates": business_dates,
            "source_states": source_states,
            "schedules": [str(path) for path in schedule_paths],
            "match_count": 0,
            "refresh_status": "not_yet_published",
            "workspace_rebuilt": False,
            "automatic_analysis": False,
            "automatic_betting": False,
            "lock_state_changed": False,
            "prediction_universe": universe_snapshots,
            "base_prediction_jobs": base_job_snapshots,
        }, ensure_ascii=False, indent=2))
        return 0
    # 抓取全部失败时保留旧工作台。失败诊断文件可以落盘，但绝不能用新的页面
    # 生成时间伪装成赛程已更新。
    if not successful_payloads:
        print(json.dumps({
            "date": args.date,
            "business_dates": business_dates,
            "source_states": source_states,
            "schedules": [str(path) for path in schedule_paths],
            "match_count": 0,
            "refresh_status": "failed_kept_previous_workspace",
            "workspace_rebuilt": False,
            "automatic_analysis": False,
            "automatic_betting": False,
            "lock_state_changed": False,
            "prediction_universe": universe_snapshots,
            "base_prediction_jobs": base_job_snapshots,
        }, ensure_ascii=False, indent=2))
        return 1

    index = latest = ROOT / "data" / "match_workspace" / "latest.html"
    if not args.fetch_only:
        index, latest = build(args.date)
    print(json.dumps({
        "date": args.date, "business_dates": business_dates,
        "source_states": source_states,
        "schedule": str(schedule_paths[0]),
        "schedules": [str(path) for path in schedule_paths], "match_count": len(match_ids),
        "workspace": str(latest), "workspace_snapshot": str(index), "latest": str(latest),
        "user_entry": str(latest), "automatic_analysis": False,
        "automatic_betting": False, "lock_state_changed": False,
        "refresh_status": "success" if len(successful_payloads) == len(payloads) else "partial_success",
        "nowscore_binding": nowscore_binding,
        "prediction_universe": universe_snapshots,
        "base_prediction_jobs": base_job_snapshots,
        "workspace_rebuilt": not args.fetch_only,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

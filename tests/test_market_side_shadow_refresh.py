import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow_refresh import refresh_shadow  # noqa: E402


PAIR_SOURCE = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs" / "MS-SHADOW-PAIR-c2419d933d267e88530442231cace2e5.json"
RESULT_SOURCE = ROOT / "data" / "postmatch_automation" / "results" / "FBOS-202608160930-c61a4b640b.json"


def _copy_smoke_inputs(tmp_path):
    pair_root = tmp_path / "pairs"
    result_root = tmp_path / "results"
    pair_root.mkdir()
    result_root.mkdir()
    shutil.copyfile(PAIR_SOURCE, pair_root / PAIR_SOURCE.name)
    shutil.copyfile(RESULT_SOURCE, result_root / RESULT_SOURCE.name)
    return pair_root, result_root


def test_refresh_discovers_verified_result_and_writes_latest(tmp_path):
    pair_root, result_root = _copy_smoke_inputs(tmp_path)
    output = tmp_path / "latest.json"

    summary = refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=output,
        refreshed_at="2026-08-30T12:00:00+08:00",
    )

    assert summary["status"] == "SUCCESS"
    assert summary["market_side_shadow_status"] == "REFRESHED"
    assert summary["paired_count"] == 1
    assert summary["challenger_abstain_count"] == 0
    assert summary["promotion_eligible_pairs"] == 0
    assert summary["excluded_non_promotion_pair_count"] == 1
    assert summary["verified_paired_count"] == 0
    assert summary["total_pair_version_rows"] == 1
    assert summary["promotion_eligible_pair_version_rows"] == 0
    assert summary["verified_pair_version_rows"] == 0
    assert summary["promotion_eligible_unique_matches"] == 0
    assert summary["verified_unique_matches"] == 0
    assert summary["unmatched_pair_count"] == 0
    assert summary["checkpoint_status"] == "NOT_REACHED"
    assert summary["early_stop_status"] == "NOT_TRIGGERED"
    latest = json.loads(output.read_text(encoding="utf-8"))
    assert latest["counts"]["pairs"] == 1
    assert latest["counts"]["paired"] == 1
    assert latest["counts"]["promotion_eligible_pairs"] == 0
    assert latest["counts"]["excluded_non_promotion_pair_count"] == 1
    assert latest["evaluation"]["verified_paired_count"] == 0
    assert latest["counts"]["total_pair_version_rows"] == 1
    assert latest["counts"]["verified_unique_matches"] == 0
    assert latest["checkpoint"]["verified_unique_matches"] == 0
    assert latest["refresh"]["matched_pair_count"] == 1
    assert latest["checkpoint"]["auto_promote"] is False
    assert latest["checkpoint"]["status"] == "NOT_REACHED"
    assert latest["evaluation"]["candidates"]["challenger"]["sample_count"] == 0
    assert "actual_result" not in latest["pairs"][0]


def test_refresh_uses_identity_safe_final_scope_only(tmp_path):
    pair_root, result_root = _copy_smoke_inputs(tmp_path)
    result_path = result_root / RESULT_SOURCE.name
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["match_key"] = "OTHER-MATCH"
    result["scope"] = "extra_time"
    result["status"] = "result_pending"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    summary = refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=tmp_path / "latest.json",
        refreshed_at="2026-08-30T12:00:00+08:00",
    )

    assert summary["verified_paired_count"] == 0
    assert summary["result_files_rejected"] == 1
    assert summary["checkpoint_status"] == "NOT_REACHED"


def test_refresh_is_repeatable_and_replaces_latest_atomically(tmp_path):
    pair_root, result_root = _copy_smoke_inputs(tmp_path)
    output = tmp_path / "latest.json"
    first = refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=output,
        refreshed_at="2026-08-30T12:00:00+08:00",
    )
    second = refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=output,
        refreshed_at="2026-08-30T12:01:00+08:00",
    )

    assert first["latest_status"] == "CREATED"
    assert second["latest_status"] == "REPLACED"
    assert json.loads(output.read_text(encoding="utf-8"))["refresh"]["refreshed_at"] == "2026-08-30T12:01:00+08:00"

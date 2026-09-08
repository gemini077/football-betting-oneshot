import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow import build_shadow_document, load_persisted_pairs  # noqa: E402
from market_side_shadow_refresh import (  # noqa: E402
    CURRENT_VIEW_SCHEMA_VERSION,
    PAIR_INDEX_SCHEMA_VERSION,
    build_identity_safe_result_map,
    build_compact_shadow_view,
    discover_verified_results,
    load_indexed_pairs,
    pair_set_digest,
    refresh_shadow,
)


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
    assert "pairs" not in latest
    indexed_pairs = load_indexed_pairs(latest["pair_index"], pair_root)
    assert indexed_pairs[0]["pair_status"] == "PAIRED"
    assert "actual_result" not in indexed_pairs[0]


def test_refresh_writes_compact_pair_index_without_changing_evaluation(tmp_path):
    pair_root, result_root = _copy_smoke_inputs(tmp_path)
    output = tmp_path / "latest.json"
    pairs = load_persisted_pairs(pair_root)
    catalog, discovery = discover_verified_results(result_root)
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    expected = build_shadow_document(
        pairs,
        result_map,
        source_manifest={
            "result_source": "data/postmatch_automation/results/*.json",
            "result_files_scanned": discovery["result_files_scanned"],
            "result_files_accepted": discovery["result_files_accepted"],
            "matched_pair_count": matching["matched_pair_count"],
        },
    )

    summary = refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=output,
        refreshed_at="2026-08-30T12:00:00+08:00",
    )

    latest = json.loads(output.read_text(encoding="utf-8"))
    assert summary["status"] == "SUCCESS"
    assert latest["schema_version"] == CURRENT_VIEW_SCHEMA_VERSION
    assert "pairs" not in latest
    assert latest["counts"] == expected["counts"]
    assert latest["checkpoint"] == expected["checkpoint"]
    assert latest["evaluation"] == expected["evaluation"]
    assert latest["pair_index"]["schema_version"] == PAIR_INDEX_SCHEMA_VERSION
    assert latest["pair_index"]["root"] == "pairs"
    assert latest["pair_index"]["pair_count"] == len(pairs)
    assert latest["pair_index"]["pair_set_digest"] == pair_set_digest(pairs)
    assert "entries" not in latest["pair_index"]
    assert load_indexed_pairs(latest["pair_index"], pair_root) == pairs
    assert output.stat().st_size <= 1_000_000


def _synthetic_pair(index):
    return {
        "pair_id": f"MS-SHADOW-PAIR-{index:08d}",
        "pair_digest": f"{index:064x}",
        "match_id": f"MATCH-{index:08d}",
        "match_key": f"MATCH-{index:08d}",
        "pair_status": "PAIRED",
        "promotion_eligible": True,
        "source_cutoff": "2026-08-30T00:00:00+08:00",
        "freeze_created_at": "2026-08-30T00:00:00+08:00",
    }


def test_pair_index_high_water_shape_stays_bounded_with_thousands_of_pairs():
    small_pairs = [_synthetic_pair(index) for index in range(10)]
    high_water_pairs = [_synthetic_pair(index) for index in range(5000)]
    small = build_compact_shadow_view({"pairs": small_pairs, "counts": {"pairs": 0}}, small_pairs)
    high_water = build_compact_shadow_view(
        {"pairs": high_water_pairs, "counts": {"pairs": 0}},
        high_water_pairs,
    )

    small_size = len(json.dumps(small, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    high_water_size = len(
        json.dumps(high_water, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    assert set(high_water["pair_index"]) == {
        "schema_version",
        "root",
        "pair_count",
        "pair_set_digest",
    }
    assert high_water["pair_index"]["pair_count"] == 5000
    assert len(high_water["pair_index"]["pair_set_digest"]) == 64
    assert high_water_size < 100_000
    assert high_water_size - small_size < 128
    assert pair_set_digest(high_water_pairs) == pair_set_digest(reversed(high_water_pairs))


@pytest.mark.parametrize("mutation", ["add", "remove", "content"])
def test_indexed_pair_set_mutations_fail_closed(tmp_path, mutation):
    pair_root, result_root = _copy_smoke_inputs(tmp_path)
    output = tmp_path / "latest.json"
    refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=output,
        refreshed_at="2026-08-30T12:00:00+08:00",
    )
    latest = json.loads(output.read_text(encoding="utf-8"))
    pair_path = next(pair_root.glob("MS-SHADOW-PAIR-*.json"))

    if mutation == "add":
        extra = json.loads(pair_path.read_text(encoding="utf-8"))
        extra["pair_id"] = "MS-SHADOW-PAIR-extra-mutated"
        (pair_root / "MS-SHADOW-PAIR-extra-mutated.json").write_text(
            json.dumps(extra),
            encoding="utf-8",
        )
    elif mutation == "remove":
        pair_path.unlink()
    else:
        changed = json.loads(pair_path.read_text(encoding="utf-8"))
        changed["match_key"] = "MUTATED-MATCH-KEY"
        pair_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError):
        load_indexed_pairs(latest["pair_index"], pair_root)


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


def test_refresh_rejects_exact_key_with_kickoff_mismatch(tmp_path):
    pair_root, result_root = _copy_smoke_inputs(tmp_path)
    result_path = result_root / RESULT_SOURCE.name
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["kickoff_local"] = "2026-08-16T10:30:00+08:00"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    summary = refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=tmp_path / "latest.json",
        refreshed_at="2026-08-30T12:00:00+08:00",
    )

    assert summary["result_identity_mismatches"] == 1
    assert summary["verified_paired_count"] == 0
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["refresh"]["matched_pair_count"] == 0


def test_refresh_does_not_mutate_pair_or_result_inputs(tmp_path):
    pair_root, result_root = _copy_smoke_inputs(tmp_path)
    pair_path = next(pair_root.glob("*.json"))
    result_path = next(result_root.glob("*.json"))
    before = {
        "pair": pair_path.read_bytes(),
        "result": result_path.read_bytes(),
    }

    refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=tmp_path / "latest.json",
        refreshed_at="2026-08-30T12:00:00+08:00",
    )

    assert pair_path.read_bytes() == before["pair"]
    assert result_path.read_bytes() == before["result"]


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

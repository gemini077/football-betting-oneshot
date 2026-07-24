import json

from checkpoint_features import build_checkpoint_features


def _snapshot(home, draw, away, handicap, total, fetched_at):
    return {
        "fetched_at": fetched_at,
        "ouzhi": {"bookmakers": [{"spf_current": {"home": home, "draw": draw, "away": away}}]},
        "yazhi": {"companies": [{"current_handicap": handicap}]},
        "daxiao": {"companies": [{"current_line": total}]},
    }


def test_checkpoint_features_capture_direction_and_line_movement(tmp_path):
    canonical = "fixture-1"
    checkpoint_dir = tmp_path / "data" / "market_history" / "checkpoints" / canonical
    source_dir = tmp_path / "data" / "source_cache"
    manifest_dir = tmp_path / "data" / "manifests"
    checkpoint_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)
    first = source_dir / "first.json"
    second = source_dir / "second.json"
    first.write_text(json.dumps(_snapshot(1.70, 3.8, 5.0, -0.75, 2.5, "2026-07-24T01:00:00Z")), encoding="utf-8")
    second.write_text(json.dumps(_snapshot(4.8, 3.7, 1.72, 0.75, 3.0, "2026-07-24T02:00:00Z")), encoding="utf-8")
    for index, source in enumerate((first, second), start=1):
        manifest = manifest_dir / f"{index}.json"
        manifest.write_text(json.dumps({"sources": {"nowscore": {"file": str(source)}}}), encoding="utf-8")
        (checkpoint_dir / f"{index}.json").write_text(json.dumps({
            "captured_at": f"2026-07-24T0{index}:00:00Z",
            "stage": f"T-{index}",
            "fetch_manifest": str(manifest),
        }), encoding="utf-8")

    result = build_checkpoint_features(canonical, root=tmp_path)

    assert result["snapshot_count"] == 2
    assert result["leader_reversals"] == 1
    assert result["asian_handicap_delta"] == 1.5
    assert result["total_line_delta"] == 0.5
    assert result["probability_delta"]["home"] < 0
    assert result["probability_delta"]["away"] > 0

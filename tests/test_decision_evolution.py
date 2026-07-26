import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decision_evolution import attach_evolution, describe_change  # noqa: E402


def test_subthreshold_probability_move_is_visible_as_micro_adjustment():
    previous = {
        "probabilities": {"home": 0.50, "draw": 0.28, "away": 0.22},
        "primary_dimension": "主胜",
        "unique_score": "1-0",
    }
    current = {
        "probabilities": {"home": 0.506, "draw": 0.277, "away": 0.217},
        "primary_dimension": "主胜",
        "unique_score": "1-0",
    }

    change = describe_change(previous, current)

    assert change["kind"] == "micro_adjustment"
    assert change["changed"] is False
    assert "+0.6" in change["headline"] or "上调0.6" in change["headline"]
    assert change["probability_delta"]["home"] == 0.006


def test_canonical_timeline_can_inherit_provider_initial_record(tmp_path):
    provider_root = tmp_path / "provider-1"
    provider_root.mkdir()
    provider_record = {
        "match_id": "provider-1",
        "captured_at": "2026-07-26T10:00:00+08:00",
        "internal_stage": "INITIAL",
        "decision": {
            "probabilities": {"home": 0.50, "draw": 0.28, "away": 0.22},
            "primary_dimension": "主胜",
            "unique_score": "1-0",
        },
        "change": {"headline": "初始判断", "summary": "初始", "changed": True},
    }
    (provider_root / "decision_timeline.jsonl").write_text(
        json.dumps(provider_record, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    analysis = {
        "match": {"provider_match_id": "provider-1"},
        "model": {"probabilities": {"home": 0.506, "draw": 0.277, "away": 0.217}},
        "decisions": {"unique_primary_dimension": "主胜", "unique_score": "1-0"},
    }

    updated, _ = attach_evolution(
        analysis,
        "FBOS-202607261200-test",
        {"stage": "T-15", "captured_at": "2026-07-26T11:45:00+08:00"},
        root=tmp_path,
    )

    assert len(updated["decision_evolution"]["history"]) == 2
    assert updated["decision_evolution"]["latest"]["kind"] == "micro_adjustment"

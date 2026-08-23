import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_governance import canonical_json, freeze_prediction, prediction_content_hash  # noqa: E402
import prospective_challenger_runner as runner  # noqa: E402
from prospective_challenger_runner import (  # noqa: E402
    CHALLENGER_ID,
    MODEL_CORE_VERSION,
    build_challenger_record,
    filter_history_at_cutoff,
    load_frozen_challenger_spec,
)
from prospective_pair_capture import capture_forward_pairs  # noqa: E402


TZ = timezone(timedelta(hours=8))
CUTOFF = "2026-08-12T10:00:00+08:00"
KICKOFF = "2026-08-13T18:00:00+08:00"


def _snapshot_document():
    projection = {"request": {"match_id": "500-TEST"}, "selected_workspace_match": {"id": "500-TEST"}}
    digest = __import__("hashlib").sha256(canonical_json(projection).encode("utf-8")).hexdigest()
    metadata = {
        "contract_version": "deterministic_model_input.v1",
        "snapshot_contract_version": "governance_snapshot.v2",
        "snapshot_id": f"FBOS-SNAPSHOT-{digest[:24]}",
        "manifest_ref": "tests/fixtures/challenger-manifest.json",
        "source_refs": [],
        "source_hashes": {},
        "captured_at": CUTOFF,
        "prediction_created_at": "2026-08-12T10:01:00+08:00",
        "model_input_as_of_at": CUTOFF,
        "source_cutoff_at": CUTOFF,
        "market_snapshot_at": CUTOFF,
        "odds_snapshot_at": CUTOFF,
        "source_time_range": {"source_timestamps": {}},
        "canonical_model_input_sha256": digest,
        "canonical_input_sha256": digest,
        "snapshot_ref": f"data/model_governance/input_snapshots/{digest}.json",
    }
    return {**metadata, "input": projection}


def _champion(snapshot):
    return {
        "prediction_id": "FBOS-PRED-SYNTHETIC-CHAMPION",
        "prediction_sha256": "champion-sha",
        "prediction_status": "formal",
        "model_role": "champion",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "model_core_version": "recent_form_market_calibrated_poisson_v2",
        "model_source_fingerprint": "champion-source",
        "model_run_fingerprint": "champion-run",
        "prediction_variant": "model_only",
        "manual_override": False,
        "input_sha256": "champion-input",
        "critical_missing_fields": [],
        "missing_critical_fields": [],
        "match_key": "FBOS-202608131800-synthetic",
        "match_id": "500-TEST",
        "match_identity": {
            "match_key": "FBOS-202608131800-synthetic",
            "match_id": "500-TEST",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_at": KICKOFF,
        },
        "canonical_team_identity": {
            "competition_id": "competition:test",
            "season_id": "2026",
            "home_team_id": "team:test:home",
            "away_team_id": "team:test:away",
        },
        "business_date": "2026-08-13",
        "kickoff_at": KICKOFF,
        "source_cutoff_at": CUTOFF,
        "prediction_created_at": "2026-08-12T10:01:00+08:00",
        "freeze_created_at": "2026-08-12T10:02:00+08:00",
        "input_snapshot": {key: value for key, value in snapshot.items() if key != "input"},
        "model_input_snapshot_ref": snapshot["snapshot_ref"],
        "data_grade": "B",
    }


def _history_row(index, *, info_at=CUTOFF):
    day = 1 + index
    if index % 2:
        home, away = "team:test:away", f"team:test:other{index}"
    else:
        home, away = "team:test:home", f"team:test:other{index}"
    return {
        "canonical_match_id": f"match:test:{index}",
        "competition_id": "competition:test",
        "season_id": "2026",
        "home_team_id": home,
        "away_team_id": away,
        "kickoff_at": f"2026-08-{day:02d}T10:00:00Z",
        "home_goals": index % 3,
        "away_goals": (index + 1) % 2,
        "eligible_for_team_strength": True,
        "duplicate_status": "unique",
        "source_conflict": False,
        "entity_type": "club",
        "source_as_of_at": info_at,
        "captured_at": info_at,
    }


def test_selected_spec_is_loaded_from_frozen_research_artifact():
    spec, provenance = load_frozen_challenger_spec()

    assert spec.spec_id == "opponent:fixed-point:prior20"
    assert spec.regularization == 20
    assert provenance["selected_spec_id"] == spec.spec_id
    assert provenance["fresh_heldout_available"] is False
    assert provenance["historical_validation_reused"] is True


def test_history_filter_excludes_information_after_champion_cutoff():
    legal = _history_row(1)
    late_information = _history_row(2, info_at="2026-08-12T10:00:01+08:00")
    late_kickoff = _history_row(3)
    late_kickoff["kickoff_at"] = "2026-08-12T10:30:00+08:00"

    filtered = filter_history_at_cutoff(
        [legal, late_information, late_kickoff],
        source_cutoff_at=CUTOFF,
        target_kickoff_at=KICKOFF,
    )

    assert [row["canonical_match_id"] for row in filtered] == ["match:test:1"]


def test_challenger_record_is_frozen_shadow_with_same_match_and_cutoff():
    snapshot = _snapshot_document()
    record = build_challenger_record(
        _champion(snapshot),
        history_records=[_history_row(index) for index in range(1, 11)],
        input_snapshot_document=snapshot,
        now=datetime(2026, 8, 12, 12, 0, tzinfo=TZ),
        historical_dataset_digest="history-sha",
        historical_dataset_path="historical_results.duckdb",
    )

    assert record["model_role"] == "challenger"
    assert record["challenger_id"] == CHALLENGER_ID
    assert record["model_core_version"] == MODEL_CORE_VERSION
    assert record["prediction_status"] == "frozen"
    assert record["formal_eligible"] is False
    assert record["model_formal_eligible"] is False
    assert record["match_key"] == "FBOS-202608131800-synthetic"
    assert record["source_cutoff_at"] == CUTOFF
    assert record["freeze_created_at"] == "2026-08-12T12:00:00+08:00"
    assert record["kickoff_at"] == KICKOFF
    assert record["challenger_provenance"]["history_as_of_at"] == CUTOFF
    assert record["challenger_provenance"]["research_only"] is True
    assert record["challenger_provenance"]["historical_dataset_digest"] == "history-sha"
    assert record["challenger_provenance"]["historical_dataset_path"] == "historical_results.duckdb"
    assert record["prediction_sha256"] == prediction_content_hash(record)


def test_missing_canonical_research_identity_is_rejected_without_mapping():
    snapshot = _snapshot_document()
    champion = _champion(snapshot)
    champion.pop("canonical_team_identity")

    with pytest.raises(ValueError, match="CANONICAL_RESEARCH_IDENTITY_MISSING"):
        build_challenger_record(
            champion,
            history_records=[],
            input_snapshot_document=snapshot,
            now=datetime(2026, 8, 12, 12, 0, tzinfo=TZ),
        )


def test_synthetic_forward_freeze_is_pair_capture_compatible(tmp_path):
    snapshot = _snapshot_document()
    champion = _champion(snapshot)
    challenger = build_challenger_record(
        champion,
        history_records=[_history_row(index) for index in range(1, 11)],
        input_snapshot_document=snapshot,
        now=datetime(2026, 8, 12, 12, 0, tzinfo=TZ),
    )
    result = freeze_prediction(
        challenger,
        tmp_path / "challenger_predictions",
        input_snapshot_root=tmp_path / "input_snapshots",
    )
    frozen = json.loads(result["path"].read_text(encoding="utf-8"))

    captured = capture_forward_pairs(
        [champion],
        [frozen],
        now=datetime(2026, 8, 12, 13, 0, tzinfo=TZ),
        business_date="2026-08-13",
        pair_root=tmp_path / "pairs",
        raw_frozen_path=tmp_path / "frozen.json",
    )

    assert captured["pairs_captured_this_run"] == 1
    assert captured["CHAMPION_EVALUABLE"] == 1
    assert captured["CHALLENGER_EVALUABLE"] == 1
    assert captured["TRUE_PAIRED"] == 0


def test_future_freeze_is_idempotent_across_reruns_before_kickoff(tmp_path, monkeypatch):
    snapshot = _snapshot_document()
    champion = _champion(snapshot)
    champion["input_sha256"] = snapshot["canonical_input_sha256"]
    champion["canonical_model_input_sha256"] = snapshot["canonical_model_input_sha256"]
    champion_root = tmp_path / "champion"
    champion_root.mkdir()
    (champion_root / "champion.json").write_text(json.dumps(champion), encoding="utf-8")
    snapshot_root = tmp_path / "input_snapshots"
    snapshot_root.mkdir()
    snapshot_root.joinpath(f"{snapshot['canonical_input_sha256']}.json").write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    history = [_history_row(index) for index in range(1, 11)]

    class FakeStore:
        path = tmp_path / "historical_results.duckdb"

        def __init__(self, _path):
            pass

        def dataset_digest(self):
            return "history-sha"

        def iter_records(self, **_kwargs):
            return iter(history)

    monkeypatch.setattr(runner, "HistoricalResultStore", FakeStore)
    challenger_root = tmp_path / "challenger"
    first = runner.freeze_future_challengers(
        "2026-08-13",
        now=datetime(2026, 8, 12, 13, 0, tzinfo=TZ),
        champion_root=champion_root,
        challenger_root=challenger_root,
        input_snapshot_root=snapshot_root,
    )
    assert first["challenger_frozen_this_run"] == 1, json.dumps(first, sort_keys=True)
    first_path = next(challenger_root.glob("*.json"))
    first_bytes = first_path.read_bytes()

    second = runner.freeze_future_challengers(
        "2026-08-13",
        now=datetime(2026, 8, 12, 13, 1, tzinfo=TZ),
        champion_root=champion_root,
        challenger_root=challenger_root,
        input_snapshot_root=snapshot_root,
    )

    assert second["challenger_frozen_this_run"] == 0
    assert second["challenger_existing_count"] == 1
    assert list(challenger_root.glob("*.json")) == [first_path]
    assert first_path.read_bytes() == first_bytes
    frozen = json.loads(first_bytes)
    assert frozen["prediction_sha256"] == prediction_content_hash(frozen)
    assert frozen["challenger_provenance"]["historical_dataset_digest"] == "history-sha"

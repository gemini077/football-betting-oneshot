from __future__ import annotations

import json

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.storage import HistoricalResultStore
from scripts.football_data.verify_data_home import verify_data_home


def test_verify_data_home_checks_manifest_count_and_digest(tmp_path):
    data_home = tmp_path / "data-home"
    manifest_root = tmp_path / "manifests"
    store = HistoricalResultStore(data_home / "historical_results.duckdb")
    store.append(
        make_historical_match_result(
            canonical_match_id="match:verify",
            competition_id="competition:test",
            season_id="season:2026",
            home_team_id="team:home",
            away_team_id="team:away",
            kickoff_at="2026-08-01T12:00:00Z",
            home_goals=1,
            away_goals=0,
            provider="fixture",
            provider_match_id="fixture:verify",
            source_as_of_at="2026-08-01T12:00:00Z",
            captured_at="2026-08-10T00:00:00Z",
            source_record_ref="fixture:verify",
            source_reliable=True,
            resolution_method="manual_verified",
        )
    )
    manifest_root.mkdir()
    json.dump(
        {
            "record_count": 1,
            "dataset_sha256": store.dataset_digest(),
        },
        (manifest_root / "historical_results.dataset.json").open("w", encoding="utf-8"),
    )
    (manifest_root / "team_strength.dataset.json").write_text(
        json.dumps({"record_count": 0, "dataset_sha256": "0" * 64}),
        encoding="utf-8",
    )

    result = verify_data_home(data_home=data_home, manifest_root=manifest_root)
    assert result["status"] == "DATASET_NOT_AVAILABLE"
    assert result["datasets"]["historical_results"]["status"] == "OK"
    assert result["datasets"]["team_strength"]["status"] == "DATASET_NOT_AVAILABLE"

    (manifest_root / "team_strength.dataset.json").unlink()
    (manifest_root / "historical_results.dataset.json").write_text(
        json.dumps({"record_count": 1, "dataset_sha256": "0" * 64}),
        encoding="utf-8",
    )
    mismatch = verify_data_home(data_home=data_home, manifest_root=manifest_root)
    assert mismatch["status"] == "DIGEST_MISMATCH"
    assert mismatch["datasets"]["historical_results"]["status"] == "DIGEST_MISMATCH"

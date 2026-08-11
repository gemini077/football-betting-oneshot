from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def test_git_manifest_has_cohort_digests_but_not_bulk_match_ids_or_duckdb():
    report = json.loads((ROOT / "data" / "football_data" / "phase2c_research_readiness.json").read_text(encoding="utf-8"))

    assert report["recommended_cohort"]["cohort_size"] >= 0
    assert "match_ids" not in report["recommended_cohort"]
    assert all("match_ids" not in cohort for cohort in report["cohorts"].values())

    with ZipFile(ROOT / "artifacts" / "football-phase2c-preflight-handoff.zip") as archive:
        names = archive.namelist()
    assert not any(name.endswith(".duckdb") for name in names)
    assert not any("eligibility_audit" in name for name in names)

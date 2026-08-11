from __future__ import annotations

import json
from pathlib import Path

from scripts.football_data.data_home import resolve_football_data_home


ROOT = Path(__file__).resolve().parents[1]


def test_compact_verified_crosswalk_survives_detailed_candidate_cleanup():
    path = ROOT / "data" / "football_data" / "verified_identity_crosswalk.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["mappings"]

    assert len(rows) == 152
    assert all(row["verified"] is True for row in rows)
    assert all(row.get("verification_evidence_digest") for row in rows)
    assert all("aligned_fixtures" not in row and "evidence" not in row for row in rows)
    assert not (ROOT / "data" / "football_data" / "p0_p1_identity_candidates.json").exists()
    assert resolve_football_data_home() / "identity" / "p0_p1_identity_candidates.json" != path

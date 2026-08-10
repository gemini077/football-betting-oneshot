from __future__ import annotations

from scripts.football_data.p0_p1_coverage import classify_recent_form_scope


def test_european_only_history_does_not_claim_complete_club_recent_form():
    assert classify_recent_form_scope(
        observed_match_types={"continental_club"},
        intended_match_types={"league", "domestic_cup", "continental_club"},
    ) == "PARTIAL"

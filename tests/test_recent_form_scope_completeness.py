from __future__ import annotations

from scripts.football_data.p0_p1_coverage import classify_recent_form_scope


def test_single_league_source_is_not_claimed_as_all_competition_form():
    assert classify_recent_form_scope(
        observed_match_types={"league"},
        intended_match_types={"league", "domestic_cup", "continental_club"},
    ) == "PARTIAL"


def test_complete_scope_requires_known_evidence_for_each_intended_type():
    assert classify_recent_form_scope(
        observed_match_types={"league", "domestic_cup", "continental_club"},
        intended_match_types={"league", "domestic_cup", "continental_club"},
    ) == "COMPLETE"
    assert classify_recent_form_scope(
        observed_match_types=set(),
        intended_match_types={"league"},
        evidence_known=False,
    ) == "UNKNOWN"

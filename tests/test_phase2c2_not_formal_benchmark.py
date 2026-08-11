from scripts.football_data.phase2c2_opponent_strength import phase2c2_research_boundary


def test_phase2c2_is_research_only_and_not_formal_benchmark():
    boundary = phase2c2_research_boundary()
    assert boundary["research_only"] is True
    assert boundary["formal_benchmark_eligible"] is False
    assert boundary["production_challenger_registration"] is False
    assert boundary["fresh_heldout_available"] is False
    assert boundary["historical_validation_reused"] is True

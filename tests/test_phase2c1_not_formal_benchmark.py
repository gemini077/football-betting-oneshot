from __future__ import annotations

from scripts.football_data.phase2c1_experiment import research_boundary


def test_phase2c1_is_research_only_and_never_formal_benchmark():
    boundary = research_boundary()
    assert boundary["research_only"] is True
    assert boundary["formal_benchmark_eligible"] is False
    assert boundary["champion_comparison_supported"] is False

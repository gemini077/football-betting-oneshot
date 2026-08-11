from scripts.football_data.phase2c2_opponent_strength import paired_comparison_bootstrap


def test_paired_bootstrap_reports_both_required_comparisons():
    opponent = [{"loss": float(index)} for index in range(8)]
    raw = [{"loss": float(index + 1)} for index in range(8)]
    frozen = [{"loss": float(index + 2)} for index in range(8)]
    result = paired_comparison_bootstrap(opponent, raw, frozen, seed=7, n_bootstrap=100)
    assert set(result) == {"vs_matched_raw", "vs_frozen_2c1"}
    assert result["vs_matched_raw"]["sample"] == 8

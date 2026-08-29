from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.football_data.fe_dc1_model import (
    PreRegisteredConfig,
    dixon_coles_tau,
    fit_league_model,
    network_diagnostics,
    run_chronological_backtest,
    score_distribution,
)


def _match(
    match_id: str,
    kickoff_at: str,
    home: str,
    away: str,
    home_goals: int,
    away_goals: int,
) -> dict:
    return {
        "canonical_match_id": match_id,
        "competition_id": "competition:sweden-allsvenskan",
        "season_id": "season:sweden-allsvenskan:2026",
        "home_team_id": home,
        "away_team_id": away,
        "kickoff_at": kickoff_at,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "eligible_for_team_strength": True,
        "entity_type": "club",
        "match_type": "league",
    }


def _round_robin_fixture() -> list[dict]:
    teams = ["team:a", "team:b", "team:c", "team:d", "team:e", "team:f"]
    rows: list[dict] = []
    index = 0
    for home_index, home in enumerate(teams):
        for away_index, away in enumerate(teams):
            if home_index >= away_index:
                continue
            index += 1
            rows.append(
                _match(
                    f"match:{index}",
                    f"2026-01-{index:02d}T12:00:00Z",
                    home,
                    away,
                    1 + (home_index % 2),
                    away_index % 2,
                )
            )
    return rows


def test_tau_only_changes_the_four_low_score_cells():
    lambda_home = 1.4
    lambda_away = 0.9
    rho = -0.08

    assert dixon_coles_tau(0, 0, lambda_home, lambda_away, rho) == pytest.approx(
        1 - lambda_home * lambda_away * rho
    )
    assert dixon_coles_tau(1, 0, lambda_home, lambda_away, rho) == pytest.approx(
        1 + lambda_away * rho
    )
    assert dixon_coles_tau(0, 1, lambda_home, lambda_away, rho) == pytest.approx(
        1 + lambda_home * rho
    )
    assert dixon_coles_tau(1, 1, lambda_home, lambda_away, rho) == pytest.approx(1 - rho)
    assert dixon_coles_tau(2, 2, lambda_home, lambda_away, rho) == 1.0

    independent = score_distribution(lambda_home, lambda_away, 0.0, max_goals=8)
    corrected = score_distribution(lambda_home, lambda_away, rho, max_goals=8)
    changed = {
        (home_goals, away_goals)
        for home_goals, row in enumerate(zip(independent["matrix"], corrected["matrix"]))
        for away_goals, (before, after) in enumerate(zip(*row))
        if before != pytest.approx(after)
    }
    assert changed == {(0, 0), (1, 0), (0, 1), (1, 1)}
    assert sum(sum(row) for row in corrected["matrix"]) == pytest.approx(1.0)


def test_connected_network_fit_is_identifiable_and_has_a_rho_zero_control():
    rows = _round_robin_fixture()
    config = PreRegisteredConfig(warmup_matches=4, max_goals=8, optimizer_max_iter=300)
    diagnostics = network_diagnostics(rows)
    assert diagnostics["team_count"] == 6
    assert diagnostics["component_count"] == 1

    model = fit_league_model(
        rows,
        config=config,
        reference_kickoff=datetime(2026, 2, 1, tzinfo=timezone.utc),
        rho_mode="fit",
    )
    control = fit_league_model(
        rows,
        config=config,
        reference_kickoff=datetime(2026, 2, 1, tzinfo=timezone.utc),
        rho_mode="zero",
    )

    assert sum(model.attack.values()) == pytest.approx(0.0, abs=1e-8)
    assert sum(model.defense.values()) == pytest.approx(0.0, abs=1e-8)
    assert control.rho == 0.0
    assert model.training_match_count == len(rows)
    assert model.optimizer_converged is True


def test_walk_forward_uses_strict_prior_history_and_records_network_counts():
    rows = [
        _match("prior-1", "2026-01-01T12:00:00Z", "team:a", "team:b", 1, 0),
        _match("prior-2", "2026-01-02T12:00:00Z", "team:c", "team:d", 0, 0),
        _match("prior-3", "2026-01-03T12:00:00Z", "team:a", "team:c", 2, 1),
        _match("prior-4", "2026-01-04T12:00:00Z", "team:b", "team:d", 1, 1),
        _match("target", "2026-01-05T12:00:00Z", "team:a", "team:d", 1, 0),
        _match("future", "2026-01-06T12:00:00Z", "team:b", "team:c", 0, 2),
    ]
    result = run_chronological_backtest(
        rows,
        config=PreRegisteredConfig(warmup_matches=4, max_goals=8, optimizer_max_iter=300),
    )

    target = next(row for row in result["predictions"] if row["match_id"] == "target")
    assert target["history_match_count"] == 4
    assert target["home_history_match_count"] == 2
    assert target["away_history_match_count"] == 2
    assert target["network_team_count"] == 4
    assert target["network_component_count"] == 1
    assert target["training_max_kickoff"] == "2026-01-04T12:00:00Z"
    assert target["used_history_match_ids"] == ["prior-1", "prior-2", "prior-3", "prior-4"]
    assert all(kickoff < target["kickoff_at"] for kickoff in target["used_history_kickoffs"])
    assert "target" not in target["used_history_match_ids"]
    assert "future" not in target["used_history_match_ids"]
    assert result["metrics"]["dixon_coles"]["sample_size"] == 2


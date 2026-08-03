from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from repair_report_consistency import repair_report_payload


def _candidate(contract_id, selection, label, probability, *, line=None):
    return {
        "contract_id": contract_id,
        "family": "total",
        "selection": selection,
        "label": label,
        "line": line,
        "model_probability": probability,
        "conservative_probability": probability,
        "fair_odds": 1 / probability,
    }


def test_repairs_only_a_cross_market_side_contradiction():
    over = _candidate("total.2.5.over", "over", "大小球：大2.5", 0.79, line=2.5)
    under = _candidate("total.2.5.under", "under", "大小球：小2.5", 0.21, line=2.5)
    exact = {
        "contract_id": "exact_total.6+",
        "family": "exact_total",
        "selection": "6+",
        "label": "精确总进球：6+",
        "model_probability": 0.25,
        "conservative_probability": 0.175,
        "fair_odds": 4.0,
        "goals": "6+",
    }
    payload = {
        "model": {
            "market_predictions": [over, under, exact],
            "dimension_predictions": {
                "btts": {"contract_id": "btts.yes", "selection": "yes"},
                "total": under,
                "exact_total": exact,
            },
            "total_goals_buckets": [
                {"goals": "0", "probability": 0.10},
                {"goals": "1", "probability": 0.10},
                {"goals": "2", "probability": 0.20},
                {"goals": "3", "probability": 0.15},
                {"goals": "4", "probability": 0.15},
                {"goals": "5", "probability": 0.15},
                {"goals": "6+", "probability": 0.25},
            ],
        },
        "decisions": {
            "primary_contract": {"contract_id": "btts.yes"},
            "unique_primary_dimension": "双方进球：是（模型70.0%）",
            "dimension_predictions": {
                "btts": {"contract_id": "btts.yes", "selection": "yes"},
                "total": under,
                "exact_total": exact,
            },
        },
    }
    before = deepcopy(payload)

    assert repair_report_payload(payload) is True
    assert payload["model"]["dimension_predictions"]["total"]["selection"] == "under"
    assert payload["model"]["dimension_predictions"]["btts"]["contract_id"] == "btts.yes"
    repaired_exact = payload["model"]["dimension_predictions"]["exact_total"]
    assert repaired_exact["goals"] == "2"
    assert repaired_exact["consistency"]["status"] == "aligned_with_total_dimension"
    assert payload["decisions"]["dimension_predictions"] == payload["model"]["dimension_predictions"]
    assert payload["decisions"]["primary_contract"] == {"contract_id": "btts.yes"}
    assert payload["decisions"]["unique_primary_dimension"] == "双方进球：是（模型70.0%）"
    assert payload["automation"]["consistency_repair"]["status"] == "repaired_existing_report"
    assert before["model"]["dimension_predictions"]["total"]["selection"] == "under"


def test_does_not_rewrite_a_consistent_report():
    exact = {
        "contract_id": "exact_total.2",
        "family": "exact_total",
        "selection": "2",
        "label": "精确总进球：2",
        "model_probability": 0.30,
        "goals": "2",
    }
    total = _candidate("total.2.5.under", "under", "大小球：小2.5", 0.60, line=2.5)
    payload = {
        "model": {
            "market_predictions": [total, exact],
            "dimension_predictions": {"total": total, "exact_total": exact},
            "total_goals_buckets": [{"goals": "2", "probability": 0.30}],
        },
        "decisions": {"dimension_predictions": {"total": total, "exact_total": exact}},
    }

    assert repair_report_payload(payload) is False
    assert "automation" not in payload

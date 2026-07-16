from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from risk_engine import evaluate_traps, market_metrics


def test_market_metrics_accepts_null_consensus():
    result = market_metrics(
        {"ouzhi": {"bookmakers": []}, "yazhi": {"companies": []}},
        {"consensus": None},
        None,
    )
    assert result["shin_probabilities"] == {}


def test_trap_evaluation_accepts_null_consensus():
    result = evaluate_traps(
        {"ouzhi": {"bookmakers": []}, "yazhi": {"companies": []}},
        {"consensus": None},
        {"rules": []},
        None,
    )
    assert result["calculation_status"] == "degraded"

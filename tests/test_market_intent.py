from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_intelligence import interpret_market_intent


def intelligence(euro, asian, sharp, exchange=None, water_direction="neutral"):
    return {"modules": {
        "nowscore_trends": {
            "company_count": 17,
            "snapshot_count": 839,
            "direction_counts": {
                "one_x_two_home": euro,
                "asian_home": asian,
                "total": {"up": 2, "down": 0, "flat": 15},
            },
        },
        "water_flow": {
            "direction": water_direction,
            "flow_ratio": 0.6 if water_direction != "neutral" else 0.0,
            "same_line_sources": 5,
        },
        "scs": {"per_outcome": {"home": {"tier_scores": {"sharp": sharp}}}},
        "exchange": exchange or {},
    }}


def test_late_multi_market_opposition_weakens_model_in_plain_language():
    result = interpret_market_intent(
        {},
        intelligence(
            {"shortened": 1, "lengthened": 14, "flat": 2},
            {"strengthened": 0, "weakened": 3, "flat": 14},
            -0.55,
            water_direction="away",
        ),
        {"home": 0.52, "draw": 0.25, "away": 0.23},
        "T-30M",
    )
    assert result["direction"] == "away"
    assert result["impact_code"] == "weaken"
    assert "临盘" in result["model_impact"]
    assert "削弱原首推" in result["model_impact"]
    assert "不能称为真实资金流" in result["money_flow"]
    assert "目的推断" in result["bookmaker_behaviour"]


def test_exchange_confirmation_marks_high_confidence_but_not_certain_result():
    exchange = {
        "total_volume": 180000,
        "volume_minus_market_probability_pp": {"home": 8.5, "draw": -3.0, "away": -5.5},
    }
    result = interpret_market_intent(
        {},
        intelligence(
            {"shortened": 12, "lengthened": 2, "flat": 3},
            {"strengthened": 5, "weakened": 1, "flat": 11},
            0.48,
            exchange=exchange,
            water_direction="home",
        ),
        {"home": 0.55, "draw": 0.25, "away": 0.20},
        "T-60M",
    )
    assert result["direction"] == "home"
    assert result["confidence"] == "高"
    assert result["impact_code"] == "confirm"
    assert "互相确认" in result["money_flow"]
    assert "避免把同一市场信息重复计入概率" in result["model_impact"]


from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_contracts import legacy_contract, settle_contract, split_quarter_line


def test_quarter_lines_and_double_chance_settle_consistently():
    assert split_quarter_line(-0.25) == (-0.5, 0.0)
    result = settle_contract({"family": "double_chance", "selection": "1x"}, (0, 0))
    assert result["units"] == 1.0
    assert result["hit"] is True


def test_asian_total_push_is_not_a_hit_or_loss():
    result = settle_contract({"family": "total", "selection": "over", "line": 2.5}, (1, 1))
    assert result["units"] == -1.0
    result = settle_contract({"family": "total", "selection": "over", "line": 2.0}, (1, 1))
    assert result["units"] == 0.0
    assert result["hit"] is None


def test_legacy_primary_text_is_migratable():
    contract = legacy_contract("主队不败（1X）")
    assert contract["family"] == "double_chance"
    assert contract["selection"] == "1x"

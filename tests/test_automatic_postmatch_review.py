from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from automatic_postmatch_review import _primary_settlement


def test_total_goals_primary_dimension_is_strictly_settled():
    pick, actual, hit, market = _primary_settlement("小2.5（方向保留）", 1, 1)
    assert market == "大小球"
    assert pick == "小2.5"
    assert actual == "总进球2"
    assert hit is True


def test_wdl_primary_dimension_remains_supported():
    pick, actual, hit, market = _primary_settlement("胜平负：客胜（模型45.3%）", 0, 2)
    assert market == "胜平负"
    assert pick == "客胜"
    assert actual == "客胜"
    assert hit is True

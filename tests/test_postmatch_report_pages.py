from datetime import datetime
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from postmatch_dashboard import render_review_page, write_review_pages


def sample_review():
    return {
        "MatchID": "M999",
        "赛事与对阵": "测试联赛｜主队 vs 客队",
        "实际90分钟比分": "1-0",
        "赛前首推主维度": "主胜",
        "主维度是否命中": "是",
        "赛前唯一首推比分": "1-0",
        "比分是否命中": "是",
        "赛前亚盘方向": "主队-0.25",
        "赛前大小球方向": "小2.5",
        "赛前BTTS判断": "否",
        "复盘摘要": "主维度与唯一比分均严格命中。",
        "settlement": {
            "asian_handicap": {"hit": True},
            "total_goals_mode": {"hit": True},
            "btts": {"hit": True},
        },
    }


def test_individual_postmatch_report_is_complete_standalone_page():
    page = render_review_page(sample_review(), {}, {}, [], datetime(2026, 7, 16, 12, 0))
    for section in (
        "01｜复盘结论",
        "02｜全部玩法严格结算",
        "03｜赛前推理回放",
        "04｜盘口时间线与数据有效性",
        "05｜根因、反事实与模型修正",
        "06｜模拟注单结算",
        "07｜真实注单结算",
    ):
        assert section in page
    assert "命中" in page
    assert "<dialog" not in page
    assert "<iframe" not in page


def test_review_generator_writes_stable_match_url():
    with tempfile.TemporaryDirectory() as temp:
        links = write_review_pages([sample_review()], [], [], [], datetime(2026, 7, 16, 12, 0), Path(temp))
        assert links["M999"] == "../postmatch_reports/M999.html"
        assert (Path(temp) / "M999.html").exists()

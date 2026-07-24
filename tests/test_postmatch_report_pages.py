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
        "01｜赛果与复盘结论",
        "02｜比赛过程与关键事实",
        "03｜全部模型维度严格结算",
        "04｜模拟注单结算",
        "05｜真实注单结算",
        "06｜唯一比分推演审计",
        "07｜盘口、机构行为与数据有效性",
        "08｜赛前风险如何被验证",
        "09｜分层根因",
        "10｜反事实、模型修正与样本归档",
        "11｜判断变化",
    ):
        assert section in page
    assert "命中" in page
    assert "<dialog" not in page
    assert "<iframe" not in page
    assert "<details>" in page


def test_review_generator_writes_stable_match_url():
    with tempfile.TemporaryDirectory() as temp:
        links = write_review_pages([sample_review()], [], [], [], datetime(2026, 7, 16, 12, 0), Path(temp))
        assert links["M999"] == "../postmatch_reports/M999.html"
        assert (Path(temp) / "M999.html").exists()


def test_review_generator_keeps_existing_frozen_report():
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / "M999.html"
        target.write_text("frozen", encoding="utf-8")
        links = write_review_pages([sample_review()], [], [], [], datetime(2026, 7, 24, 12, 0), Path(temp))
        assert links["M999"] == "../postmatch_reports/M999.html"
        assert target.read_text(encoding="utf-8") == "frozen"

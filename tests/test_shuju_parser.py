from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_and_parse import parse_shuju


def test_parse_shuju_extracts_h2h_and_four_form_splits():
    html = """
    <div class="team_name">主队<span>[欧冠]</span></div><div class="team_name">客队<span>[欧冠]</span></div>
    <span class="his_info">双方近1次交战，主队<span>0胜</span><span>0平</span><span>1负</span>，进1球，失2球</span>
    <div class="team_a" id="team_zhanji_1"><p><strong>主队</strong>近10场战绩<span>3胜</span><span>2平</span><span>5负</span><span>进12球</span>失<span>13球</span></p></div>
    <div class="team_b" id="team_zhanji_0"><p><strong>客队</strong>近10场战绩<span>6胜</span><span>3平</span><span>1负</span><span>进22球</span>失<span>9球</span></p></div>
    <div class="team_a" id="team_zhanji2_1"><p><strong>主队</strong>近10场战绩<span>6胜</span><span>2平</span><span>2负</span><span>进19球</span>失<span>11球</span></p></div>
    <div class="team_b" id="team_zhanji2_0"><p><strong>客队</strong>近10场战绩<span>5胜</span><span>2平</span><span>3负</span><span>进16球</span>失<span>13球</span></p></div>
    """
    parsed = parse_shuju(html)
    assert parsed["home_team"] == "主队" and parsed["away_team"] == "客队"
    assert parsed["h2h"]["losses"] == 1
    assert parsed["recent_form"]["home_overall"]["goals_for"] == 12
    assert parsed["recent_form"]["away_overall"]["goals_against"] == 9
    assert parsed["recent_form"]["home_home"]["wins"] == 6
    assert parsed["recent_form"]["away_away"]["goals_for"] == 16

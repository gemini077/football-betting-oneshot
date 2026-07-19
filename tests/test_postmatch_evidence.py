from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from postmatch_evidence import nowscore_match_id, parse_nowscore_detail


def test_nowscore_id_can_be_recovered_from_verified_context_url():
    report = {"fundamentals": {"sources": ["https://live.nowscore.com/info/referee/2907407.htm?l=1"]}}
    assert nowscore_match_id(report) == "2907407"


def test_detail_parser_extracts_score_events_stats_and_environment():
    content = """
    <div>场地：测试体育场 天气：微雨 温度：30℃</div>
    <tr class='ky_tit'><td></td><td><span class='t15'>4</span></td><td>时间</td><td><span class='t15'>6</span></td><td></td></tr>
    <div class="home"><a>法国</a> 4-2-3-1</div><div class="guest"><a>英格兰</a> 4-3-3</div>
    <tr data-kind="1"><td></td><td></td><td><b>3'</b></td><td><img title='入球'/></td><td>赖斯</td></tr>
    <tr data-kind="1"><td>姆巴佩</td><td><img title='入球'/></td><td><b>50'</b></td><td></td><td></td></tr>
    <tr><td></td><td class='numberleft bg2'>19</td><td>射门</td><td class='numberright bg2'>19</td><td></td></tr>
    <tr><td></td><td class='numberleft bg1'>2.88</td><td>预期进球(xG)</td><td class='numberright bg1'>2.88</td><td></td></tr>
    """
    evidence = parse_nowscore_detail(content, "https://example.test/detail")
    assert evidence["score_90m"] == "4-6"
    assert evidence["score_half_time"] == "0-1"
    assert evidence["formations"] == {"home": "4-2-3-1", "away": "4-3-3"}
    assert evidence["statistics"]["射门"] == {"home": "19", "away": "19"}
    assert "测试体育场" in evidence["environment"]


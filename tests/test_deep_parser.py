import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_and_parse import parse_daxiao, parse_ouzhi, parse_touzhu, parse_yazhi  # noqa: E402


def market_row(current_line: str, open_line: str) -> str:
    return f"""
    <tr class="tr1" xls="row" id="293" dt="2026-07-13 18:52:54">
      <td class="tb_plgs"><a href="?cid=293" title="William"><span class="quancheng">William</span></a></td>
      <td><table class="pl_table_data"><tr>
        <td>0.750↓</td><td ref="{current_line}">3.5</td><td>0.860↑</td>
      </tr></table></td>
      <td><time>07-13 18:39</time></td>
      <td><table class="pl_table_data"><tr>
        <td>0.800</td><td ref="{open_line}">3</td><td>0.910</td>
      </tr></table></td>
      <td><time>07-05 23:14</time></td>
    </tr>
    """


class DeepParserTests(unittest.TestCase):
    def test_touzhu_allows_missing_optional_index(self):
        row = lambda team, last: f"""<tr><td>{team}</td><td>1.21</td><td>76.5%</td><td>-</td><td>84.0%</td><td>1.25</td><td>117,705</td><td>-7,035</td><td>-</td><td>9</td><td>{last}</td></tr>"""
        html = "热度分析<table>" + row("主队", "-6") + row("平局", "29") + row("客队", "-") + "<tr><td>数据提点</td></tr></table>"
        parsed = parse_touzhu(html)
        betfair = parsed["betfair"]
        self.assertEqual(betfair["home"]["betfair_volume"], 117705)
        self.assertEqual(betfair["home"]["page_simulated_pl"], -7035)
        self.assertIsNone(betfair["away"]["pl_index"])
        self.assertEqual("display_only", parsed["betfair_metadata"]["page_simulated_pl_signal_usage"])

    def test_touzhu_keeps_volume_when_exchange_price_is_missing(self):
        row = lambda team, price: f"""<tr><td>{team}</td><td>2.10</td><td>33.3%</td><td>-</td><td>33.3%</td><td>{price}</td><td>12,345</td><td>-</td><td>-</td><td>1</td><td>2</td></tr>"""
        html = "热度分析<table>" + row("主队", "1.92") + row("平局", "-") + row("客队", "-") + "<tr><td>数据提点</td></tr></table>"

        parsed = parse_touzhu(html)

        self.assertEqual(12345, parsed["betfair"]["draw"]["betfair_volume"])
        self.assertIsNone(parsed["betfair"]["draw"]["betfair_price"])
        self.assertEqual("partial", parsed["betfair_metadata"]["completeness"])
        self.assertEqual(["draw", "away"], parsed["betfair_metadata"]["missing_price_outcomes"])

    def test_ouzhi_summary_uses_stable_ids(self):
        html = """
        <td class="tb_plgs" title="P*********"><a href="?cid=1055"></a></td>
        <td id="avwinc2">1.25</td><td id="avdrawc2">5.52</td><td id="avlostc2">9.35</td>
        <td id="avwinj2">1.21</td><td id="avdrawj2">6.34</td><td id="avlostj2">10.72</td>
        <td id="lswc2">4.94</td><td id="lsdc2">30.74</td><td id="lslc2">69.2</td>
        <td id="lswj2">9.97</td><td id="lsdj2">69.46</td><td id="lslj2">84.61</td>
        """
        summary = parse_ouzhi(html)["summary"]
        self.assertEqual(summary["avg_spf_current"]["home"], 1.21)
        self.assertEqual(summary["dispersion"]["away"], 84.61)

    def test_yazhi_keeps_nested_row_fields(self):
        company = parse_yazhi(market_row("-1.750", "-1.500"))["companies"][0]
        self.assertEqual(company["current_handicap"], -1.75)
        self.assertEqual(company["open_handicap"], -1.5)
        self.assertEqual(company["current_water_home"], 0.75)
        self.assertEqual(company["open_water_away"], 0.91)
        self.assertEqual(company["change_time"], "07-13 18:39")
        self.assertEqual(company["open_time"], "07-05 23:14")

    def test_daxiao_normalizes_numeric_line(self):
        company = parse_daxiao(market_row("-3.250", "-3.000"))["companies"][0]
        self.assertEqual(company["current_line"], 3.25)
        self.assertEqual(company["open_line"], 3.0)
        self.assertEqual(company["current_over_water"], 0.75)
        self.assertEqual(company["open_under_water"], 0.91)


if __name__ == "__main__":
    unittest.main()

from spdex_exchange import merge_into, parse_detail, parse_index


def test_parse_spdex_index_and_detail():
    index = """<div class='datatitle'><h3 tid='35828094'>[竞彩20260718期第103场] \\法国 VS 英格兰</h3><span class='matchtime'>开赛时间：2026/7/19 5:00</span></div>"""
    detail = """
    <table><tr><th>header</th></tr>
    <tr><td>法国</td><td>70</td><td>17,357,130</td><td>83%</td><td>63</td><td>1.93</td><td>-0.36%</td><td>1.85</td><td>1</td></tr>
    <tr><td></td><td>12</td><td>1,463,444</td><td>7%</td><td>-71</td><td>4.30</td><td>-0.01%</td><td>4.00</td><td>4</td></tr>
    <tr><td>英格兰</td><td>18</td><td>2,101,560</td><td>10%</td><td>-59</td><td>4.00</td><td>-0.31%</td><td>3.81</td><td>5</td></tr></table>
    交易量总成交：20,922,134 更新时间：07.18 22:57:56
    """

    assert parse_index(index)[0]["id"] == "35828094"
    parsed = parse_detail(detail)
    assert parsed["betfair"]["draw"]["betfair_volume"] == 1463444
    assert parsed["total_volume"] == 20922134


def test_spdex_only_fills_missing_exchange_fields():
    deep = {"touzhu": {"betfair": {"home": {"betfair_price": 1.90, "betfair_volume": 100}}}}
    snapshot = {
        "status": "OK", "source_url": "spdex:test", "total_volume": 600,
        "betfair": {
            "home": {"betfair_price": 1.93, "betfair_volume": 200},
            "draw": {"betfair_price": 4.3, "betfair_volume": 200},
            "away": {"betfair_price": 4.0, "betfair_volume": 200},
        },
    }

    merged = merge_into(deep, snapshot)

    assert merged["touzhu"]["betfair"]["home"]["betfair_price"] == 1.90
    assert merged["touzhu"]["betfair"]["draw"]["betfair_price"] == 4.3
    assert merged["touzhu"]["betfair_metadata"]["completeness"] == "complete"

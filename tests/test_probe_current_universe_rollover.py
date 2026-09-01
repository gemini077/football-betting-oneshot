from scripts.probe_current_universe_rollover import (
    classify_probe,
    extract_official_summary,
    summarize_trade_page,
)


def test_extract_official_summary_uses_business_date_from_nested_match_groups():
    payload = {
        "success": True,
        "value": {
            "matchInfoList": [
                {
                    "businessDate": "2026-08-31",
                    "subMatchList": [{"matchId": 1, "matchNumStr": "周一001"}],
                },
                {
                    "businessDate": "2026-09-01",
                    "subMatchList": [
                        {"matchId": 2, "matchNumStr": "周二001"},
                        {"matchId": 3, "matchNumStr": "周二002"},
                    ],
                },
            ]
        },
    }

    summary = extract_official_summary(payload, "2026-09-01")

    assert summary["available_business_dates"] == ["2026-08-31", "2026-09-01"]
    assert summary["target_business_date_row_count"] == 2
    assert summary["sample_match_ids"] == ["2", "3"]
    assert summary["sample_match_numbers"] == ["周二001", "周二002"]


def test_summarize_trade_page_preserves_raw_rows_and_separates_process_date_from_match_date():
    page = """
    <table>
      <tr class="tr2" data-matchnum="周二001"
          data-processdate="2026-08-31" data-matchdate="2026-09-01"
          data-matchtime="00:30">
        <td><a href="/fenxi/shuju-1234567.shtml">fixture</a></td>
      </tr>
    </table>
    """

    summary = summarize_trade_page(page, "2026-09-01", parser_target_row_count=0)

    assert summary["raw_match_row_count"] == 1
    assert summary["target_business_date_row_count"] == 0
    assert summary["target_match_date_row_count"] == 1
    assert summary["current_parser_target_row_count"] == 0
    row = summary["raw_match_rows"][0]
    assert row["shuju_id"] == "1234567"
    assert row["data_processdate"] == "2026-08-31"
    assert row["data_matchdate"] == "2026-09-01"
    assert "data-matchnum=\"周二001\"" in row["raw_row_html"]


def test_classify_probe_distinguishes_header_only_from_stale_route_and_channel_contract():
    header_only = classify_probe(
        {
            "A_repo_current": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "A_repo_official_headers": {"target_business_date_row_count": 2, "waf_block_evidence": []},
            "B_jc_match_list": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "B_uniform_match_list": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "C_jc_calculator": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "C_uniform_calculator": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "D_trade_page": {
                "target_business_date_row_count": 0,
                "target_match_date_row_count": 0,
                "current_parser_target_row_count": 0,
                "waf_block_evidence": [],
            },
        }
    )
    assert header_only["classification"] == "WAF_BLOCK"
    assert header_only["decision_gate"] == "FIX_HEADERS_ONLY"

    stale_route = classify_probe(
        {
            "A_repo_current": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "A_repo_official_headers": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "B_jc_match_list": {"target_business_date_row_count": 2, "waf_block_evidence": []},
            "B_uniform_match_list": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "C_jc_calculator": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "C_uniform_calculator": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "D_trade_page": {
                "target_business_date_row_count": 0,
                "target_match_date_row_count": 0,
                "current_parser_target_row_count": 0,
                "waf_block_evidence": [],
            },
        }
    )
    assert stale_route["classification"] == "STALE_ENDPOINT_CONTRACT"
    assert stale_route["decision_gate"] == "FIX_OFFICIAL_ROUTE"

    channel_contract = classify_probe(
        {
            "A_repo_current": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "A_repo_official_headers": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "B_jc_match_list": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "B_uniform_match_list": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "C_jc_calculator": {"target_business_date_row_count": 3, "waf_block_evidence": []},
            "C_uniform_calculator": {"target_business_date_row_count": 0, "waf_block_evidence": []},
            "D_trade_page": {
                "target_business_date_row_count": 0,
                "target_match_date_row_count": 0,
                "current_parser_target_row_count": 0,
                "waf_block_evidence": [],
            },
        }
    )
    assert channel_contract["classification"] == "WRONG_CHANNEL_OR_POOL_CONTRACT"
    assert channel_contract["decision_gate"] == "FIX_OFFICIAL_ROUTE"

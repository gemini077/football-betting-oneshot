from scripts.paper_ledger import build_paper_ledger, pair_key, settle_ticket


def report(primary="小2.5", odds=1.9, score="1-1"):
    return {
        "match": {"home": "甲", "away": "乙", "kickoff_local": "2026-07-15 03:00"},
        "report": {"model_version": "v0.12.0", "analysis_timestamp": "2026-07-14T20:00:00+08:00"},
        "model": {
            "probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
            "score_probabilities": [{"score": score, "probability": 0.14}],
        },
        "decisions": {"unique_primary_dimension": primary, "unique_score": f"甲 {score} 乙"},
        "betting": {"price_audit": [{"market": "Pinnacle小2.5", "odds": odds, "model_probability": 0.58, "ev": 0.102}]},
    }


def test_paper_ledger_settles_primary_but_keeps_score_without_price_as_observation():
    payload = report()
    ledger = build_paper_ledger([payload], {pair_key("甲", "乙"): (0, 2)})
    assert ledger["summary"]["settled"] == 1
    assert ledger["summary"]["observations"] == 1
    assert ledger["summary"]["profit_units"] == 0.9
    assert ledger["tickets"][0]["settlement"] == "赢"


def test_missing_result_is_pending_and_never_touches_real_balance():
    ledger = build_paper_ledger([report()], {})
    assert ledger["summary"]["pending"] == 1
    assert ledger["policy"]["real_balance_affected"] is False


def test_quarter_total_supports_half_settlement():
    ticket = {"selection": "under", "line": 2.25, "odds": 1.9, "stake_units": 1}
    settled = settle_ticket(ticket, (1, 1))
    assert settled["settlement"] == "赢半"
    assert settled["profit_units"] == 0.45


def test_frozen_contract_is_not_repriced_by_a_later_report():
    first = build_paper_ledger([report(odds=1.9)], {})
    later = build_paper_ledger([report(odds=2.4)], {}, frozen_tickets=first["tickets"])
    primary = next(row for row in later["tickets"] if row["ticket_type"] == "primary")
    assert primary["odds"] == 1.9
    assert primary["ticket_id"] == "SIM-0001"

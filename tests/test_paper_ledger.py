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
    assert ledger["summary"]["observations"] == 0
    assert len(ledger["price_pending_candidates"]) == 1
    primary = next(row for row in ledger["tickets"] if row["ticket_type"] == "primary")
    assert ledger["summary"]["profit_units"] == round(primary["stake_units"] * 0.9, 4)
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


def test_existing_pending_paper_stake_is_resized_from_ev_not_forced_to_minimum():
    first = build_paper_ledger([report()], {})
    first["tickets"][0]["stake_units"] = 0.1
    migrated = build_paper_ledger([], {}, frozen_tickets=first["tickets"])
    assert migrated["tickets"][0]["stake_units"] > 2.0
    assert migrated["tickets"][0]["stake_units"] <= 5.0
    assert migrated["policy"]["stake_step"] == 0.01


def test_negative_ev_contract_has_price_but_is_rejected_without_stake():
    ledger = build_paper_ledger([report(odds=1.5)], {})
    primary = next(row for row in ledger["rejected_candidates"] if row["ticket_type"] == "primary")
    assert primary["odds"] == 1.5
    assert primary["sizing_ev"] < 0
    assert primary["stake_units"] == 0
    assert primary["status"] == "rejected_by_ev"
    assert all(row["ticket_id"] != primary["ticket_id"] for row in ledger["tickets"])


def test_first_captured_price_repairs_frozen_observation_without_reselecting():
    first = build_paper_ledger([report(odds=None)], {})
    primary = next(row for row in first["price_pending_candidates"] if row["ticket_type"] == "primary")
    assert primary["odds"] is None

    repaired = build_paper_ledger(
        [],
        {primary["match_key"]: (0, 2)},
        frozen_tickets=first["_frozen_records"],
        initial_price_overrides={
            primary["ticket_id"]: {
                "odds": 1.61,
                "probability": 0.655,
                "ev": 0.05455,
                "price_source": "first capture",
            }
        },
    )
    item = next(row for row in repaired["tickets"] if row["ticket_id"] == primary["ticket_id"])
    assert item["selection"] == primary["selection"]
    assert item["odds"] == 1.61
    assert item["profit_units"] > 0


def test_home_handicap_settlement_supports_push_and_win():
    ticket = {"selection": "home_handicap", "line": -2, "odds": 2.04, "stake_units": 2}
    assert settle_ticket(ticket, (2, 0))["settlement"] == "走"
    assert settle_ticket(ticket, (3, 0))["profit_units"] == 2.08

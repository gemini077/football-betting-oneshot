import json

from scripts.paper_channel_prices import sync_channel_price_overrides


def test_user_channel_correct_score_price_is_bound_by_explicit_aliases(tmp_path):
    aliases = {
        "teams": [
            {"canonical": "甲队", "aliases": ["甲渠道"]},
            {"canonical": "乙队", "aliases": ["乙渠道"]},
        ],
        "safety": {"maximum_kickoff_difference_minutes": 180},
    }
    archive = {
        "matches": {
            "99": {
                "metadata": {
                    "home_name": "甲渠道",
                    "away_name": "乙渠道",
                    "kickoff_timestamp": "1784139300000",
                },
                "quotes": {
                    "7|1-1|1:1": {
                        "market_code": "7",
                        "handicap_line": "1-1",
                        "inferred_decimal_odds": 8.6,
                        "odds_scale_verified": True,
                        "received_at": "2026-07-15T20:00:00+08:00",
                    }
                },
            }
        }
    }
    archive_path = tmp_path / "archive.json"
    aliases_path = tmp_path / "aliases.json"
    overrides_path = tmp_path / "overrides.json"
    archive_path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
    aliases_path.write_text(json.dumps(aliases, ensure_ascii=False), encoding="utf-8")
    tickets = [{
        "ticket_id": "SIM-0099",
        "ticket_type": "correct_score",
        "home": "甲队",
        "away": "乙队",
        "kickoff_local": "2026-07-16 02:15",
        "selection": "1-1",
        "probability": 0.12,
        "odds": None,
    }]

    result = sync_channel_price_overrides(
        tickets,
        archive_path=archive_path,
        aliases_path=aliases_path,
        overrides_path=overrides_path,
    )

    saved = json.loads(overrides_path.read_text(encoding="utf-8"))["tickets"]["SIM-0099"]
    assert result["added"] == ["SIM-0099"]
    assert saved["odds"] == 8.6
    assert saved["ev"] == 0.032
    assert saved["source_match_id"] == "99"

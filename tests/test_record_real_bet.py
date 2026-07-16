import json

import pytest

from scripts.record_real_bet import parse_body, persist


def body(stake="12.34"):
    return "\n".join((
        "match_id: fixture-1", "match: 甲 vs 乙", "market: 全场独赢",
        "selection: 甲", "odds: 2.18", f"stake: {stake}",
        "channel: 测试渠道", "confirmed_at: 2026-07-16T10:00:00+08:00",
    ))


def test_confirmed_real_bet_uses_user_price_and_stake(tmp_path):
    target = persist(parse_body(body()), "42", tmp_path)
    row = json.loads(target.read_text(encoding="utf-8"))
    assert row["status"] == "locked"
    assert row["odds"] == 2.18
    assert row["stake"] == 12.34
    assert row["real_execution"] is True


def test_real_bet_rejects_below_platform_minimum():
    with pytest.raises(ValueError, match="不得低于2.00元"):
        parse_body(body("1.99"))

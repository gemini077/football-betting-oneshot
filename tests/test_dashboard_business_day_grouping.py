import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from scripts import prediction_dashboard as mod


def fixture(date, league="Europa", home="A", away="B"):
    return {"business_date": date, "competition": league, "home": home, "away": away}


def test_same_league_on_two_dates_gets_two_sections_in_input_order():
    cards = [fixture("2026-10-15", home="First"), fixture("2026-10-16", home="Second")]
    html = mod._league_groups_html(cards)
    assert html.count('class="league-group"') == 2
    assert html.index('data-business-date="2026-10-15"') < html.index('data-business-date="2026-10-16"')
    assert html.index("First") < html.index("Second")


def test_date_and_competition_attributes_and_heading_are_escaped():
    html = mod._league_groups_html([fixture('2026-10-15"<x>', 'A&<B')])
    assert 'data-business-date="2026-10-15&amp;quot;&lt;x&gt;"' in html or 'data-business-date="2026-10-15&quot;&lt;x&gt;"' in html
    assert 'data-league="A&amp;&lt;B"' in html
    assert "A&amp;&lt;B" in html


def test_missing_card_date_uses_top_level_default_date():
    html = mod._league_groups_html([fixture(None)], default_business_date="2026-10-16")
    assert 'data-business-date="2026-10-16"' in html
    assert "\u7ade\u5f69\u65e5 10\u670816\u65e5 \u00b7 Europa" in html


def test_missing_date_without_default_is_not_inferred():
    html = mod._league_groups_html([fixture(None)])
    assert 'data-business-date=""' in html
    assert "???" not in html


def test_projection_copies_business_date_alias_without_mutating_input():
    src = {"businessDate": "2026-10-15", "league": "Europa", "homeTeam": "H", "awayTeam": "A"}
    before = dict(src)
    projected = mod._fixture_projection(src)
    assert projected["business_date"] == "2026-10-15"
    assert src == before
    src2 = {"business_date": "2026-10-16"}
    assert mod._fixture_projection(src2)["business_date"] == "2026-10-16"


def test_render_uses_period_title_only_when_next_day_fixture_count_positive():
    common = {"business_date": "2026-10-15", "fixtures": [], "summary": {"fixture_count": 0}}
    multi = mod.render_dashboard({**common, "summary": {"fixture_count": 0, "next_business_date_fixture_count": 1}})
    single = mod.render_dashboard(common)
    assert "<h1>\u672c\u671f\u6bd4\u8d5b</h1>" in multi and "<strong>\u672c\u671f\u6bd4\u8d5b</strong>" in multi
    assert "<h1>\u4eca\u65e5\u6bd4\u8d5b</h1>" in single and "<strong>\u4eca\u65e5\u6bd4\u8d5b</strong>" in single


def test_grouping_does_not_mutate_cards_or_probability_values():
    card = fixture("2026-10-15")
    card["probabilities"] = {"home": 0.42, "draw": 0.3, "away": 0.28}
    before = {**card, "probabilities": dict(card["probabilities"])}
    mod._league_groups_html([card])
    assert card == before
    assert card["probabilities"] == {"home": 0.42, "draw": 0.3, "away": 0.28}

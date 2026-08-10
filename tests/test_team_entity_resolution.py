from pathlib import Path

from scripts.football_data.entity_resolution import TeamEntityResolver


ROOT = Path(__file__).resolve().parents[1]


def resolver():
    return TeamEntityResolver(ROOT / "data" / "football_data" / "team_alias_registry.json")


def test_reviewed_english_and_chinese_aliases_resolve_without_fuzzy_matching():
    value = resolver()
    cases = [
        ("Manchester Utd", "team:manchester-united"),
        ("曼联", "team:manchester-united"),
        ("Inter", "team:inter-milan"),
        ("Internazionale", "team:inter-milan"),
        ("国际米兰", "team:inter-milan"),
        ("PSG", "team:paris-saint-germain"),
        ("巴黎圣日耳曼", "team:paris-saint-germain"),
    ]
    for name, expected in cases:
        result = value.resolve_team("fixture", name)
        assert result.canonical_team_id == expected
        assert result.resolution_status == "resolved"
        assert result.resolution_method in {"exact_alias", "normalized_alias"}


def test_provider_id_exact_is_stronger_than_name_and_is_recorded():
    result = resolver().resolve_team(
        "fixture",
        "Manchester City",
        provider_team_id="fixture:manchester-city",
    )
    assert result.canonical_team_id == "team:manchester-city"
    assert result.resolution_method == "provider_id_exact"
    assert result.confidence == 1.0


def test_dangerous_generic_names_never_confirm_a_team():
    value = resolver()
    for name in ("United", "City", "Racing", "Sporting", "National", "Central"):
        result = value.resolve_team("unknown-provider", name)
        assert result.canonical_team_id is None
        assert result.resolution_status == "unresolved"
        assert result.resolution_method == "unresolved"


def test_full_city_names_are_contextual_and_do_not_cross_merge():
    value = resolver()
    assert value.resolve_team("fixture", "Manchester City").canonical_team_id == "team:manchester-city"
    assert value.resolve_team("fixture", "Melbourne City").canonical_team_id == "team:melbourne-city"
    assert value.resolve_team("fixture", "New York City").canonical_team_id == "team:new-york-city"
    assert value.resolve_team("fixture", "Manchester City", country="Australia").canonical_team_id is None


def test_senior_reserve_women_and_youth_entities_do_not_cross_merge():
    value = resolver()
    assert value.resolve_team("fixture", "Barcelona").canonical_team_id == "team:barcelona"
    assert value.resolve_team("fixture", "Barcelona B").canonical_team_id == "team:barcelona-b"
    assert value.resolve_team("fixture", "Barcelona Women").canonical_team_id == "team:barcelona-women"
    assert value.resolve_team("fixture", "Barcelona U19").canonical_team_id == "team:barcelona-u19"
    assert value.resolve_team("fixture", "Barcelona", team_level="reserve").canonical_team_id is None
    assert value.resolve_team("fixture", "Barcelona", gender="female").canonical_team_id is None

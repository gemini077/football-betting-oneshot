from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import scripts.recent_form_cache as cache_module
from scripts.recent_form_cache import build_recent_form
from scripts.football_data.providers.openfootball import parse_football_txt_rows


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "football_data" / "openfootball" / "south_america_brazil_source_manifest.json"
EVIDENCE_PATH = ROOT / "data" / "football_data" / "openfootball" / "south_america_brazil_identity_evidence.json"
CROSSWALK_PATH = ROOT / "data" / "football_data" / "verified_project_provider_crosswalk.json"
BRAZIL_FIXTURE = "\u5df4\u897f\u676f"
INTERNACIONAL = "team:brazil:internacional"
GREMIO = "team:brazil:gremio"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _rows_fixture() -> str:
    lines = ["= Brazil Brasileiro Serie A 2026"]
    for day in range(1, 7):
        lines.extend(
            [
                f"Sat Aug {day} 2026",
                f"  18:00 SC Internacional v Opponent {day} 1-0",
                f"  20:00 Opponent {day} v Gr\u00eamio FBPA 0-1",
            ]
        )
    lines.extend(
        [
            "Fri Aug 28 2026",
            "  18:00 SC Internacional v Gr\u00eamio FBPA 9-9",
        ]
    )
    return "\n".join(lines) + "\n"


def test_brazil_manifest_reuses_exact_canonical_ids_and_provider_names():
    manifest = _manifest()
    targets = {row["canonical_team_id"]: row for row in manifest["targets"]}
    assert targets[INTERNACIONAL]["provider_team_names"] == ["SC Internacional"]
    assert targets[GREMIO]["provider_team_names"] == ["Gr\u00eamio FBPA"]
    assert all("?" not in name and "\ufffd" not in name for row in manifest["sources"] for name in [row["provider_competition_name"]])
    assert all("?" not in name and "\ufffd" not in name for target in targets.values() for name in target["provider_team_names"])
    assert manifest["repository"] == "openfootball/south-america"
    assert manifest["allowed_fixture_competition_names"] == [BRAZIL_FIXTURE]
    assert manifest["allowed_history_competition_keys"] == ["brazil-serie-a"]

    crosswalk = json.loads(CROSSWALK_PATH.read_text(encoding="utf-8"))["mappings"]
    for canonical_id in (INTERNACIONAL, GREMIO):
        assert any(row["canonical_team_id"] == canonical_id and row["verified"] is True for row in crosswalk)
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))["teams"]
    assert {(row["provider_team_name"], row["canonical_team_id"]) for row in evidence} == {
        ("SC Internacional", INTERNACIONAL),
        ("Gr\u00eamio FBPA", GREMIO),
    }
    assert all(row["verified"] is True and row["resolution_method"] == "existing_crosswalk" for row in evidence)


def test_brazil_exact_provider_parser_builds_four_form_blocks_without_future_leakage():
    manifest = _manifest()
    targets = cache_module._reviewed_targets(manifest)
    raw = _rows_fixture()
    rows = parse_football_txt_rows(raw)
    records = cache_module._build_provider_records(
        [{"source_file": "brazil/2026_br1.txt", "provider_season_id": "2026", "competition_key": "brazil-serie-a", "raw_text": raw}],
        targets,
    )
    assert len(rows) == 13
    assert len(records) == 14
    built = build_recent_form(
        records,
        home_team_id=INTERNACIONAL,
        away_team_id=GREMIO,
        cutoff_at="2026-08-27T00:00:00Z",
    )
    assert built is not None
    assert all(row["kickoff_at"] < "2026-08-27T00:00:00Z" for row in built["records"])
    assert all(built["recent_form"][key]["matches"] > 0 for key in ("home_overall", "home_home", "away_overall", "away_away"))


def test_brazil_demand_requires_exact_targets_and_fixture_allowlist():
    manifest = _manifest()
    future = "2026-08-27T12:00:00Z"
    base = {"match_id": "brazil-1", "home": "\u5df4\u897f\u56fd\u9645", "away": "\u683c\u96f7\u7c73\u5965", "kickoff": future}
    accepted = cache_module._manifest_demand(manifest, [{**base, "league": BRAZIL_FIXTURE}], datetime(2026, 8, 26, 12, tzinfo=timezone.utc))
    assert len(accepted) == 1
    assert not cache_module._manifest_demand(manifest, [{**base, "league": "Brazil Serie A"}], datetime(2026, 8, 26, 12, tzinfo=timezone.utc))
    unknown = {**base, "home": "Internacional RS", "league": BRAZIL_FIXTURE}
    assert not cache_module._manifest_demand(manifest, [unknown], datetime(2026, 8, 26, 12, tzinfo=timezone.utc))


def test_default_manifest_set_keeps_spain_and_brazil_isolated():
    paths = cache_module._manifest_paths(None)
    assert [path.name for path in paths] == ["espana_source_manifest.json", "south_america_brazil_source_manifest.json"]
    spain = json.loads(paths[0].read_text(encoding="utf-8"))
    brazil = json.loads(paths[1].read_text(encoding="utf-8"))
    assert any(row["canonical_team_id"] == "team:barcelona" for row in spain["targets"])
    assert not any(row["canonical_team_id"] == "team:barcelona" for row in brazil["targets"])
    assert cache_module._reviewed_targets(brazil) == brazil["targets"]
    assert {row["canonical_team_id"] for row in cache_module._reviewed_targets(spain)} == {
        row["canonical_team_id"] for row in spain["targets"]
    }

from pathlib import Path

from scripts.team_crest_enrichment import (
    enrich_dashboard_crests,
    parse_nowscore_analysis_crests,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"fixture-png"


def page(
    *,
    match_id: int = 9001,
    home_id: int = 11,
    away_id: int = 22,
    home: str = "Home FC",
    away: str = "Away FC",
    home_src: str | None = None,
    away_src: str | None = None,
) -> str:
    home_src = home_src or f"//info.nowscore.com/Image/team/images/{home_id}/home.png"
    away_src = away_src or f"//info.nowscore.com/Image/team/images/{away_id}/away.png"
    return f"""
    <input type="hidden" id="hide_scheduleId" value="{match_id}" />
    <div id="home">
      <a class="name" href="//info.nowscore.com/cn/team/Summary.aspx?teamid={home_id}">{home}(\u4e3b)</a>
      <div class="teamimg"><img src="{home_src}" /></div>
    </div>
    <div id="guest">
      <div class="teamimg"><img src="{away_src}" /></div>
      <a class="name" href="//info.nowscore.com/cn/team/Summary.aspx?teamid={away_id}">{away}</a>
    </div>
    """


def test_parser_extracts_ordered_team_ids_and_crest_urls():
    result = parse_nowscore_analysis_crests(
        page(),
        expected_nowscore_id=9001,
        expected_home="Home FC",
        expected_away="Away FC",
    )

    assert result["status"] == "VERIFIED"
    assert result["home"]["team_id"] == "11"
    assert result["away"]["team_id"] == "22"
    assert result["home"]["crest_url"] == "https://info.nowscore.com/Image/team/images/11/home.png"
    assert result["away"]["crest_url"] == "https://info.nowscore.com/Image/team/images/22/away.png"


def test_parser_rejects_reversed_page_identity():
    result = parse_nowscore_analysis_crests(
        page(home="Away FC", away="Home FC"),
        expected_nowscore_id=9001,
        expected_home="Home FC",
        expected_away="Away FC",
    )

    assert result["status"] == "UNVERIFIED"
    assert "ORIENTATION_CONFLICT" in result["reasons"]


def test_enrichment_uses_local_assets_and_deduplicates_team_downloads(tmp_path: Path):
    pages = {
        "https://live.nowscore.com/analysis/9001cn.html": page(),
        "https://live.nowscore.com/analysis/9002cn.html": page(
            match_id=9002,
            home_id=22,
            away_id=33,
            home="Away FC",
            away="Third FC",
            home_src="//info.nowscore.com/Image/team/images/22/away.png",
            away_src="//info.nowscore.com/Image/team/images/33/third.png",
        ),
    }
    calls: list[str] = []

    def fetch(url: str, timeout: float = 30) -> bytes:
        calls.append(url)
        if url in pages:
            return pages[url].encode("utf-8")
        return PNG + url.encode("ascii")

    dashboard = {
        "business_date": "2026-09-09",
        "fixtures": [
            {"match_id": "9001", "home": "Home FC", "away": "Away FC", "nowscore_id": 9001},
            {"match_id": "9002", "home": "Away FC", "away": "Third FC", "nowscore_id": 9002},
        ],
    }
    result = enrich_dashboard_crests(
        dashboard,
        asset_root=tmp_path / "assets" / "team-crests",
        fetcher=fetch,
    )

    assert result["fixtures"][0]["home_crest"].startswith("../assets/team-crests/")
    assert result["fixtures"][0]["away_crest"] == result["fixtures"][1]["home_crest"]
    assert len(list((tmp_path / "assets" / "team-crests").iterdir())) == 3
    assert calls.count("https://info.nowscore.com/Image/team/images/22/away.png") == 1


def test_enrichment_failures_preserve_fallback_and_do_not_raise(tmp_path: Path):
    def fail(_url: str, timeout: float = 30) -> bytes:
        raise OSError("fixture network failure")

    dashboard = {
        "business_date": "2026-09-09",
        "fixtures": [{"match_id": "9001", "home": "Home FC", "away": "Away FC", "nowscore_id": 9001}],
    }

    result = enrich_dashboard_crests(
        dashboard,
        asset_root=tmp_path / "assets" / "team-crests",
        fetcher=fail,
    )

    assert result["fixtures"][0].get("home_crest") is None
    assert result["fixtures"][0].get("away_crest") is None
    assert not (tmp_path / "assets" / "team-crests").exists()


def test_invalid_image_bytes_preserve_fallback_and_do_not_publish_html(tmp_path: Path):
    def fetch(url: str, timeout: float = 30) -> bytes:
        if "/analysis/9001cn.html" in url:
            return page().encode("utf-8")
        return b"not-an-image"

    dashboard = {
        "business_date": "2026-09-09",
        "fixtures": [{"match_id": "9001", "home": "Home FC", "away": "Away FC", "nowscore_id": 9001}],
    }

    result = enrich_dashboard_crests(
        dashboard,
        asset_root=tmp_path / "assets" / "team-crests",
        fetcher=fetch,
    )

    assert result["fixtures"][0].get("home_crest") is None
    assert result["fixtures"][0].get("away_crest") is None
    assert not (tmp_path / "assets" / "team-crests").exists()


def test_enrichment_can_resolve_nowscore_id_from_universe(tmp_path: Path):
    calls: list[str] = []

    def fetch(url: str, timeout: float = 30) -> bytes:
        calls.append(url)
        if "analysis/9001cn.html" in url:
            return page().encode("utf-8")
        return PNG + url.encode("ascii")

    dashboard = {
        "business_date": "2026-09-09",
        "fixtures": [{"match_id": "9001", "home": "Home FC", "away": "Away FC"}],
    }
    universe = {
        "fixtures": [{"matchId": "9001", "nowscoreId": 9001, "homeTeam": "Home FC", "awayTeam": "Away FC"}]
    }

    result = enrich_dashboard_crests(
        dashboard,
        universe=universe,
        asset_root=tmp_path / "assets" / "team-crests",
        fetcher=fetch,
    )

    assert result["fixtures"][0]["nowscore_id"] == 9001
    assert calls[0] == "https://live.nowscore.com/analysis/9001cn.html"
    assert result["fixtures"][0]["home_crest"]

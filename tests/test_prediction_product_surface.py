from pathlib import Path

from scripts import build_public_site


def test_public_site_home_targets_prediction_dashboard_and_keeps_legacy_workspace(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data" / "prediction_dashboard").mkdir(parents=True)
    (root / "data" / "match_workspace").mkdir(parents=True)
    (root / "data" / "prediction_dashboard" / "latest.html").write_text("dashboard", encoding="utf-8")
    (root / "data" / "match_workspace" / "latest.html").write_text("legacy", encoding="utf-8")
    monkeypatch.setattr(build_public_site, "ROOT", root)

    output = build_public_site.build(root / "site")

    index = output.read_text(encoding="utf-8")
    assert "prediction_dashboard/latest.html" in index
    assert (root / "site" / "prediction_dashboard" / "latest.html").read_text(encoding="utf-8") == "dashboard"
    assert (root / "site" / "match_workspace" / "latest.html").read_text(encoding="utf-8") == "legacy"

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_public_site  # noqa: E402


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False))


def contract(match_id: str = "1001") -> dict:
    return {
        "identity": {
            "match_id": match_id,
            "business_date": "2026-08-25",
            "competition": "Fixture League",
            "match_num": "001",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_at": "2026-08-25T20:00:00+08:00",
        },
        "status": {"code": "FROZEN", "reason_text": ""},
        "hero": {
            "primary_score": "1-0",
            "neighbor_scores": ["1-1"],
            "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "summary": "Fixture summary",
            "script": "Fixture script",
        },
        "timestamps": {"prediction_frozen_at": "2026-08-25T12:00:00+08:00"},
        "model": {"probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2}},
        "evidence": {},
    }


def make_source_tree(root: Path, *, include_contract: bool = True) -> None:
    data = root / "data"
    write_text(
        data / "prediction_dashboard" / "latest.html",
        """<a href=\"../match_workspace/latest.html\">workspace</a>
        <a href=\"../analysis_reports/current/prematch.html\">prematch</a>
        <a href=\"../postmatch_reports/review.html\">review</a>
        <a href=\"../matches/1001/\">detail</a>""",
    )
    write_json(
        data / "prediction_dashboard" / "latest.json",
        {
            "business_date": "2026-08-25",
            "fixtures": [
                {
                    "match_id": "1001",
                    "home": "Home FC",
                    "away": "Away FC",
                    "status": "FROZEN",
                    "competition": "Fixture League",
                    "kickoff": "2026-08-25T20:00:00+08:00",
                    "prediction": {"unique_score": "1-0"},
                }
            ],
        },
    )
    write_text(
        data / "match_workspace" / "latest.html",
        '<script>const DATA={"postmatch_dashboard_url":"../postmatch_dashboard/latest.html"}</script>',
    )
    write_json(data / "match_workspace" / "latest.json", {"history": [], "completed": []})
    write_text(
        data / "postmatch_dashboard" / "latest.html",
        '<a href="../postmatch_reports/review.html">review</a>',
    )
    write_text(data / "analysis_reports" / "current" / "prematch.html", "prematch")
    write_text(data / "postmatch_reports" / "review.html", "review")
    write_text(data / "match_workspace" / "old" / "raw.json", "do not publish")
    write_text(data / "postmatch_dashboard" / "old" / "raw.json", "do not publish")
    write_text(data / "analysis_reports" / "old" / "raw.json", "do not publish")
    write_text(data / "postmatch_reports" / "internal.txt", "do not publish")
    if include_contract:
        write_json(data / "match_analysis" / "2026-08-25" / "1001" / "latest.json", contract())


def test_build_is_a_selective_read_only_projection(tmp_path, monkeypatch):
    make_source_tree(tmp_path)
    output = tmp_path / "site"
    source_contract = tmp_path / "data" / "match_analysis" / "2026-08-25" / "1001" / "latest.json"
    before = hashlib.sha256(source_contract.read_bytes()).hexdigest()
    copy_calls = []
    real_copy2 = build_public_site.shutil.copy2

    def record_copy(source, target, *args, **kwargs):
        copy_calls.append(Path(source).relative_to(tmp_path).as_posix())
        return real_copy2(source, target, *args, **kwargs)

    monkeypatch.setattr(build_public_site, "ROOT", tmp_path)
    monkeypatch.setattr(build_public_site.shutil, "copy2", record_copy)
    monkeypatch.setattr(
        build_public_site.shutil,
        "copytree",
        lambda *args, **kwargs: pytest.fail("recursive publication is forbidden"),
    )

    build_public_site.build(output)

    assert (output / "prediction_dashboard/latest.html").is_file()
    assert (output / "prediction_dashboard/latest.json").is_file()
    assert (output / "match_workspace/latest.html").is_file()
    assert (output / "postmatch_dashboard/latest.html").is_file()
    assert (output / "analysis_reports/current/prematch.html").is_file()
    assert (output / "postmatch_reports/review.html").is_file()
    detail = output / "matches/1001/index.html"
    assert detail.is_file()
    assert "Home FC" in detail.read_text(encoding="utf-8")
    assert not (output / "match_workspace/old/raw.json").exists()
    assert not (output / "postmatch_dashboard/old/raw.json").exists()
    assert not (output / "analysis_reports/old/raw.json").exists()
    assert not (output / "postmatch_reports/internal.txt").exists()
    assert len(copy_calls) == 7
    assert hashlib.sha256(source_contract.read_bytes()).hexdigest() == before


def test_build_renders_missing_contract_from_current_dashboard_fixture_without_writing_data(tmp_path, monkeypatch):
    make_source_tree(tmp_path, include_contract=False)
    output = tmp_path / "site"
    monkeypatch.setattr(build_public_site, "ROOT", tmp_path)

    build_public_site.build(output)

    detail = output / "matches/1001/index.html"
    assert detail.is_file()
    assert "Home FC" in detail.read_text(encoding="utf-8")
    assert not (tmp_path / "data" / "match_analysis").exists()


def test_contract_lookup_reads_only_linked_match_ids(tmp_path, monkeypatch):
    make_source_tree(tmp_path)
    unrelated = tmp_path / "data" / "match_analysis" / "2026-08-25" / "9999" / "latest.json"
    write_text(unrelated, "not json")
    read_paths = []
    real_read_json = build_public_site._read_json

    def record_read(path):
        read_paths.append(Path(path))
        return real_read_json(path)

    monkeypatch.setattr(build_public_site, "ROOT", tmp_path)
    monkeypatch.setattr(build_public_site, "_read_json", record_read)

    build_public_site.build(tmp_path / "site")

    assert unrelated not in read_paths


def test_build_fails_loudly_when_linked_public_report_is_missing(tmp_path, monkeypatch):
    make_source_tree(tmp_path)
    (tmp_path / "data" / "postmatch_reports" / "review.html").unlink()
    monkeypatch.setattr(build_public_site, "ROOT", tmp_path)

    with pytest.raises(FileNotFoundError, match="postmatch_reports/review.html"):
        build_public_site.build(tmp_path / "site")


def test_build_propagates_current_prediction_quality_warning_to_linked_detail(tmp_path, monkeypatch):
    make_source_tree(tmp_path)
    dashboard_path = tmp_path / "data" / "prediction_dashboard" / "latest.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    dashboard["prediction_quality_health"] = {
        "status": "ALERT",
        "scope": "current_serving",
        "business_date": "2026-08-25",
        "runtime_cycle_finished_at": "2026-08-25T12:01:00+08:00",
    }
    write_json(dashboard_path, dashboard)
    monkeypatch.setattr(build_public_site, "ROOT", tmp_path)

    build_public_site.build(tmp_path / "site")

    detail = (tmp_path / "site" / "matches/1001/index.html").read_text(encoding="utf-8")
    assert "\u9884\u6d4b\u8d28\u91cf\u5f02\u5e38" in detail
    assert "\u4eca\u65e5\u6bd4\u5206\u9884\u6d4b\u51fa\u73b0\u5f02\u5e38\u96c6\u4e2d\uff0c\u5f53\u524d\u9884\u6d4b\u4ecd\u4fdd\u7559\u4f9b\u89c2\u5bdf\u3002" in detail

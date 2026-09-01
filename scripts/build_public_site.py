#!/usr/bin/env python3
"""Build the static GitHub Pages artifact from generated public projections."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from typing import Any

try:
    from .match_detail import render_match_detail
except ImportError:  # pragma: no cover - direct script execution path.
    from match_detail import render_match_detail


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "site"
DATA_PUBLIC_ROOTS = {"analysis_reports", "postmatch_reports", "postmatch_dashboard", "match_workspace"}
PUBLIC_ENTRYPOINTS = (
    "prediction_dashboard/latest.html",
    "prediction_dashboard/latest.json",
    "match_workspace/latest.html",
    "match_workspace/latest.json",
    "postmatch_dashboard/latest.html",
)
EMBEDDED_REFERENCE_RE = re.compile(
    r"(?:\.\./)+(?:analysis_reports|postmatch_reports|postmatch_dashboard|match_workspace)/[^\"'\\\s<>]+\.html"
    r"|(?:\.\./)+matches/[A-Za-z0-9._~-]+/"
)
MATCH_LINK_RE = re.compile(r"(?:\.\./)+matches/([A-Za-z0-9._~-]+)/")


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.references.append(value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid required JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"required JSON artifact is not an object: {path}")
    return payload


def _copy_file(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"required public artifact is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _public_reference(page: Path, reference: str, data_root: Path) -> Path | None:
    parsed = urlsplit(unquote(reference))
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith(("#", "javascript:")):
        return None
    candidate = (page.parent / parsed.path).resolve()
    try:
        relative = candidate.relative_to(data_root.resolve())
    except ValueError:
        return None
    if not relative.parts or relative.parts[0] not in DATA_PUBLIC_ROOTS:
        return None
    if candidate.suffix.lower() != ".html":
        return None
    return candidate


def _page_references(page: Path, data_root: Path) -> tuple[set[Path], set[str]]:
    text = page.read_text(encoding="utf-8", errors="replace")
    parser = _ReferenceParser()
    parser.feed(text)
    references = set(parser.references)
    references.update(EMBEDDED_REFERENCE_RE.findall(text))
    linked_pages: set[Path] = set()
    match_ids: set[str] = set()
    for reference in references:
        match = MATCH_LINK_RE.search(reference)
        if match:
            match_ids.add(match.group(1))
        linked = _public_reference(page, reference, data_root)
        if linked is not None:
            linked_pages.add(linked)
    return linked_pages, match_ids


def _copy_linked_public_pages(data_root: Path, output: Path) -> set[str]:
    queue = [data_root / relative for relative in PUBLIC_ENTRYPOINTS if relative.endswith(".html")]
    copied: set[Path] = set()
    match_ids: set[str] = set()
    while queue:
        source = queue.pop()
        if source in copied:
            continue
        if not source.is_file():
            relative = source.relative_to(data_root).as_posix()
            raise FileNotFoundError(f"required linked public page is missing: {relative}")
        _copy_file(source, output / source.relative_to(data_root))
        copied.add(source)
        linked_pages, page_match_ids = _page_references(source, data_root)
        match_ids.update(page_match_ids)
        queue.extend(linked_pages - copied)
    return match_ids


def _fixture_contract(fixture: dict[str, Any], business_date: str) -> dict[str, Any]:
    prediction = fixture.get("prediction") if isinstance(fixture.get("prediction"), dict) else {}
    result = fixture.get("result") if isinstance(fixture.get("result"), dict) else {}
    return {
        "identity": {
            "match_id": fixture.get("match_id"),
            "business_date": fixture.get("business_date") or business_date,
            "competition": fixture.get("competition"),
            "match_num": fixture.get("match_num"),
            "home": fixture.get("home"),
            "away": fixture.get("away"),
            "kickoff_at": fixture.get("kickoff"),
        },
        "status": {
            "code": fixture.get("status") or "PENDING",
            "reason_code": fixture.get("reason_code"),
            "reason_text": fixture.get("reason_text"),
        },
        "hero": {
            "primary_score": prediction.get("unique_score") or prediction.get("score_top1"),
            "neighbor_scores": prediction.get("neighbor_scores") or [],
            "probabilities": prediction.get("probabilities") or {},
            "summary": prediction.get("summary"),
            "script": prediction.get("script"),
        },
        "model": prediction,
        "result": result,
        "evidence": {"source_quality": fixture.get("source_quality") or {}},
        "governance": {"pilot_excluded": fixture.get("pilot_excluded", False)},
        "timestamps": {"prediction_frozen_at": fixture.get("prediction_frozen_at")},
        "analysis_sections": [],
    }


def _match_contracts(data_root: Path, dashboard: dict[str, Any], match_ids: set[str]) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    business_date = str(dashboard.get("business_date") or "")
    fixtures: dict[str, dict[str, Any]] = {}
    for fixture in dashboard.get("fixtures") or []:
        if isinstance(fixture, dict):
            match_id = str(fixture.get("match_id") or "")
            if match_id in match_ids:
                fixtures[match_id] = fixture
    contract_root = data_root / "match_analysis"
    for match_id in sorted(match_ids):
        for path in sorted(contract_root.glob(f"*/{match_id}/latest.json")):
            try:
                payload = _read_json(path)
            except ValueError:
                continue
            identity = payload.get("identity") or {}
            if str(identity.get("match_id") or "") == match_id:
                contracts[match_id] = payload
                break
    for match_id in sorted(match_ids - contracts.keys()):
        fixture = fixtures.get(match_id)
        if fixture is not None:
            contracts[match_id] = _fixture_contract(fixture, business_date)
    return contracts


def _build_match_pages(data_root: Path, output: Path, match_ids: set[str], dashboard: dict[str, Any]) -> None:
    contracts = _match_contracts(data_root, dashboard, match_ids)
    for match_id in sorted(match_ids):
        contract = contracts.get(match_id)
        if contract is None:
            raise FileNotFoundError(f"missing canonical match detail contract for linked match: {match_id}")
        contract = {
            **contract,
            "prediction_quality_health": dashboard.get("prediction_quality_health"),
        }
        target = output / "matches" / match_id / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_match_detail(contract), encoding="utf-8")


def build(output: Path, *, data_root: Path | None = None) -> Path:
    root = Path(data_root or ROOT)
    data_root = root / "data"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for relative in PUBLIC_ENTRYPOINTS:
        if relative.endswith(".json"):
            _copy_file(data_root / relative, output / relative)
    dashboard = _read_json(data_root / "prediction_dashboard" / "latest.json")
    match_ids = _copy_linked_public_pages(data_root, output)
    _build_match_pages(data_root, output, match_ids, dashboard)

    downloads = output / "downloads"
    downloads.mkdir(exist_ok=True)
    workbooks = sorted(
        (root / "outputs").glob("**/*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if workbooks:
        _copy_file(workbooks[0], downloads / workbooks[0].name)

    (output / ".nojekyll").write_text("", encoding="utf-8")
    (output / "index.html").write_text(
        """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="0;url=prediction_dashboard/latest.html">
  <title>Football Prediction Day</title>
</head>
<body>
  <p><a href="prediction_dashboard/latest.html">进入 Football Prediction Day</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )
    return output / "index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    print(build(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

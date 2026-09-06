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

try:
    from .formal_market_projection import project_frozen_formal_markets
except ImportError:  # pragma: no cover - direct script execution path.
    from formal_market_projection import project_frozen_formal_markets

try:
    from .change_awareness import build_prematch_change_awareness
except ImportError:  # pragma: no cover - direct script execution path.
    from change_awareness import build_prematch_change_awareness


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


def _linked_frozen_formal_markets(data_root: Path, fixture: dict[str, Any]) -> dict[str, Any] | None:
    if str(fixture.get("status") or "").upper() != "FROZEN":
        return None
    prediction_id = str(fixture.get("selected_prediction_id") or fixture.get("prediction_id") or "").strip()
    if not prediction_id or not re.fullmatch(r"[A-Za-z0-9._~-]+", prediction_id):
        return None
    path = data_root / "model_governance" / "predictions" / f"{prediction_id}.json"
    if not path.is_file():
        return None
    try:
        record = _read_json(path)
    except ValueError:
        return None
    if str(record.get("prediction_id") or "") != str(prediction_id):
        return None
    fixture_match_id = str(fixture.get("match_id") or "")
    record_match_id = str(record.get("match_id") or "")
    if fixture_match_id and record_match_id and fixture_match_id != record_match_id:
        return None
    return project_frozen_formal_markets(record)


def _prediction_records(data_root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    prediction_root = data_root / "model_governance" / "predictions"
    if not prediction_root.is_dir():
        return records
    for path in sorted(prediction_root.glob("*.json")):
        try:
            record = _read_json(path)
        except ValueError:
            continue
        prediction_id = str(record.get("prediction_id") or "").strip()
        if prediction_id:
            records[prediction_id] = record
    return records


def _linked_prediction_record(data_root: Path, fixture: dict[str, Any]) -> dict[str, Any] | None:
    prediction_id = str(fixture.get("selected_prediction_id") or fixture.get("prediction_id") or "").strip()
    if not prediction_id or not re.fullmatch(r"[A-Za-z0-9._~-]+", prediction_id):
        return None
    path = data_root / "model_governance" / "predictions" / f"{prediction_id}.json"
    if not path.is_file():
        return None
    try:
        record = _read_json(path)
    except ValueError:
        return None
    if str(record.get("prediction_id") or "") != prediction_id:
        return None
    fixture_match_id = str(fixture.get("match_id") or "")
    record_match_id = str(record.get("match_id") or "")
    if fixture_match_id and record_match_id and fixture_match_id != record_match_id:
        return None
    return record


def _change_awareness_for_fixture(
    data_root: Path,
    fixture: dict[str, Any],
    *,
    records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = _linked_prediction_record(data_root, fixture)
    all_records = records if records is not None else _prediction_records(data_root)
    identity = {
        "match_id": fixture.get("match_id"),
        "match_key": fixture.get("match_key") or fixture.get("matchKey"),
        "home": fixture.get("home"),
        "away": fixture.get("away"),
        "kickoff_at": fixture.get("kickoff") or fixture.get("kickoff_at"),
    }
    return build_prematch_change_awareness(
        records=all_records.values(),
        current_record=current,
        identity=identity,
    )


def _formal_markets_for_fixture(data_root: Path, fixture: dict[str, Any]) -> dict[str, Any] | None:
    linked = _linked_frozen_formal_markets(data_root, fixture)
    if linked is not None:
        return linked
    prediction = fixture.get("prediction") if isinstance(fixture.get("prediction"), dict) else {}
    summary = prediction.get("formal_markets")
    if isinstance(summary, dict):
        return summary
    if str(fixture.get("status") or "").upper() == "FROZEN":
        return project_frozen_formal_markets(None)
    return None


def _fixture_contract(
    fixture: dict[str, Any],
    business_date: str,
    *,
    formal_markets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prediction = fixture.get("prediction") if isinstance(fixture.get("prediction"), dict) else {}
    result = fixture.get("result") if isinstance(fixture.get("result"), dict) else {}
    source_quality = fixture.get("source_quality") if isinstance(fixture.get("source_quality"), dict) else {}
    if not source_quality and prediction.get("source_references"):
        source_quality = {"source_references": prediction.get("source_references")}
    prediction_frozen_at = (
        fixture.get("selected_freeze_created_at")
        or fixture.get("prediction_frozen_at")
        or prediction.get("freeze_created_at")
        or prediction.get("freeze_at")
    )
    source_cutoff_at = (
        fixture.get("selected_source_cutoff_at")
        or fixture.get("source_cutoff_at")
        or prediction.get("source_cutoff_at")
        or prediction.get("model_input_as_of_at")
    )
    fallback_formal_markets = formal_markets
    if fallback_formal_markets is None:
        fallback_formal_markets = prediction.get("formal_markets")
    if fallback_formal_markets is None and str(fixture.get("status") or "").upper() == "FROZEN":
        fallback_formal_markets = project_frozen_formal_markets(None)
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
        "formal_markets": fallback_formal_markets,
        "result": result,
        "evidence": {"source_quality": source_quality},
        "governance": {"pilot_excluded": fixture.get("pilot_excluded", False)},
        "timestamps": {
            "prediction_frozen_at": prediction_frozen_at,
            "source_cutoff_at": source_cutoff_at,
        },
        "analysis_sections": [],
    }


def _match_contracts(data_root: Path, dashboard: dict[str, Any], match_ids: set[str]) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    business_date = str(dashboard.get("business_date") or "")
    prediction_records = _prediction_records(data_root)
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
                fixture = fixtures.get(match_id)
                if fixture is not None and not isinstance(payload.get("formal_markets"), dict):
                    payload = {
                        **payload,
                        "formal_markets": _formal_markets_for_fixture(data_root, fixture),
                    }
                if fixture is not None:
                    payload = {
                        **payload,
                        "change_awareness": _change_awareness_for_fixture(
                            data_root,
                            fixture,
                            records=prediction_records,
                        ),
                    }
                contracts[match_id] = payload
                break
    for match_id in sorted(match_ids - contracts.keys()):
        fixture = fixtures.get(match_id)
        if fixture is not None:
            formal_markets = _formal_markets_for_fixture(data_root, fixture)
            contracts[match_id] = _fixture_contract(
                fixture,
                business_date,
                formal_markets=formal_markets,
            )
            contracts[match_id]["change_awareness"] = _change_awareness_for_fixture(
                data_root,
                fixture,
                records=prediction_records,
            )
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

"""Persist detailed identity evidence outside Git and compact identity truth in Git."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .data_home import identity_detail_path
from .storage import content_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CROSSWALK_PATH = ROOT / "data" / "football_data" / "verified_identity_crosswalk.json"
DEFAULT_REVIEW_QUEUE_PATH = ROOT / "data" / "football_data" / "identity_review_queue.json"
MAX_COMPACT_SOURCE_REFS = 8


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_refs(evidence: Mapping[str, Any] | None) -> list[str]:
    refs: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                normalized_key = str(child_key).casefold()
                if (
                    normalized_key.endswith("source_ref")
                    or normalized_key in {"source_refs", "source_file", "source_url", "repository", "commit_sha"}
                ):
                    if isinstance(child_value, str) and child_value.strip():
                        refs.add(child_value.strip())
                    elif isinstance(child_value, Iterable) and not isinstance(child_value, (str, bytes, Mapping)):
                        refs.update(str(item).strip() for item in child_value if str(item).strip())
                else:
                    visit(child_value, normalized_key)
        elif isinstance(value, list):
            for item in value:
                visit(item, key)

    visit(evidence or {})
    return sorted(refs)


def _supporting_fixture_count(evidence: Mapping[str, Any] | None) -> int:
    if not evidence:
        return 0
    aligned = evidence.get("aligned_fixtures")
    if isinstance(aligned, list):
        return len(aligned)
    return int(evidence.get("aligned_match_count") or evidence.get("distinct_fixture_count") or 0)


def _evidence_digest(candidate: Mapping[str, Any]) -> str:
    return content_sha256(candidate.get("evidence") or {})


def _compact_mapping(mapping: Mapping[str, Any], *, verified_at: str) -> dict[str, Any]:
    evidence = mapping.get("evidence") if isinstance(mapping.get("evidence"), Mapping) else {}
    refs = _source_refs(evidence)
    return {
        "provider": mapping.get("provider"),
        "provider_team_id": mapping.get("provider_team_id"),
        "provider_team_name": mapping.get("provider_team_name"),
        "canonical_team_id": mapping.get("canonical_team_id"),
        "canonical_name": mapping.get("canonical_name"),
        "competition": mapping.get("competition_id"),
        "country": mapping.get("country"),
        "verified": True,
        "resolution_method": mapping.get("resolution_method"),
        "verification_method": mapping.get("verification_method"),
        "verification_evidence_digest": _evidence_digest(mapping),
        "source_refs": refs[:MAX_COMPACT_SOURCE_REFS],
        "source_ref_count": len(refs),
        "supporting_fixture_count": _supporting_fixture_count(evidence),
        "verified_at": verified_at,
    }


def _compact_review_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), Mapping) else {}
    refs = _source_refs(evidence)
    conflicts = candidate.get("conflicts")
    reason = conflicts if isinstance(conflicts, list) and conflicts else [
        str(candidate.get("verification_method") or candidate.get("resolution_method") or "review_required")
    ]
    return {
        "provider": candidate.get("provider"),
        "provider_team_id": candidate.get("provider_team_id"),
        "provider_team_name": candidate.get("provider_team_name"),
        "candidate_canonical_team_ids": [candidate["canonical_team_id"]] if candidate.get("canonical_team_id") else [],
        "candidate_canonical_names": [candidate["canonical_name"]] if candidate.get("canonical_name") else [],
        "competition": candidate.get("competition_id"),
        "country": candidate.get("country"),
        "status": candidate.get("status") or "UNRESOLVED",
        "reason": [str(item) for item in reason],
        "source_refs": refs[:MAX_COMPACT_SOURCE_REFS],
        "source_ref_count": len(refs),
        "verification_evidence_digest": _evidence_digest(candidate),
        "supporting_fixture_count": _supporting_fixture_count(evidence),
    }


def build_compact_identity_artifacts(
    identity_output: Mapping[str, Any],
    *,
    verified_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mappings = identity_output.get("provider_mappings") or []
    candidates = identity_output.get("candidates") or []
    crosswalk_rows = [
        _compact_mapping(mapping, verified_at=verified_at)
        for mapping in mappings
        if mapping.get("verified") is True and mapping.get("status") == "AUTO_VERIFIED"
    ]
    review_rows = [
        _compact_review_row(candidate)
        for candidate in candidates
        if candidate.get("status") != "AUTO_VERIFIED"
    ]
    crosswalk = {
        "contract_version": "verified_identity_crosswalk.v1",
        "generated_at": verified_at,
        "mapping_count": len(crosswalk_rows),
        "mappings": crosswalk_rows,
    }
    review_queue = {
        "contract_version": "identity_review_queue.v1",
        "generated_at": verified_at,
        "entry_count": len(review_rows),
        "entries": review_rows,
    }
    return crosswalk, review_queue


def persist_identity_artifacts(
    identity_output: Mapping[str, Any],
    *,
    generated_at: str,
    detail_path: str | Path | None = None,
    crosswalk_path: str | Path = DEFAULT_CROSSWALK_PATH,
    review_queue_path: str | Path = DEFAULT_REVIEW_QUEUE_PATH,
) -> dict[str, Any]:
    detail = Path(detail_path) if detail_path is not None else identity_detail_path()
    crosswalk, review_queue = build_compact_identity_artifacts(identity_output, verified_at=generated_at)
    _write_json(detail, identity_output)
    _write_json(Path(crosswalk_path), crosswalk)
    _write_json(Path(review_queue_path), review_queue)
    return {
        "detail_path": str(detail),
        "crosswalk_path": str(crosswalk_path),
        "review_queue_path": str(review_queue_path),
        "verified_mapping_count": crosswalk["mapping_count"],
        "review_queue_count": review_queue["entry_count"],
    }

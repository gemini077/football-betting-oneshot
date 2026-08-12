"""Read formal prediction exclusions without changing immutable records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXCLUSION_ROOT = BASE_DIR / "data" / "model_governance" / "prediction_exclusions"


def iter_exclusions(exclusion_root: Path = DEFAULT_EXCLUSION_ROOT) -> Iterable[dict[str, Any]]:
    """Yield valid exclusion artifacts; malformed artifacts fail closed."""
    root = exclusion_root if exclusion_root.is_absolute() else BASE_DIR / exclusion_root
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        ids = payload.get("prediction_ids")
        if not isinstance(ids, list):
            continue
        payload = dict(payload)
        payload["_artifact_path"] = str(path)
        yield payload


def exclusion_for(prediction_id: str, exclusion_root: Path = DEFAULT_EXCLUSION_ROOT) -> dict[str, Any] | None:
    wanted = str(prediction_id or "").strip()
    if not wanted:
        return None
    for payload in iter_exclusions(exclusion_root):
        if wanted in {str(item).strip() for item in payload.get("prediction_ids") or []}:
            return payload
    return None


def is_prediction_excluded(prediction_id: str, exclusion_root: Path = DEFAULT_EXCLUSION_ROOT) -> bool:
    """Return whether a prediction is excluded from formal prospective data."""
    return exclusion_for(prediction_id, exclusion_root) is not None


def excluded_prediction_ids(exclusion_root: Path = DEFAULT_EXCLUSION_ROOT) -> set[str]:
    ids: set[str] = set()
    for payload in iter_exclusions(exclusion_root):
        ids.update(str(item).strip() for item in payload.get("prediction_ids") or [] if str(item).strip())
    return ids

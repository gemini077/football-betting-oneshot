"""Minimal content-addressed JSON storage for normalized snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class SnapshotStore:
    """Write/read JSON snapshots addressed by their canonical content hash."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, value_or_digest: Mapping[str, Any] | str) -> Path:
        digest = value_or_digest if isinstance(value_or_digest, str) else content_sha256(value_or_digest)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.casefold()):
            raise ValueError("snapshot digest must be a 64-character hexadecimal SHA256")
        return self.root / f"{digest}.json"

    def put(self, value: Mapping[str, Any]) -> tuple[str, Path]:
        digest = content_sha256(value)
        path = self.path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_json_bytes(value) + b"\n"
        if path.exists() and path.read_bytes() != encoded:
            raise ValueError(f"content-addressed path collision: {path}")
        if not path.exists():
            path.write_bytes(encoded)
        return digest, path

    def get(self, digest: str) -> dict[str, Any]:
        path = self.path_for(digest)
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if content_sha256(value) != digest:
            raise ValueError(f"snapshot content hash mismatch: {path}")
        return value

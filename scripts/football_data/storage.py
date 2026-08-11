"""Small immutable JSON and DuckDB stores for the football data layer.

The JSON store remains useful for compact fixtures and registries. Bulk
historical results and pre-match strength snapshots use one local DuckDB file
per dataset so Git does not become a match database. The DuckDB records keep
the canonical JSON payload alongside query columns, preserving logical parity
with the previous content-addressed records.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

try:
    import duckdb
except ImportError:  # pragma: no cover - exercised by the explicit error path
    duckdb = None  # type: ignore[assignment]


class DatasetNotAvailableError(FileNotFoundError):
    """Raised when a required local bulk dataset has not been rebuilt."""

    code = "DATASET_NOT_AVAILABLE"

    def __init__(self, path: str | Path) -> None:
        super().__init__(f"{self.code}: local dataset is unavailable: {path}")


def _require_duckdb() -> Any:
    if duckdb is None:
        raise DatasetNotAvailableError("DuckDB dependency is not installed; run pip install -r requirements.txt")
    return duckdb


def _database_path(path: str | Path, default_filename: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.suffix.lower() == ".duckdb" else candidate / default_filename


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


class HistoricalResultStore:
    """Query and append normalized historical results in one DuckDB file."""

    _table = "historical_results"

    def __init__(self, path: str | Path) -> None:
        self.path = _database_path(path, "historical_results.duckdb")

    @property
    def root(self) -> Path:
        """Compatibility location for callers that only need the dataset path."""

        return self.path

    def _connect(self, *, read_only: bool) -> Any:
        db = _require_duckdb()
        if read_only and not self.path.exists():
            raise DatasetNotAvailableError(self.path)
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = db.connect(str(self.path), read_only=read_only)
        if not read_only:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_results (
                    record_digest VARCHAR PRIMARY KEY,
                    canonical_match_id VARCHAR,
                    competition_id VARCHAR,
                    season_id VARCHAR,
                    home_team_id VARCHAR,
                    away_team_id VARCHAR,
                    kickoff_at VARCHAR,
                    entity_type VARCHAR,
                    match_type VARCHAR,
                    eligible_for_team_strength BOOLEAN,
                    source_conflict BOOLEAN,
                    record_json VARCHAR NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS historical_results_team_idx ON historical_results(home_team_id, away_team_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS historical_results_kickoff_idx ON historical_results(kickoff_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS historical_results_competition_idx ON historical_results(competition_id, season_id)")
        return connection

    @staticmethod
    def _validate(record: Mapping[str, Any]) -> None:
        # Local import avoids a module cycle: historical_results imports this store.
        from .contracts import validate_record

        validate_record("historical_match_result", record)

    @staticmethod
    def _encoded(record: Mapping[str, Any]) -> tuple[str, str]:
        encoded = canonical_json_bytes(record).decode("utf-8")
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), encoded

    def append(self, record: Mapping[str, Any]) -> str:
        self._validate(record)
        digest, encoded = self._encoded(record)
        connection = self._connect(read_only=False)
        try:
            existing = connection.execute(
                "SELECT record_json FROM historical_results WHERE record_digest = ?",
                [digest],
            ).fetchone()
            if existing is not None:
                if existing[0] != encoded:
                    raise ValueError(f"historical result digest collision: {digest}")
                return digest
            connection.execute(
                """
                INSERT INTO historical_results (
                    record_digest, canonical_match_id, competition_id, season_id,
                    home_team_id, away_team_id, kickoff_at, entity_type,
                    match_type, eligible_for_team_strength, source_conflict, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    digest,
                    record.get("canonical_match_id"),
                    record.get("competition_id"),
                    record.get("season_id"),
                    record.get("home_team_id"),
                    record.get("away_team_id"),
                    record.get("kickoff_at"),
                    record.get("entity_type"),
                    record.get("match_type"),
                    bool(record.get("eligible_for_team_strength")),
                    bool(record.get("source_conflict")),
                    encoded,
                ],
            )
            return digest
        finally:
            connection.close()

    def append_many(self, records: Iterable[Mapping[str, Any]]) -> int:
        materialized = [dict(record) for record in records]
        encoded_records = []
        for record in materialized:
            self._validate(record)
            encoded_records.append((*self._encoded(record), record))
        if not encoded_records:
            return 0
        connection = self._connect(read_only=False)
        inserted = 0
        try:
            connection.execute("BEGIN TRANSACTION")
            for digest, encoded, record in encoded_records:
                existing = connection.execute(
                    "SELECT record_json FROM historical_results WHERE record_digest = ?",
                    [digest],
                ).fetchone()
                if existing is not None:
                    if existing[0] != encoded:
                        raise ValueError(f"historical result digest collision: {digest}")
                    continue
                connection.execute(
                    """
                    INSERT INTO historical_results (
                        record_digest, canonical_match_id, competition_id, season_id,
                        home_team_id, away_team_id, kickoff_at, entity_type,
                        match_type, eligible_for_team_strength, source_conflict, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        digest,
                        record.get("canonical_match_id"),
                        record.get("competition_id"),
                        record.get("season_id"),
                        record.get("home_team_id"),
                        record.get("away_team_id"),
                        record.get("kickoff_at"),
                        record.get("entity_type"),
                        record.get("match_type"),
                        bool(record.get("eligible_for_team_strength")),
                        bool(record.get("source_conflict")),
                        encoded,
                    ],
                )
                inserted += 1
            connection.execute("COMMIT")
            return inserted
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _decode(rows: Iterable[tuple[Any, ...]]) -> Iterator[dict[str, Any]]:
        for row in rows:
            yield json.loads(row[0])

    def _query(self, where: str = "", parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
        connection = self._connect(read_only=True)
        try:
            sql = "SELECT record_json FROM historical_results"
            if where:
                sql += f" WHERE {where}"
            sql += " ORDER BY kickoff_at, canonical_match_id, record_digest"
            return list(self._decode(connection.execute(sql, list(parameters)).fetchall()))
        finally:
            connection.close()

    def iter_records(
        self,
        *,
        team_id: str | None = None,
        before_kickoff: str | None = None,
        competition_id: str | None = None,
        season_id: str | None = None,
        entity_type: str | None = None,
        eligible_only: bool = False,
    ) -> Iterator[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if team_id is not None:
            clauses.append("(home_team_id = ? OR away_team_id = ?)")
            parameters.extend([team_id, team_id])
        if before_kickoff is not None:
            clauses.append("kickoff_at < ?")
            parameters.append(before_kickoff)
        if competition_id is not None:
            clauses.append("competition_id = ?")
            parameters.append(competition_id)
        if season_id is not None:
            clauses.append("season_id = ?")
            parameters.append(season_id)
        if entity_type is not None:
            clauses.append("entity_type = ?")
            parameters.append(entity_type)
        if eligible_only:
            clauses.append("eligible_for_team_strength = TRUE")
        return iter(self._query(" AND ".join(clauses), parameters))

    def query_by_team(self, team_id: str, **filters: Any) -> list[dict[str, Any]]:
        return list(self.iter_records(team_id=team_id, **filters))

    def query_before_kickoff(self, team_id: str, target_kickoff: str, **filters: Any) -> list[dict[str, Any]]:
        return list(self.iter_records(team_id=team_id, before_kickoff=target_kickoff, **filters))

    def query_by_competition(self, competition_id: str, **filters: Any) -> list[dict[str, Any]]:
        return list(self.iter_records(competition_id=competition_id, **filters))

    def records(self) -> list[dict[str, Any]]:
        return list(self.iter_records())

    def get(self, digest: str) -> dict[str, Any]:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT record_json FROM historical_results WHERE record_digest = ?",
                [digest],
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(digest)
        record = json.loads(row[0])
        if content_sha256(record) != digest:
            raise ValueError(f"historical result content hash mismatch: {digest}")
        return record

    def count(self) -> int:
        connection = self._connect(read_only=True)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM historical_results").fetchone()[0])
        finally:
            connection.close()

    def dataset_digest(self) -> str:
        connection = self._connect(read_only=True)
        try:
            digests = [row[0] for row in connection.execute("SELECT record_digest FROM historical_results ORDER BY record_digest").fetchall()]
        finally:
            connection.close()
        return content_sha256(digests)


class DuckDBSnapshotStore:
    """Immutable snapshot table keyed by snapshot identity and content digest."""

    def __init__(self, path: str | Path) -> None:
        self.path = _database_path(path, "team_strength_snapshots.duckdb")

    def _connect(self, *, read_only: bool) -> Any:
        db = _require_duckdb()
        if read_only and not self.path.exists():
            raise DatasetNotAvailableError(self.path)
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = db.connect(str(self.path), read_only=read_only)
        if not read_only:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS team_strength_snapshots (
                    snapshot_id VARCHAR PRIMARY KEY,
                    snapshot_digest VARCHAR NOT NULL,
                    target_match_id VARCHAR,
                    team_id VARCHAR,
                    as_of_at VARCHAR,
                    input_dataset_digest VARCHAR,
                    builder_version VARCHAR,
                    snapshot_json VARCHAR NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS team_strength_snapshot_team_idx ON team_strength_snapshots(team_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS team_strength_snapshot_target_idx ON team_strength_snapshots(target_match_id)")
        return connection

    def put(self, snapshot: Mapping[str, Any]) -> str:
        identity = str(snapshot.get("snapshot_id") or "")
        if not identity:
            raise ValueError("immutable snapshot requires snapshot_id")
        digest, encoded = HistoricalResultStore._encoded(snapshot)
        connection = self._connect(read_only=False)
        try:
            existing = connection.execute(
                "SELECT snapshot_json FROM team_strength_snapshots WHERE snapshot_id = ?",
                [identity],
            ).fetchone()
            if existing is not None:
                if existing[0] != encoded:
                    raise ValueError(f"immutable pre-match snapshot conflict: {identity}")
                return identity
            connection.execute(
                """
                INSERT INTO team_strength_snapshots (
                    snapshot_id, snapshot_digest, target_match_id, team_id,
                    as_of_at, input_dataset_digest, builder_version, snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    identity,
                    digest,
                    snapshot.get("target_match_id"),
                    snapshot.get("team_id"),
                    snapshot.get("as_of_at"),
                    snapshot.get("input_dataset_digest"),
                    snapshot.get("builder_version"),
                    encoded,
                ],
            )
            return identity
        finally:
            connection.close()

    def get(self, snapshot_id: str) -> dict[str, Any]:
        connection = self._connect(read_only=True)
        try:
            row = connection.execute(
                "SELECT snapshot_digest, snapshot_json FROM team_strength_snapshots WHERE snapshot_id = ?",
                [snapshot_id],
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(snapshot_id)
        snapshot = json.loads(row[1])
        if snapshot.get("snapshot_id") != snapshot_id or content_sha256(snapshot) != row[0]:
            raise ValueError(f"snapshot content hash mismatch: {snapshot_id}")
        return snapshot

    def records(self) -> list[dict[str, Any]]:
        connection = self._connect(read_only=True)
        try:
            rows = connection.execute("SELECT snapshot_json FROM team_strength_snapshots ORDER BY snapshot_id").fetchall()
        finally:
            connection.close()
        return list(HistoricalResultStore._decode(rows))

    def count(self) -> int:
        connection = self._connect(read_only=True)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM team_strength_snapshots").fetchone()[0])
        finally:
            connection.close()

    def dataset_digest(self) -> str:
        connection = self._connect(read_only=True)
        try:
            digests = [row[0] for row in connection.execute("SELECT snapshot_digest FROM team_strength_snapshots ORDER BY snapshot_id").fetchall()]
        finally:
            connection.close()
        return content_sha256(digests)

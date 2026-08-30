from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.football_data import publish_runtime_snapshot
from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.runtime_snapshot import (
    SnapshotObjectError,
    file_sha256,
    immutable_object_key,
    manifest_object_key,
    safe_object_store_diagnostic,
)
from scripts.football_data.storage import HistoricalResultStore


class FakeObjectStore:
    def __init__(self, *, fail_put: bool = False):
        self.objects: dict[str, bytes] = {}
        self.fail_put = fail_put
        self.calls: list[tuple[str, str]] = []

    def head_object(self, key: str) -> dict:
        self.calls.append(("head", key))
        if key not in self.objects:
            from scripts.football_data.runtime_snapshot import ObjectNotFound

            raise ObjectNotFound()
        return {"ContentLength": len(self.objects[key])}

    def put_file(self, key: str, source: Path, *, content_type: str = "application/octet-stream") -> None:
        self.calls.append(("put", key))
        if self.fail_put:
            raise RuntimeError("object store upload failed")
        self.objects[key] = source.read_bytes()

    def put_bytes(self, key: str, body: bytes, *, content_type: str = "application/octet-stream") -> None:
        self.calls.append(("put", key))
        if self.fail_put:
            raise RuntimeError("object store upload failed")
        self.objects[key] = bytes(body)

    def download(self, key: str, destination: Path) -> None:
        self.calls.append(("get", key))
        if key not in self.objects:
            from scripts.football_data.runtime_snapshot import ObjectNotFound

            raise ObjectNotFound()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])


def _record(index: int) -> dict:
    return make_historical_match_result(
        canonical_match_id=f"match:publish:{index}",
        competition_id="competition:test",
        season_id="season:test:2026",
        home_team_id=f"team:test:home:{index}",
        away_team_id=f"team:test:away:{index}",
        kickoff_at=f"2026-08-{index + 1:02d}T12:00:00Z",
        home_goals=1,
        away_goals=0,
        provider="fixture",
        provider_match_id=f"fixture:{index}",
        source_as_of_at=f"2026-08-{index + 1:02d}T12:00:00Z",
        captured_at="2026-08-30T00:00:00Z",
        source_record_ref=f"fixture:{index}",
        source_reliable=True,
        resolution_method="manual_verified",
    )


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    data_home = tmp_path / "data-home"
    data_home.mkdir()
    db = data_home / "historical_results.duckdb"
    HistoricalResultStore(db).append_many(_record(index) for index in (1, 2))
    store = HistoricalResultStore(db)
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "historical_results.dataset.json").write_text(
        json.dumps({
            "record_count": store.count(),
            "dataset_sha256": store.dataset_digest(),
            "builder_version": "test-builder.v1",
            "source_manifest_hashes": {"source": "b" * 64},
        }),
        encoding="utf-8",
    )
    runtime_manifest = tmp_path / "runtime_snapshot_manifest.json"
    monkeypatch.setattr(publish_runtime_snapshot, "EXPECTED_RECORD_COUNT", store.count())
    monkeypatch.setattr(publish_runtime_snapshot, "EXPECTED_DATASET_SHA256", store.dataset_digest())
    return data_home, manifest_dir, runtime_manifest


def test_publisher_verifies_upload_before_advancing_manifest(tmp_path, monkeypatch):
    data_home, manifest_dir, runtime_manifest = _setup(tmp_path, monkeypatch)
    object_store = FakeObjectStore()

    result = publish_runtime_snapshot.publish_snapshot(
        data_home=data_home,
        runtime_manifest_path=runtime_manifest,
        authoritative_manifest_path=manifest_dir / "historical_results.dataset.json",
        object_store=object_store,
        now="2026-08-30T01:02:03Z",
        temp_root=tmp_path / "temp",
    )

    assert result["status"] == "OBJECT_SNAPSHOT_VERIFIED"
    manifest = json.loads(runtime_manifest.read_text(encoding="utf-8"))
    assert manifest["object_key"] == immutable_object_key(manifest["dataset_sha256"])
    assert manifest["object_key"].endswith("historical_results.duckdb")
    assert manifest["previous_snapshot_version"] is None
    assert ("put", manifest["object_key"]) in object_store.calls
    assert ("head", manifest["object_key"]) in object_store.calls
    assert ("get", manifest["object_key"]) in object_store.calls
    assert ("put", manifest_object_key(manifest["snapshot_version"])) in object_store.calls


def test_publisher_failure_does_not_advance_existing_manifest(tmp_path, monkeypatch):
    data_home, manifest_dir, runtime_manifest = _setup(tmp_path, monkeypatch)
    previous = {
        "snapshot_version": "snapshot-20260830T000000Z-" + "1" * 64,
        "object_key": immutable_object_key("1" * 64),
        "artifact_sha256": "2" * 64,
        "dataset_sha256": "1" * 64,
        "record_count": 2,
        "dataset_version": "authoritative-1778",
        "contract_version": "data-plane-2.v1",
        "builder_version": "test-builder.v1",
        "source_manifest_hashes": ["3" * 64],
        "created_at": "2026-08-30T00:00:00Z",
        "previous_snapshot_version": None,
    }
    original = json.dumps(previous, sort_keys=True, indent=2) + "\n"
    runtime_manifest.write_text(original, encoding="utf-8")

    with pytest.raises(Exception):
        publish_runtime_snapshot.publish_snapshot(
            data_home=data_home,
            runtime_manifest_path=runtime_manifest,
            authoritative_manifest_path=manifest_dir / "historical_results.dataset.json",
            object_store=FakeObjectStore(fail_put=True),
            now="2026-08-30T01:02:03Z",
            temp_root=tmp_path / "temp",
        )

    assert runtime_manifest.read_text(encoding="utf-8") == original


def test_publisher_config_repr_and_failure_output_do_not_include_secret(monkeypatch, capsys):
    secret = "LOCAL_APPLICATION_KEY_SHOULD_NOT_BE_LOGGED"
    config = publish_runtime_snapshot.SnapshotConfig(
        endpoint_url="https://object-store.example",
        bucket="private-bucket",
        region="us-east-1",
        access_key_id="key-id",
        secret_access_key=secret,
    )
    assert secret not in repr(config)

    def fail(*args, **kwargs):
        raise RuntimeError(f"transport failed with {secret}")

    monkeypatch.setattr(publish_runtime_snapshot, "publish_snapshot", fail)
    monkeypatch.setenv("FOOTBALL_DATA_SNAPSHOT_PUBLISH_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("FOOTBALL_DATA_SNAPSHOT_PUBLISH_SECRET_ACCESS_KEY", secret)
    monkeypatch.setenv("FOOTBALL_DATA_SNAPSHOT_ENDPOINT_URL", "https://object-store.example")
    monkeypatch.setenv("FOOTBALL_DATA_SNAPSHOT_BUCKET", "private-bucket")
    monkeypatch.setenv("FOOTBALL_DATA_SNAPSHOT_REGION", "us-east-1")

    assert publish_runtime_snapshot.main([]) != 0
    assert secret not in capsys.readouterr().out


def test_publisher_without_local_credentials_prints_only_safe_interactive_command(monkeypatch, capsys):
    for name in (
        "FOOTBALL_DATA_SNAPSHOT_PUBLISH_ACCESS_KEY_ID",
        "FOOTBALL_DATA_SNAPSHOT_PUBLISH_SECRET_ACCESS_KEY",
        "FOOTBALL_DATA_SNAPSHOT_ENDPOINT_URL",
        "FOOTBALL_DATA_SNAPSHOT_BUCKET",
        "FOOTBALL_DATA_SNAPSHOT_REGION",
    ):
        monkeypatch.delenv(name, raising=False)

    assert publish_runtime_snapshot.main([]) == 2
    assert capsys.readouterr().out == (
        "LOCAL_PUBLISHER_INPUT_REQUIRED\n"
        "python -m scripts.football_data.publish_runtime_snapshot --interactive\n"
    )


def test_object_store_diagnostic_contains_only_safe_request_metadata():
    secret = "APPLICATION_KEY_MUST_NOT_APPEAR"

    class FakeClientError(RuntimeError):
        response = {
            "Error": {"Code": "AccessDenied", "Message": f"leaked {secret}"},
            "ResponseMetadata": {"HTTPStatusCode": 403, "RequestId": "request-id"},
        }

    error = SnapshotObjectError("S3 PUT failed", operation="PUT")
    error.__cause__ = FakeClientError(secret)

    diagnostic = safe_object_store_diagnostic(error)

    assert diagnostic == {
        "operation": "PUT",
        "exception_type": "FakeClientError",
        "service_code": "AccessDenied",
        "http_status": 403,
    }
    assert secret not in repr(diagnostic)


def test_interactive_config_strips_application_key_whitespace():
    values = iter(
        [
            "https://object-store.example",
            "private-bucket",
            "us-east-1",
            "key-id",
        ]
    )

    config = publish_runtime_snapshot.interactive_config(
        input_fn=lambda _prompt: next(values),
        secret_input_fn=lambda _prompt: "  application-key  ",
    )

    assert config.secret_access_key == "application-key"

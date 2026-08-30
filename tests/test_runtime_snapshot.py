from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.football_data.historical_results import make_historical_match_result
from scripts.football_data.storage import HistoricalResultStore
from scripts.football_data import runtime_snapshot
from scripts.football_data.runtime_snapshot import (
    S3ObjectStore,
    SnapshotConfig,
    SnapshotManifestError,
    SnapshotObjectError,
    SnapshotVerificationError,
    atomic_install_verified,
    build_manifest,
    build_s3_client,
    file_sha256,
    immutable_object_key,
    manifest_object_key,
    verify_artifact,
    verify_duckdb_dataset,
)


def _record(index: int) -> dict:
    return make_historical_match_result(
        canonical_match_id=f"match:runtime:{index}",
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


def _database(tmp_path: Path, count: int = 2) -> Path:
    path = tmp_path / "historical_results.duckdb"
    HistoricalResultStore(path).append_many(_record(index) for index in range(1, count + 1))
    return path


def _manifest(*, dataset_sha256: str, record_count: int, previous: str | None = None) -> dict:
    return build_manifest(
        dataset_sha256=dataset_sha256,
        record_count=record_count,
        artifact_sha256="a" * 64,
        source_manifest_hashes=["b" * 64],
        builder_version="test-builder.v1",
        previous_snapshot_version=previous,
        now="2026-08-30T01:02:03Z",
    )


def test_immutable_object_naming_is_digest_addressed():
    digest = "1" * 64

    assert immutable_object_key(digest) == (
        "football-data/historical-results/"
        f"{digest}/historical_results.duckdb"
    )
    assert "latest.duckdb" not in immutable_object_key(digest)
    assert manifest_object_key("snapshot-20260830T010203Z-" + digest).startswith(
        "football-data/historical-results/manifests/"
    )


def test_manifest_rejects_latest_object_and_missing_fields():
    manifest = _manifest(dataset_sha256="1" * 64, record_count=2)
    manifest["object_key"] = "football-data/historical-results/latest.duckdb"

    with pytest.raises(SnapshotManifestError):
        runtime_snapshot.validate_manifest(manifest)

    incomplete = dict(manifest)
    incomplete.pop("previous_snapshot_version")
    with pytest.raises(SnapshotManifestError):
        runtime_snapshot.validate_manifest(incomplete)


def test_verify_artifact_rejects_checksum_mismatch(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"artifact")

    with pytest.raises(SnapshotVerificationError) as error:
        verify_artifact(path, "0" * 64)

    assert error.value.code == "ARTIFACT_CHECKSUM_MISMATCH"


def test_verify_duckdb_rejects_logical_digest_mismatch(tmp_path):
    path = _database(tmp_path)
    store = HistoricalResultStore(path)

    with pytest.raises(SnapshotVerificationError) as error:
        verify_duckdb_dataset(path, expected_count=store.count(), expected_digest="0" * 64)

    assert error.value.code == "LOGICAL_DIGEST_MISMATCH"


def test_verify_duckdb_rejects_record_count_mismatch(tmp_path):
    path = _database(tmp_path)
    digest = HistoricalResultStore(path).dataset_digest()

    with pytest.raises(SnapshotVerificationError) as error:
        verify_duckdb_dataset(path, expected_count=999, expected_digest=digest)

    assert error.value.code == "RECORD_COUNT_MISMATCH"


def test_atomic_install_copies_verified_artifact_without_partial_destination(tmp_path):
    source = tmp_path / "downloaded.duckdb"
    source.write_bytes(b"verified-bytes")
    data_home = tmp_path / "runtime"
    destination = data_home / "historical_results.duckdb"

    atomic_install_verified(source, data_home, expected_artifact_sha256=file_sha256(source))

    assert destination.read_bytes() == b"verified-bytes"
    assert not list(data_home.glob("*.tmp"))


def test_s3_client_is_provider_neutral(monkeypatch):
    captured = {}

    class FakeBoto3:
        @staticmethod
        def client(service_name, **kwargs):
            captured["service_name"] = service_name
            captured["kwargs"] = kwargs
            return object()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(runtime_snapshot, "_load_boto3", lambda: (FakeBoto3, FakeConfig))
    config = SnapshotConfig(
        endpoint_url="https://object-store.example",
        bucket="private-bucket",
        region="us-east-1",
        access_key_id="key-id",
        secret_access_key="application-key",
    )

    build_s3_client(config)

    assert captured["service_name"] == "s3"
    assert captured["kwargs"]["endpoint_url"] == config.endpoint_url
    assert captured["kwargs"]["region_name"] == config.region
    assert captured["kwargs"]["aws_access_key_id"] == config.access_key_id
    assert captured["kwargs"]["aws_secret_access_key"] == config.secret_access_key


def test_s3_store_find_exact_object_uses_list_objects_v2_without_exposing_config():
    key = immutable_object_key("1" * 64)
    calls = []

    class FakeClient:
        @staticmethod
        def list_objects_v2(**kwargs):
            calls.append(kwargs)
            return {"Contents": [{"Key": key + ".other"}, {"Key": key}]}

    config = SnapshotConfig(
        endpoint_url="https://object-store.example",
        bucket="private-bucket",
        region="us-east-1",
        access_key_id="key-id",
        secret_access_key="application-key",
    )

    assert S3ObjectStore(config, client=FakeClient()).find_exact_object(key) is True
    assert calls == [{"Bucket": config.bucket, "Prefix": key, "MaxKeys": 2}]


def test_s3_store_find_exact_object_wraps_list_failure_safely():
    class FakeClient:
        @staticmethod
        def list_objects_v2(**kwargs):
            raise RuntimeError("credential material must not escape")

    config = SnapshotConfig(
        endpoint_url="https://object-store.example",
        bucket="private-bucket",
        region="us-east-1",
        access_key_id="key-id",
        secret_access_key="application-key",
    )

    with pytest.raises(SnapshotObjectError) as error:
        S3ObjectStore(config, client=FakeClient()).find_exact_object("key")

    assert error.value.operation == "LIST"
    assert "credential material" not in str(error.value)

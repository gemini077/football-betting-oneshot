"""Provider-neutral runtime snapshot contracts and S3-compatible I/O helpers.

The historical DuckDB remains the authoritative local dataset.  This module
only adds the immutable object-store boundary used to publish and bootstrap
that already-built artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from .data_home import historical_results_path
from .storage import HistoricalResultStore


EXPECTED_RECORD_COUNT = 1778
EXPECTED_DATASET_SHA256 = "48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2"
RUNTIME_CONTRACT_VERSION = "data-plane-2.v1"
AUTHORITATIVE_DATASET_VERSION = "authoritative-1778"
DEFAULT_BUILDER_VERSION = "data-plane-2-publisher.v1"
RUNTIME_MANIFEST_FILENAME = "runtime_snapshot_manifest.json"
SNAPSHOT_PREFIX = "football-data/historical-results"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_VERSION_RE = re.compile(r"^snapshot-\d{8}T\d{6}Z-[0-9a-f]{64}$")

REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "snapshot_version",
        "object_key",
        "artifact_sha256",
        "dataset_sha256",
        "record_count",
        "dataset_version",
        "contract_version",
        "builder_version",
        "source_manifest_hashes",
        "created_at",
        "previous_snapshot_version",
    }
)


class SnapshotError(RuntimeError):
    """Base error with a public-safe machine-readable code."""

    code = "SNAPSHOT_ERROR"

    def __init__(self, detail: str | None = None, *, code: str | None = None):
        if code:
            self.code = code
        self.detail = detail or ""
        message = self.code if not self.detail else f"{self.code}: {self.detail}"
        super().__init__(message)


class SnapshotConfigurationError(SnapshotError):
    code = "SNAPSHOT_CONFIGURATION_ERROR"


class SnapshotManifestError(SnapshotError):
    code = "SNAPSHOT_MANIFEST_INVALID"


class SnapshotVerificationError(SnapshotError):
    code = "SNAPSHOT_VERIFICATION_FAILED"


class SnapshotObjectError(SnapshotError):
    code = "OBJECT_STORE_REQUEST_FAILED"


class ObjectNotFound(SnapshotObjectError):
    code = "OBJECT_NOT_FOUND"


class ObjectStore(Protocol):
    """Small interface shared by boto3 and deterministic test doubles."""

    def head_object(self, key: str) -> Mapping[str, Any]: ...

    def put_file(self, key: str, source: Path, *, content_type: str = "application/octet-stream") -> None: ...

    def put_bytes(self, key: str, body: bytes, *, content_type: str = "application/octet-stream") -> None: ...

    def download(self, key: str, destination: Path) -> None: ...


@dataclass(frozen=True)
class SnapshotConfig:
    """Provider-neutral credentials and endpoint settings.

    Secret material is excluded from the dataclass representation so an
    accidental debug representation cannot copy it into a log.
    """

    endpoint_url: str
    bucket: str
    region: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)

    def __post_init__(self) -> None:
        if not all(str(value).strip() for value in (self.endpoint_url, self.bucket, self.region, self.access_key_id, self.secret_access_key)):
            raise SnapshotConfigurationError("object-store configuration is incomplete")

    @classmethod
    def from_environment(cls, *, role: str) -> "SnapshotConfig":
        role_name = str(role).strip().upper()
        if role_name not in {"RUNTIME", "PUBLISH"}:
            raise SnapshotConfigurationError("object-store role is invalid")
        names = {
            "access_key_id": f"FOOTBALL_DATA_SNAPSHOT_{role_name}_ACCESS_KEY_ID",
            "secret_access_key": f"FOOTBALL_DATA_SNAPSHOT_{role_name}_SECRET_ACCESS_KEY",
            "endpoint_url": "FOOTBALL_DATA_SNAPSHOT_ENDPOINT_URL",
            "bucket": "FOOTBALL_DATA_SNAPSHOT_BUCKET",
            "region": "FOOTBALL_DATA_SNAPSHOT_REGION",
        }
        values = {field_name: os.environ.get(environment_name, "").strip() for field_name, environment_name in names.items()}
        missing = [environment_name for field_name, environment_name in names.items() if not values[field_name]]
        if missing:
            code = "GITHUB_RUNTIME_CONFIG_MISSING" if role_name == "RUNTIME" else "LOCAL_PUBLISHER_INPUT_REQUIRED"
            raise SnapshotConfigurationError(
                f"missing configured names: {', '.join(missing)}",
                code=code,
            )
        return cls(**values)


def _load_boto3() -> tuple[Any, Any]:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as error:  # pragma: no cover - dependency gate is exercised in CLI environments
        raise SnapshotConfigurationError("boto3 dependency is not installed") from error
    return boto3, Config


def build_s3_client(config: SnapshotConfig) -> Any:
    """Build a standard S3 client for any S3-compatible endpoint.

    The endpoint and credentials are passed to boto3; authentication/signing
    stays inside the maintained client instead of being reimplemented here.
    See boto3's official Session and S3 client references.
    """

    boto3, config_type = _load_boto3()
    try:
        return boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=config_type(
                signature_version="s3v4",
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=10,
                read_timeout=120,
            ),
        )
    except Exception as error:  # do not expose provider or credential details
        raise SnapshotObjectError("S3 client initialization failed") from error


def _is_not_found(error: BaseException) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    metadata = response.get("ResponseMetadata")
    error_info = response.get("Error")
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
    error_code = error_info.get("Code") if isinstance(error_info, Mapping) else None
    return status == 404 or str(error_code or "") in {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}


class S3ObjectStore:
    """Adapter over boto3's low-level S3 client with safe error boundaries."""

    def __init__(self, config: SnapshotConfig, client: Any | None = None):
        self._config = config
        self._client = client if client is not None else build_s3_client(config)

    @classmethod
    def from_config(cls, config: SnapshotConfig) -> "S3ObjectStore":
        return cls(config)

    def head_object(self, key: str) -> Mapping[str, Any]:
        try:
            return self._client.head_object(Bucket=self._config.bucket, Key=key)
        except Exception as error:
            if _is_not_found(error):
                raise ObjectNotFound() from error
            raise SnapshotObjectError("S3 HEAD failed") from error

    def put_file(self, key: str, source: Path, *, content_type: str = "application/octet-stream") -> None:
        try:
            with source.open("rb") as handle:
                self._client.put_object(
                    Bucket=self._config.bucket,
                    Key=key,
                    Body=handle,
                    ContentType=content_type,
                )
        except Exception as error:
            raise SnapshotObjectError("S3 PUT failed") from error

    def put_bytes(self, key: str, body: bytes, *, content_type: str = "application/octet-stream") -> None:
        try:
            self._client.put_object(
                Bucket=self._config.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except Exception as error:
            raise SnapshotObjectError("S3 PUT failed") from error

    def download(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = self._client.get_object(Bucket=self._config.bucket, Key=key)
            body = response["Body"]
            try:
                with destination.open("wb") as handle:
                    while True:
                        chunk = body.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except Exception as error:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            if _is_not_found(error):
                raise ObjectNotFound() from error
            raise SnapshotObjectError("S3 GET failed") from error


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SnapshotVerificationError("artifact is not readable") from error
    return digest.hexdigest()


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def immutable_object_key(dataset_sha256: str) -> str:
    if not _valid_sha256(dataset_sha256):
        raise SnapshotManifestError("dataset digest must be a lowercase SHA256")
    return f"{SNAPSHOT_PREFIX}/{dataset_sha256}/historical_results.duckdb"


def manifest_object_key(snapshot_version: str) -> str:
    if not isinstance(snapshot_version, str) or _SNAPSHOT_VERSION_RE.fullmatch(snapshot_version) is None:
        raise SnapshotManifestError("snapshot version is invalid")
    return f"{SNAPSHOT_PREFIX}/manifests/{snapshot_version}.json"


def validate_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SnapshotManifestError("manifest must be an object")
    payload = dict(value)
    missing = sorted(REQUIRED_MANIFEST_FIELDS - payload.keys())
    extra = sorted(payload.keys() - REQUIRED_MANIFEST_FIELDS)
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing=" + ",".join(missing))
        if extra:
            parts.append("unexpected=" + ",".join(extra))
        raise SnapshotManifestError("manifest fields are not exact: " + "; ".join(parts))

    snapshot_version = payload["snapshot_version"]
    if not isinstance(snapshot_version, str) or _SNAPSHOT_VERSION_RE.fullmatch(snapshot_version) is None:
        raise SnapshotManifestError("snapshot_version is invalid")
    dataset_digest = payload["dataset_sha256"]
    artifact_digest = payload["artifact_sha256"]
    if not _valid_sha256(dataset_digest) or not _valid_sha256(artifact_digest):
        raise SnapshotManifestError("artifact and dataset digests must be lowercase SHA256")
    if payload["object_key"] != immutable_object_key(dataset_digest):
        raise SnapshotManifestError("object_key must be the exact immutable dataset key")
    count = payload["record_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise SnapshotManifestError("record_count must be a positive integer")
    if payload["contract_version"] != RUNTIME_CONTRACT_VERSION:
        raise SnapshotManifestError("contract_version is unsupported")
    for field_name in ("dataset_version", "builder_version"):
        if not isinstance(payload[field_name], str) or not payload[field_name].strip():
            raise SnapshotManifestError(f"{field_name} is required")
    source_hashes = payload["source_manifest_hashes"]
    if not isinstance(source_hashes, list) or not source_hashes or not all(_valid_sha256(item) for item in source_hashes):
        raise SnapshotManifestError("source_manifest_hashes must contain SHA256 values")
    if _parse_timestamp(payload["created_at"]) is None:
        raise SnapshotManifestError("created_at must be an ISO timestamp")
    previous = payload["previous_snapshot_version"]
    if previous is not None and (not isinstance(previous, str) or _SNAPSHOT_VERSION_RE.fullmatch(previous) is None or previous == snapshot_version):
        raise SnapshotManifestError("previous_snapshot_version is invalid")
    return payload


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotManifestError("runtime manifest is unreadable") from error
    return validate_manifest(value)


def _iso_utc(value: datetime | str | None) -> str:
    if isinstance(value, str):
        parsed = _parse_timestamp(value)
        if parsed is None:
            raise SnapshotManifestError("created_at must be an ISO timestamp")
        value = parsed
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_manifest(
    *,
    dataset_sha256: str,
    record_count: int,
    artifact_sha256: str,
    source_manifest_hashes: list[str],
    builder_version: str,
    previous_snapshot_version: str | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    created_at = _iso_utc(now)
    snapshot_version = f"snapshot-{created_at.replace('-', '').replace(':', '')}-{dataset_sha256}"
    return validate_manifest(
        {
            "snapshot_version": snapshot_version,
            "object_key": immutable_object_key(dataset_sha256),
            "artifact_sha256": artifact_sha256,
            "dataset_sha256": dataset_sha256,
            "record_count": record_count,
            "dataset_version": AUTHORITATIVE_DATASET_VERSION,
            "contract_version": RUNTIME_CONTRACT_VERSION,
            "builder_version": builder_version,
            "source_manifest_hashes": sorted(set(source_manifest_hashes)),
            "created_at": created_at,
            "previous_snapshot_version": previous_snapshot_version,
        }
    )


def verify_artifact(path: str | Path, expected_sha256: str) -> str:
    if not _valid_sha256(expected_sha256):
        raise SnapshotVerificationError("expected artifact digest is invalid")
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise SnapshotVerificationError(code="ARTIFACT_CHECKSUM_MISMATCH")
    return actual


def verify_duckdb_dataset(path: str | Path, *, expected_count: int, expected_digest: str) -> dict[str, Any]:
    database_path = Path(path)
    try:
        store = HistoricalResultStore(database_path)
        actual_count = store.count()
        actual_digest = store.dataset_digest()
    except Exception as error:
        raise SnapshotVerificationError(code="DUCKDB_READ_ONLY_VERIFY_FAILED") from error
    if actual_count != expected_count:
        raise SnapshotVerificationError(code="RECORD_COUNT_MISMATCH")
    if actual_digest != expected_digest:
        raise SnapshotVerificationError(code="LOGICAL_DIGEST_MISMATCH")
    return {"record_count": actual_count, "dataset_sha256": actual_digest}


def verify_snapshot_file(path: str | Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_manifest(manifest)
    verify_artifact(path, validated["artifact_sha256"])
    return verify_duckdb_dataset(
        path,
        expected_count=validated["record_count"],
        expected_digest=validated["dataset_sha256"],
    )


def atomic_write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_install_verified(source: str | Path, data_home: str | Path, *, expected_artifact_sha256: str) -> Path:
    source_path = Path(source)
    destination_root = Path(data_home)
    verify_artifact(source_path, expected_artifact_sha256)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = historical_results_path(destination_root)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination_root,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            with source_path.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        verify_artifact(temporary, expected_artifact_sha256)
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def source_manifest_hashes(value: Mapping[str, Any]) -> list[str]:
    raw = value.get("source_manifest_hashes")
    if isinstance(raw, Mapping):
        values = list(raw.values())
    elif isinstance(raw, list):
        values = raw
    else:
        values = []
    hashes = sorted({item for item in values if _valid_sha256(item)})
    if not hashes:
        raise SnapshotManifestError("authoritative source manifest hashes are missing")
    return hashes


def read_json_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SnapshotManifestError("object manifest is unreadable") from error
    return validate_manifest(value)


def temporary_directory(base: str | Path | None = None) -> tempfile.TemporaryDirectory[str]:
    root = Path(base) if base is not None else None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="football-data-snapshot-", dir=str(root) if root else None)

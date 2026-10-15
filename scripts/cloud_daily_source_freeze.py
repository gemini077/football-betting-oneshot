"""Local, non-production immutable daily Sporttery source snapshot."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request
import zlib

try:
    from scripts.automation_cycle import active_business_dates, SHANGHAI
    from scripts.fetch_sporttery import SPORTTERY_SCHEDULE_API, OFFICIAL_PAGE_HEADERS
except ImportError:
    from automation_cycle import active_business_dates, SHANGHAI
    from fetch_sporttery import SPORTTERY_SCHEDULE_API, OFFICIAL_PAGE_HEADERS

MAX_DOWNLOAD = 5 * 1024 * 1024


def _download():
    request = urllib.request.Request(SPORTTERY_SCHEDULE_API, headers=OFFICIAL_PAGE_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        if not 200 <= response.status < 300:
            raise ValueError("unsuccessful HTTP status")
        raw = response.read(MAX_DOWNLOAD + 1)
    if len(raw) > MAX_DOWNLOAD:
        raise ValueError("response exceeds 5 MiB limit")
    return raw


def _json_bytes(raw: bytes) -> bytes:
    if raw.startswith(b"\x1f\x8b"):
        decoder = gzip.decompressobj() if hasattr(gzip, "decompressobj") else None
        if decoder is None:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            decoded = decoder.decompress(raw, MAX_DOWNLOAD + 1)
            if len(decoded) > MAX_DOWNLOAD or decoder.unconsumed_tail:
                raise ValueError("decompressed response exceeds 5 MiB limit")
            decoded += decoder.flush(MAX_DOWNLOAD + 1 - len(decoded))
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError("invalid gzip response") from exc
        if len(decoded) > MAX_DOWNLOAD:
            raise ValueError("decompressed response exceeds 5 MiB limit")
        if not decoder.eof or decoder.unused_data:
            raise ValueError("invalid gzip response or trailing bytes")
        return decoded
    if len(raw) > MAX_DOWNLOAD:
        raise ValueError("response exceeds 5 MiB limit")
    return raw


def _summary(groups, business_date):
    matching = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("invalid schedule group")
        group_date = group.get("businessDate")
        fixtures = group.get("subMatchList", [])
        if not isinstance(fixtures, list):
            raise ValueError("invalid fixture list")
        if group_date == business_date:
            for fixture in fixtures:
                if not isinstance(fixture, dict):
                    raise ValueError("invalid fixture")
                row_date = fixture.get("businessDate")
                if row_date and row_date != business_date:
                    raise ValueError("fixture business date mismatch")
                matching.append(fixture)
    count = len(matching)
    return {"status": "OK" if count else "SOURCE_HAS_NO_ACTIVE_BUSINESS_DATE",
            "fixture_count": count, "group_count": sum(1 for g in groups if isinstance(g, dict) and g.get("businessDate") == business_date)}


def _verify(path: Path, digest: str):
    try:
        if path.is_symlink():
            raise ValueError("symlink target")
        with gzip.open(path, "rb") as stream:
            saved = json.loads(stream.read().decode("utf-8"))
        raw = base64.b64decode(saved["raw_payload_base64"], validate=True)
        if (hashlib.sha256(raw).hexdigest() != digest or saved.get("source_sha256") != digest
                or saved.get("source_url") != SPORTTERY_SCHEDULE_API):
            raise ValueError("existing snapshot integrity/source mismatch")
    except Exception as exc:
        raise ValueError("existing snapshot is corrupt or unverifiable") from exc


def freeze(output_dir: Path, *, now=None, fetcher=None):
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("--output-dir must be an existing real directory")
    business_date, _ = active_business_dates(now)
    fetched = (fetcher or _download)()
    raw = fetched[0] if isinstance(fetched, tuple) else fetched
    parsed = json.loads(_json_bytes(raw).decode("utf-8"))
    if (not isinstance(parsed, dict) or parsed.get("success") is not True
            or not isinstance(parsed.get("value"), dict)
            or not isinstance(parsed["value"].get("matchInfoList"), list)):
        raise ValueError("upstream schema invalid")
    groups = parsed["value"]["matchInfoList"]
    digest = hashlib.sha256(raw).hexdigest()
    target = output_dir / f"{business_date}.json.gz"
    if target.is_symlink():
        raise ValueError("snapshot target must not be a symlink")
    if target.exists():
        _verify(target, digest)
        return target
    captured = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    body = {"schema_version": "1", "business_date": business_date,
            "captured_at_utc": captured, "source_url": SPORTTERY_SCHEDULE_API,
            "source_sha256": digest, "summary": _summary(groups, business_date),
            "raw_payload_base64": base64.b64encode(raw).decode("ascii")}
    encoded = gzip.compress(json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), mtime=0)
    if len(encoded) > MAX_DOWNLOAD + 65536:
        raise ValueError("snapshot exceeds bounded output size")
    fd, temp_name = tempfile.mkstemp(prefix=f".{business_date}.", suffix=".tmp", dir=output_dir)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if target.is_symlink():
            raise ValueError("snapshot target must not be a symlink")
        if target.exists():
            _verify(target, digest)
            return target
        try:
            os.link(temp, target)
        except FileExistsError:
            if target.is_symlink():
                raise ValueError("snapshot target must not be a symlink")
            _verify(target, digest)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        path = freeze(Path(args.output_dir))
        print(json.dumps({"status": "FROZEN", "path": str(path)}))
        return 0
    except Exception as exc:
        print(f"freeze failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


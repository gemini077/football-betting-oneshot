import base64
import datetime as dt
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts import cloud_daily_source_freeze as freeze
from scripts.automation_cycle import SHANGHAI


def fixture_bytes(groups):
    return json.dumps({"success": True, "value": {"matchInfoList": groups}}).encode()


def fetcher(raw):
    return lambda: (raw, json.loads(raw)["value"]["matchInfoList"])


def test_rollover_boundary():
    before = dt.datetime(2026, 10, 14, 10, 59, tzinfo=SHANGHAI)
    after = dt.datetime(2026, 10, 14, 11, 0, tzinfo=SHANGHAI)
    assert freeze.active_business_dates(before)[0] == "2026-10-13"
    assert freeze.active_business_dates(after)[0] == "2026-10-14"


def test_fixture_selection_and_counts(tmp_path):
    groups = [{"businessDate": "2026-10-14", "subMatchList": [{"matchId": "1"}, {"matchId": "2"}]},
              {"businessDate": "2026-10-13", "subMatchList": [{"matchId": "3"}]}]
    raw = fixture_bytes(groups)
    path = freeze.freeze(tmp_path, now=dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI), fetcher=fetcher(raw))
    data = json.loads(gzip.decompress(path.read_bytes()))
    assert data["summary"] == {"status": "OK", "fixture_count": 2, "group_count": 1}
    assert "prediction" not in json.dumps(data).lower()


def test_format_gzip_mtime_and_raw_replay(tmp_path):
    raw = fixture_bytes([])
    path = freeze.freeze(tmp_path, now=dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI), fetcher=fetcher(raw))
    content = path.read_bytes()
    assert content[:4] == b"\x1f\x8b\x08\x00" and content[4:8] == b"\x00" * 4
    body = json.loads(gzip.decompress(content))
    assert base64.b64decode(body["raw_payload_base64"]) == raw
    assert body["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["captured_at_utc"].endswith("Z")


def test_gzip_upstream_roundtrip_preserves_compressed_wire_bytes(tmp_path):
    raw = gzip.compress(fixture_bytes([]), mtime=0)
    path = freeze.freeze(tmp_path, now=dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI), fetcher=lambda: raw)
    body = json.loads(gzip.decompress(path.read_bytes()))
    assert base64.b64decode(body["raw_payload_base64"]) == raw
    assert body["source_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("raw", [
    gzip.compress(b"x" * (5 * 1024 * 1024 + 1)),
    gzip.compress(fixture_bytes([])) + b"trailing",
])
def test_gzip_oversize_or_trailing_data_rejected(tmp_path, raw):
    with pytest.raises(ValueError):
        freeze.freeze(tmp_path, now=dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI), fetcher=lambda: raw)
    assert list(tmp_path.iterdir()) == []


def test_duplicate_is_idempotent(tmp_path):
    raw = fixture_bytes([])
    instant = dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI)
    first = freeze.freeze(tmp_path, now=instant, fetcher=fetcher(raw))
    original = first.read_bytes()
    assert freeze.freeze(tmp_path, now=instant, fetcher=fetcher(raw)) == first
    assert first.read_bytes() == original


def test_tamper_rejected(tmp_path):
    raw = fixture_bytes([])
    now = dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI)
    path = freeze.freeze(tmp_path, now=now, fetcher=fetcher(raw))
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="corrupt"):
        freeze.freeze(tmp_path, now=now, fetcher=fetcher(raw))


def test_publish_links_only_after_complete_temp_is_written(tmp_path, monkeypatch):
    raw = fixture_bytes([])
    instant = dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI)
    real_link = freeze.os.link
    observed = []

    def checked_link(source, target):
        assert not Path(target).exists()
        assert Path(source).stat().st_size > 0
        observed.append(True)
        return real_link(source, target)

    monkeypatch.setattr(freeze.os, "link", checked_link)
    freeze.freeze(tmp_path, now=instant, fetcher=fetcher(raw))
    assert observed == [True]


def test_concurrent_publish_is_idempotent_and_never_exposes_empty_target(tmp_path):
    raw = fixture_bytes([])
    instant = dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI)
    def publish():
        return freeze.freeze(tmp_path, now=instant, fetcher=fetcher(raw))
    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _: publish(), range(2)))
    assert paths[0] == paths[1]
    assert paths[0].stat().st_size > 0
    body = json.loads(gzip.decompress(paths[0].read_bytes()))
    assert base64.b64decode(body["raw_payload_base64"]) == raw


@pytest.mark.parametrize("raw", [b"{", b'{"success":false,"value":{"matchInfoList":[]}}', b'{"success":true,"value":{"matchInfoList":{}}}'])
def test_upstream_failure_no_file(tmp_path, raw):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        freeze.freeze(tmp_path, now=dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI), fetcher=lambda: (raw, []))
    assert list(tmp_path.iterdir()) == []


def test_api_failure_no_file(tmp_path, monkeypatch):
    def fail():
        raise OSError("HTTP failure")
    monkeypatch.setattr(freeze, "_download", fail)
    assert freeze.main(["--output-dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []


def test_no_active_business_date_status(tmp_path):
    raw = fixture_bytes([{"businessDate": "2026-10-13", "subMatchList": [{"matchId": "x"}]}])
    path = freeze.freeze(tmp_path, now=dt.datetime(2026, 10, 14, 12, tzinfo=SHANGHAI), fetcher=fetcher(raw))
    data = json.loads(gzip.decompress(path.read_bytes()))
    assert data["summary"]["status"] == "SOURCE_HAS_NO_ACTIVE_BUSINESS_DATE"
    assert data["summary"]["fixture_count"] == 0


def test_invalid_or_missing_output_dir(tmp_path):
    with pytest.raises(ValueError):
        freeze.freeze(tmp_path / "missing", fetcher=lambda: (b"", []))
    with pytest.raises(SystemExit):
        freeze.main([])


def test_output_symlink_rejected(tmp_path):
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(ValueError, match="real directory"):
        freeze.freeze(link)


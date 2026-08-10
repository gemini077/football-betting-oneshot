from scripts.football_data.storage import SnapshotStore, content_sha256


def test_content_addressed_json_round_trips_and_is_order_stable(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    first = {"z": 1, "records": [{"provider": "statsbomb", "value": 0.4}], "a": "x"}
    second = {"a": "x", "records": [{"value": 0.4, "provider": "statsbomb"}], "z": 1}
    digest, path = store.put(first)
    assert digest == content_sha256(second)
    assert path.name == f"{digest}.json"
    assert store.get(digest) == first
    store.put(second)
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 1


def test_snapshot_digest_mismatch_is_rejected(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    digest, path = store.put({"value": 1})
    path.write_text('{"value": 2}\n', encoding="utf-8")
    try:
        store.get(digest)
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered snapshot must be rejected")

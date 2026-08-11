# Football data storage policy

Phase 2B.3 keeps bulk historical results and pre-match Team Strength snapshots
out of Git. The formal local analytical store is one DuckDB file per dataset
under the shared `FOOTBALL_DATA_HOME`, so sibling worktrees see the same
dataset.

The resolver is:

1. `FOOTBALL_DATA_HOME` when configured;
2. otherwise `Path.home()/.football-betting-oneshot/football_data`.

For example on Windows:

```powershell
$env:FOOTBALL_DATA_HOME = "D:\MyProject\football-betting-data"
```

The source code never embeds a user-specific absolute path.

| Material | Git-tracked | Shared Data Home | Test fixture |
| --- | --- | --- | --- |
| Provider/source manifests, URLs, source commits, raw hashes and terms | Yes | Optional | Small samples only |
| Verified identity crosswalk and compact review queue | Yes | No | Small samples only |
| Detailed identity candidate evidence | No | `identity/p0_p1_identity_candidates.json` | Small samples only |
| Normalized historical result rows | No, except legacy rows already on `main` | `historical_results.duckdb` | `tests/fixtures/` |
| Pre-match Team Strength snapshots | No | `team_strength_snapshots.duckdb` | `tests/fixtures/` |
| Dataset manifests and deterministic digests | Yes | No | No |

## Existing data and fresh clone semantics

Use the following explicit cases:

### A. Shared Data Home already exists

Use the DuckDB files in the resolved Data Home and run:

```bash
python -m scripts.football_data.verify_data_home
```

The command checks record counts and deterministic digests against the tracked
manifests. A mismatch is `DIGEST_MISMATCH`; it is not silently repaired.

### B. Legacy cache or permitted source captures exist

Copy the current worktree cache into the shared home without deleting the
legacy cache:

```bash
python -m scripts.football_data.migrate_data_home
```

For legacy JSON captures, rebuild the DuckDB datasets:

```bash
python -m scripts.football_data.rebuild_historical_store
```

Both commands are offline. They never download third-party data, fabricate
rows, or fall back to aggregate recent-form text.

### C. Fresh clone has no local data

The store reports `DATASET_NOT_AVAILABLE`. The manifests describe source
references, hashes, parser versions and permitted acquisition boundaries, but
they do not contain the 1554 historical rows or 160 snapshots. A fresh clone
must rerun the permitted source capture/population workflow before the bulk
dataset can be rebuilt.

## Store contract

`HistoricalResultStore` supports append/idempotence, iteration, team queries,
strict pre-kickoff queries, competition queries, counts and deterministic
dataset digests. `PreMatchSnapshotStore` uses an immutable DuckDB table keyed by
`snapshot_id` and rejects conflicting content. Snapshot rows retain the
target match, team, as-of time, input dataset digest and builder version.

The Team Strength builder consumes the store interface (or a small in-memory
iterable in tests), and its strict `historical kickoff < target kickoff` gate
is unchanged. The store is shadow-only; no Champion feature source is changed.

## Identity evidence boundary

The detailed P0/P1 candidate graph is derived bulk evidence and is written to
`${FOOTBALL_DATA_HOME}/identity/p0_p1_identity_candidates.json`. Git retains
only the compact `verified_identity_crosswalk.json` and
`identity_review_queue.json`. The compact crosswalk preserves the 152
AUTO_VERIFIED provider mappings, evidence digests and source references without
embedding aligned fixture payloads.

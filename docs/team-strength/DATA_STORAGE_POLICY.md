# Football data storage policy

Phase 2B.3 keeps bulk historical results and pre-match Team Strength snapshots
out of Git. The local analytical store is one DuckDB file per dataset under
`.cache/football_data/`; the files are reproducible local cache artifacts, not
model inputs committed to the repository.

| Material | Git-tracked | Local bulk cache | Test fixture |
| --- | --- | --- | --- |
| Provider/source manifests, URLs, source commits, raw hashes and terms | Yes | Optional | Small samples only |
| Team identity/competition registries and compact health summaries | Yes | No | Small samples only |
| Normalized historical result rows | No, except legacy rows already on `main` | `historical_results.duckdb` | `tests/fixtures/` |
| Pre-match Team Strength snapshots | No | `team_strength_snapshots.duckdb` | `tests/fixtures/` |
| Dataset manifests and deterministic digests | Yes | No | No |

## Rebuild boundary

Run:

```bash
python -m scripts.football_data.rebuild_historical_store
```

The command migrates locally available legacy JSON evidence or exits with
`DATASET_NOT_AVAILABLE` when the evidence is absent. It never downloads raw
third-party data, fabricates rows, or falls back to aggregate recent-form
text. Source manifests under `data/football_data/` document how a permitted
capture can be reacquired and which parser/hash must be checked.

## Store contract

`HistoricalResultStore` supports append/idempotence, iteration, team queries,
strict pre-kickoff queries, competition queries, counts and deterministic
dataset digests. `PreMatchSnapshotStore` uses an immutable DuckDB table keyed by
`snapshot_id` and rejects conflicting content. Snapshot rows retain the
target match, team, as-of time, input dataset digest and builder version.

The Team Strength builder consumes the store interface (or a small in-memory
iterable in tests), and its strict `historical kickoff < target kickoff` gate
is unchanged. The store is shadow-only; no Champion feature source is changed.


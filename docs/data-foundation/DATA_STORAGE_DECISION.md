# Phase 2A Storage Decision Memo

## Decision

Phase 2A uses:

1. raw evidence outside the normalized contract boundary;
2. immutable, normalized JSON snapshots;
3. JSON registry files for team aliases and competition identity;
4. content-addressed snapshot helpers for reproducible test/research artifacts.

No SQLite, DuckDB, Parquet or Postgres migration is introduced in this phase. The existing repository already uses bounded JSON/report/snapshot artifacts, and the Phase 2A data volume and query patterns do not yet prove that a database is needed.

## Why JSON first

- Small registry and fixture records remain reviewable in Git.
- The source record reference, provider, timestamps, raw digest and contract version travel with each normalized value.
- A content hash gives an immutable handoff/reference without scanning or copying the historical `data/` tree.
- Provider-specific xG records can remain separate files/records until normalization is explicitly defined.

The JSON approach is a storage decision, not a claim that JSON is the final analytical engine. The `SnapshotStore` interface is deliberately narrow so a future analytical projection can be added without changing the data contract or Champion.

## DuckDB / Parquet evaluation

The [DuckDB Parquet documentation](https://duckdb.org/docs/stable/data/parquet/overview) confirms useful future capabilities: direct Parquet read/write, column projection, filter pushdown, schema-by-name options and metadata inspection. Those capabilities become attractive when historical event/shot data is large enough that repeated JSON scans are a measurable bottleneck or when cross-provider analytical queries are frequent.

They are not yet a reason to add a runtime dependency because:

- Phase 2A has only one research event adapter and no multi-provider event workload;
- current contracts are record-oriented and provenance-heavy;
- the Champion must remain isolated from analytical storage choices;
- adding a database now would create migration, backup and schema-ownership work without a demonstrated query requirement.

Revisit the choice when a bounded measurement shows one or more of: repeated historical scans exceed an agreed runtime budget, snapshots become too large for practical review, or at least two real event providers need recurring cross-provider analysis. Any migration must preserve content hashes and source record refs.

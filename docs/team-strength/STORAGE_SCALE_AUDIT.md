# Phase 2B.3 storage scale audit

This audit compares PR #69 against its `main` base. GitHub's `gh pr diff` file
listing endpoint returned HTTP 406 because the PR exceeds GitHub's 300-file
diff limit; the counts below were independently computed from the local
three-dot Git diff and are therefore not based on a truncated web response.

## Before the storage hotfix

| Category | Count |
| --- | ---: |
| PR changed files | 1493 |
| Bulk historical result JSON files | 1348 |
| Bulk Team Strength snapshot JSON files | 112 |
| Code files | 9 |
| Test files | 11 |
| Documentation files | 2 |
| Manifest/report/config/task files | 11 |

The PR's historical result rows represented 1348 newly normalized eligible
records. The local ledger also contains 206 historical result rows inherited
from earlier merged work; those old-main rows are not rewritten by this
hotfix. The 112 snapshots are Phase 2B.3 bulk artifacts and are migrated out
of Git.

## After the storage hotfix

| Category | Count |
| --- | ---: |
| PR changed files versus `origin/main` | 50 |
| Changed historical-result bulk JSON paths | 0 |
| Changed Team Strength bulk JSON paths | 0 |
| Git-tracked historical JSON files (legacy main baseline) | 206 |
| Git-tracked Team Strength snapshot JSON files (legacy main baseline) | 48 |
| Local DuckDB historical records | 1554 |
| Local DuckDB Team Strength snapshots | 160 |

The final changed-file count includes compact Phase 2B.3 evidence and the
handoff archive, not the ignored DuckDB datasets. The old-main legacy JSON
baseline is deliberately left untouched; future generated JSON in those paths
is ignored and the formal bulk store is the local DuckDB dataset.

## Decision

DuckDB single-file storage is selected for this repository. It keeps nested
normalized record JSON lossless while exposing indexed columns for team,
kickoff and competition queries. Parquet remains a compatible future export or
interchange format, but adding a second formal dataset format now would create
two sources of truth without a current need.

The repository retains code, contracts, manifests, hashes, registries,
compact coverage summaries and small deterministic fixtures. Bulk files move
to the shared `FOOTBALL_DATA_HOME` documented in `DATA_STORAGE_POLICY.md`, not
to a worktree-local cache.

## Storage Final boundary

- `FOOTBALL_DATA_HOME` is resolved from the environment or the stable user-home
  default, so two sibling worktrees discover the same DuckDB files.
- The current 1554 historical records and 160 snapshots were copied from the
  old worktree cache and verified by count and digest; the old cache remains
  preserved for rollback/migration safety.
- The detailed `p0_p1_identity_candidates.json` is outside Git in the shared
  Data Home. Git retains 152 compact AUTO_VERIFIED mappings and a compact
  49-entry review queue.
- A fresh clone with neither shared data nor permitted captures returns
  `DATASET_NOT_AVAILABLE`; manifests do not pretend to reconstruct bulk rows.

## Authenticity and parity constraints

- Dataset manifests retain record counts, time bounds, source-manifest hashes,
  parser/builder versions, storage policy and deterministic dataset digests.
- A missing local bulk store is reported as `DATASET_NOT_AVAILABLE`; no
  aggregate recent-form, odds, Champion lambda or synthetic fallback is used.
- Historical result eligibility and strict pre-kickoff filtering are unchanged.
- Snapshot identity is immutable; a conflicting write is rejected.
- P0/P1 demand metrics remain a data-layer audit only and remain
  `validated_for_model=false`.
- `agent-reach unavailable in current Codex environment`; official DuckDB
  documentation and the local dependency check were used for this bounded
  storage decision.

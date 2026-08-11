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

## Decision

DuckDB single-file storage is selected for this repository. It keeps nested
normalized record JSON lossless while exposing indexed columns for team,
kickoff and competition queries. Parquet remains a compatible future export or
interchange format, but adding a second formal dataset format now would create
two sources of truth without a current need.

The repository retains code, contracts, manifests, hashes, registries,
compact coverage summaries and small deterministic fixtures. Bulk files move
to the ignored local paths documented in `DATA_STORAGE_POLICY.md`.

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


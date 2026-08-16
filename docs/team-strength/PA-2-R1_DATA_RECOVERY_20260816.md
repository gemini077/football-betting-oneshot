# PA-2-R1 DATA Recovery Record — 2026-08-16

## Recovery source and method

The complete local recovery source was found in Git object
`a42826ed270eff352838e7d8f54c398f2c989919`, the parent of storage-hotfix
commit `250468d0`. Its trees contain 1,554 historical-result JSON records and
160 team-strength snapshots. The other nine unreachable commits inspected were
the 206/48 baseline.

The source was exported outside the repository and processed with the existing
offline `scripts.football_data.rebuild_historical_store` pipeline. No network
fetch, mock record, empty database, or synthetic record was used.

## Authoritative store verification

The restored shared home is `D:\\MyProject\\football-betting-data`.

| Dataset | Records | Time range | Dataset SHA-256 |
| --- | ---: | --- | --- |
| historical results | 1,554 | 2025-02-22T00:00:00Z — 2026-08-03T18:00:00Z | `710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e` |
| team-strength snapshots | 160 | 2026-07-17T17:15:00Z — 2026-08-11T03:15:00+08:00 | `3fcd494b0cbe20f65f6f8407f471ca2d8e034010789b6ebec85d0e4becd9a8a6` |

Independent checks found no duplicate canonical match IDs, no duplicate
provider match IDs, no missing identity, no missing provenance, and no
synthetic historical records. All 1,554 records have a source URL/raw SHA
reference and are before target `2026-08-12` (future-leakage check passed).

The pre-recovery 206/48 shared databases are preserved outside the repository
under the PA-2-R1 delivery directory.

## PA-2-R1 evidence result

Evidence was generated outside the repository under
`D:\\MyProject\\_deliveries\\football-betting-oneshot\\PA-2-R1-DATA\\evidence`:

- `identity_bridge_audit.json`
- `paired_challenger_evaluation.json`
- `challenger_summary.json`
- `walk_forward_metrics.json`

The bridge is deterministic-only (`fuzzy_resolution_used=false`). The current
input contributed 0 rows in this run; the formal input contained 9 rows: 7
`COMPETITION_UNSUPPORTED`, 1 `IDENTITY_UNAVAILABLE`, and 1 `MAPPED` row. The
formal paired sample is 1 and `same_match_ids_for_all_methods=true`.

For the single paired Norway match (`500-1364333`, Rosenborg vs Viking), the
challenger's Brier/log-loss were `0.526843021409` / `0.894254164539`, compared
with current `0.606861126098` / `0.993085386853`. This is directional only;
the sample is too small for a decision. Market-only and Uniform score-level
metrics are unavailable on that row because frozen score probabilities are
missing. Fusion remains `NOT_YET_EVALUATED`; promotion remains shadow-only;
CA-1 remains `KEEP_PAUSED`.

## Scope boundary

No Champion or production prediction logic was changed. PA-3 was not started.
The full formal acceptance gate is still open until authoritative frozen
predictions and deterministic competition/identity coverage provide the
required paired sample.

# FE-HISTORY-GRAPH-1 — Historical Network Coverage Audit

Status: `READY_FOR_ACCEPTANCE`

## Scope

This is a read-only topology and identity-coverage audit. It does not fit a model, modify Champion, modify production, or read settlement/postmatch evaluation data.

- Historical store: `FOOTBALL_DATA_HOME/historical_results.duckdb`; dataset digest `710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e`.
- Current production fixture source: `data/prediction_universe/2026-08-29.json`; business date `2026-08-29`; source status `READY`.
- Historical library: **1554 matches / 113 teams / 7 competitions / 12 seasons**.

## Connected coverage by competition

| Competition | Matches | Teams | Components | Largest component | Match coverage | Team coverage |
|---|---:|---:|---:|---:|---:|---:|
| `competition:brazil-serie-a` | 290 | 16 | 1 | 16 teams | 100.00% | 100.00% |
| `competition:finland-veikkausliiga` | 251 | 12 | 1 | 12 teams | 100.00% | 100.00% |
| `competition:norway-eliteserien` | 319 | 16 | 1 | 16 teams | 100.00% | 100.00% |
| `competition:portugal-primeira-liga` | 370 | 33 | 1 | 33 teams | 100.00% | 100.00% |
| `competition:sweden-allsvenskan` | 135 | 18 | 1 | 18 teams | 100.00% | 100.00% |
| `competition:sweden-superettan` | 5 | 6 | 1 | 6 teams | 100.00% | 100.00% |
| `competition:usa-mls` | 184 | 14 | 1 | 14 teams | 100.00% | 100.00% |

## Team history depth

113 teams; min/median/p75/max = 1/30.0/41.0/48 matches; mean = 27.50.
Buckets: `{'0': 0, '1-4': 19, '5-9': 0, '10-19': 15, '20-39': 44, '40+': 35}`. The exact per-team distribution is retained in the JSON evidence.
Historical identity diagnostic: 15 crosswalk entity clusters split across 30 historical team IDs; affected competitions: `['competition:portugal-primeira-liga']`.

## Current production fixture coverage

Canonical current-day universe: **28 fixtures**; both teams in the same historical network: **0/28 (0.00%)**.
Mutually exclusive blockers: identity `28`, history after identity resolution `0`, ready `0`.
Existing current identity evidence has `3` rows but exact overlap with this universe is `0`; no verified two-team pair is available.
Competition-level pre-identity signal: supported historical competition `4`, known missing historical competition `6`, registry-unresolved `18`.
Known missing competition history keys: `{'competition:germany-2-bundesliga': 1, 'competition:japan-j1-league': 2, 'competition:japan-j2-league': 1, 'competition:netherlands-eredivisie': 1, 'competition:south-korea-k-league-1': 1}`.

## Readiness

- Elo: historical graph `CONDITIONAL_IDENTITY_REPAIR_REQUIRED`; current-production development `NOT_READY`.
- Dynamic A/D: historical graph `CONDITIONAL_IDENTITY_REPAIR_REQUIRED`; current-production development `NOT_READY`.

## Time semantics

Historical max kickoff `2026-08-03T18:00:00+00:00`; current fixture min kickoff `2026-08-29T17:00:00+08:00`; strict prior relation `True`.
Historical source_as_of/captured_at are also before the current fixture minimum: `True` / `True`.
Feature construction rule remains strict `historical kickoff_at < target kickoff_at`; no target or later match is eligible.

## Conclusion

Primary blocker: **identity**. Missing categories: `identity, competition_history`.
The historical graph is topologically connected within all seven covered competitions, but the verified crosswalk exposes 15 identity-fragmentation clusters in Portugal. The current production universe has no deterministic two-team identity pair. In addition, 24 current fixtures are outside an exact-supported historical competition context (6 known missing result coverage, 18 unresolved in the existing competition registry).

## Production mutation check

The audit reads the historical DuckDB and tracked evidence only; it writes only this compact report and the audit markdown. Champion, frozen predictions, production workflows, and the shared data store are not modified.

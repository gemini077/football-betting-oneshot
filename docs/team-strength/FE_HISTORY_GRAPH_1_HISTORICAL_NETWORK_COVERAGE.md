# FE-HISTORY-GRAPH-1-R1 — Historical Network Coverage Audit

Status: `READY_FOR_ACCEPTANCE`
Revision: `R1`

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
Competition-level pre-identity classification: alias/context unresolved `18`, known without authoritative history `4`, source known outside authoritative store `2`, authoritative history available `4`.
Authoritative-history competition keys: `{'competition:norway-eliteserien': 1, 'competition:portugal-primeira-liga': 1, 'competition:sweden-allsvenskan': 1, 'competition:usa-mls': 1}`.
Registry/source-known-but-not-authoritative competition keys: `{'competition:japan-j1-league': 2}`; known-without-source keys: `{'competition:germany-2-bundesliga': 1, 'competition:japan-j2-league': 1, 'competition:netherlands-eredivisie': 1, 'competition:south-korea-k-league-1': 1}`.
Alias/context unresolved labels: `{'德国甲级联赛': 6, '意大利甲级联赛': 4, '法国甲级联赛': 1, '英格兰超级联赛': 4, '西班牙甲级联赛': 3}`.
Alias/context unresolved is a conservative exact-mapping result: a canonical main-table definition alone is not treated as a raw-label alias, and this class is not a historical-provider verdict.
Mutually exclusive fixture IDs by class: `{'competition_alias_or_context_unresolved': ['500-1420365', '500-1428459', '500-1428467', '500-1428468', '500-1428461', '500-1428464', '500-1420356', '500-1420349', '500-1427967', '500-1415094', '500-1420371', '500-1428457', '500-1414261', '500-1414239', '500-1414205', '500-1427975', '500-1414193', '500-1427976'], 'competition_known_but_authoritative_history_unavailable': ['500-1419095', '500-1373226', '500-1430650', '500-1415891'], 'historical_source_known_outside_authoritative_store': ['500-1418924', '500-1418949'], 'authoritative_history_available': ['500-1362754', '500-1364318', '500-1438074', '500-1358610']}`.
Bounded identity-closure candidates: **4**; fixture IDs: `['500-1362754', '500-1364318', '500-1438074', '500-1358610']`.

## Readiness

- Elo: historical graph `CONDITIONAL_IDENTITY_REPAIR_REQUIRED`; current-production development `NOT_READY`.
- Dynamic A/D: historical graph `CONDITIONAL_IDENTITY_REPAIR_REQUIRED`; current-production development `NOT_READY`.

## Time semantics

Historical max kickoff `2026-08-03T18:00:00+00:00`; current fixture min kickoff `2026-08-29T17:00:00+08:00`; strict prior relation `True`.
Historical source_as_of/captured_at are also before the current fixture minimum: `True` / `True`.
Feature construction rule remains strict `historical kickoff_at < target kickoff_at`; no target or later match is eligible.

## Conclusion

Primary blocker: **identity**. Missing categories: `identity, competition_history`.
The historical graph is topologically connected within all seven covered competitions, but the verified crosswalk exposes 15 identity-fragmentation clusters in Portugal. The current production universe has no deterministic two-team identity pair. The four competition classes above are mutually exclusive; 4 fixtures have authoritative history available and therefore leave only team identity for bounded closure. No historical topology statistic was recomputed or changed by R1.

## Production mutation check

The audit reads the historical DuckDB and tracked evidence only; it writes only this compact report and the audit markdown. Champion, frozen predictions, production workflows, and the shared data store are not modified.

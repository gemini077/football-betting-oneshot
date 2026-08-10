# Phase 2B real-data audit

Audit date: 2026-08-10. The audit is limited to existing provider snapshots,
the current match workspace, the latest schedule update, and the football-data
registries. It does not scan the historical repository wholesale.

## Observed evidence

`data/fetch_runs/` contains 2,652 JSON snapshot files in the scoped provider
snapshot directory:

| Evidence | Snapshot files | What it proves |
| --- | ---: | --- |
| Nowscore-named snapshots | 366 | Captured provider evidence exists, but not match-result history |
| 500 deep snapshots | 231 | Deep market/form evidence exists, but not match-result history |
| 500 trade snapshots | 442 | Trade/odds schedule evidence exists, not historical results |
| Snapshots with aggregate `recent_form` | 396 | Aggregate form is available |
| Snapshots with provider `team_ids` | 393 | Some provider team IDs are available in captured evidence |
| Snapshots with explicit result fields | 0 | No usable match-level score ledger was found |

These are file observations, not distinct-match counts. Nowscore and 500
therefore currently provide **0 match-level historical results eligible for a
Team Strength snapshot** in this repository.

The current workspace has 3 scheduled matches. Their rows contain provider
schedule IDs, team names, league text, dates/times, and odds. They do not carry
canonical team IDs. The current `competition_registry.json` is empty and the
production player registry is empty. The team alias registry currently contains
fixture-only mappings, not reviewed Nowscore/500 mappings.

## Shape of `recent_form`

The captured provider payload is an aggregate object with:

```text
home_overall
home_home
away_overall
away_away
```

Each aggregate has matches, wins, draws, losses, goals_for, and goals_against.
It does not contain the individual match dates, opponents, opponent IDs, or
individual scores needed to build a reproducible historical result ledger.
Consequently it cannot be expanded into `last_5`, `last_10`, or
`season_to_date` match windows without inventing lineage.

## What is currently buildable

The Phase 2B builder can build a transparent snapshot when a normalized result
record has a reviewed canonical match/team identity, kickoff time, score,
source fact time, and reliable provenance. It stores matches, goals for/against,
home/away splits, opponents, and the effective sample window. It uses
per-match rates only; it does not manufacture per-90 values.

At this audit point, no production Nowscore or 500 record satisfies that
match-level input boundary. Current scheduled matches therefore remain
diagnostic-only and produce no team-strength snapshot.

Post-match reports were not promoted into the ledger. They are report/narrative
outputs rather than provider result evidence with a stable source record and
reviewed entity lineage.

StatsBomb Open Data remains an offline research/schema/history source. It is not
a claim of current all-competition coverage or a live production feed.

## External historical-source decision

`external historical source = DEFER` for Phase 2B. No external dataset is
copied into the repository and no network dependency is added to CI/runtime.

The reviewed candidates were:

- [openfootball/football.json](https://github.com/openfootball/football.json):
  useful CC0 fixtures/results reference, but it does not supply this project’s
  reviewed provider IDs or current canonical identity layer.
- [footballcsv/cache.footballdata](https://github.com/footballcsv/cache.footballdata):
  useful CC0 CSV reference, but its repository history is not a sufficient
  current-match source for this phase. Its latest meaningful repository update
  observed in this audit was June 11, 2024; see its
  [commit history](https://github.com/footballcsv/cache.footballdata/commits/master).
- [schochastics/football-data](https://github.com/schochastics/football-data):
  broad historical results reference under ODC Attribution. The repository is
  maintained, but its published result README covers results through 2023 and
  warns about identity errors; it is not adopted as an automatic production
  identity source.

The adapter boundary remains available for a future reviewed source. External
team names may be resolver inputs only; they may not automatically create
`verified=true` registry mappings.

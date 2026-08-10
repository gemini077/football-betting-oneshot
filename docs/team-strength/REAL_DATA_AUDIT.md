# Real historical data audit

Audit/capture time: `2026-08-10T11:56:08Z`. Scope is limited to the current match workspace, latest schedule metadata, existing provider capability audit, the OpenFootball manifest, and the bounded normalized pilot sample.

## Existing Nowscore / 500 capability

The existing scoped provider audit found 2,652 JSON snapshots: 366 Nowscore-named, 231 500 deep, 442 500 trade, 396 aggregate recent-form, and 393 with provider team IDs. It found 0 explicit match-level result records. These are snapshot-file observations, not distinct-match counts.

The available `recent_form` shape is aggregate overall/home/away data with matches, wins, draws, losses, goals for and goals against. It lacks individual match dates, opponents, opponent IDs, and scores, so it cannot be expanded into a result ledger without inventing history.

## OpenFootball pilot

The pinned `openfootball/europe@e27eb01726f394ddf9fa68b15d37b900487b5903` capture contains 404 parsed result rows across three source files. The bounded pilot stores 87 normalized records involving the six current pilot teams; 87 are eligible for Team Strength.

Every eligible record has canonical home/away IDs from explicit source-context identity evidence, a date/time, score, competition, season, source fact time, reliable provenance, and no source conflict. OpenFootball source files do not provide provider team IDs; that absence is recorded rather than fabricated.

## Current buildability

Current bounded schedule: 3 matches; both teams evaluable: 3; one side: 0; neither: 0. Source conflicts: 0; unresolved identity: 0.
Immutable pre-match Team Strength snapshots persisted: 24; they remain data-layer-only.

Team Strength uses result history only. xG, lineups, injuries, Elo, odds, and Champion expected goals are not used as substitutes.

The normalized sample is a shadow data layer and remains `validated_for_model=false`; the Champion does not read it.

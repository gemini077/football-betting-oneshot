# FE-ID-BRIDGE-1 — Swedish Current-to-History Identity Bridge

**Status:** `READY_FOR_ACCEPTANCE`

## Scope

Only fixture `500-1362754` (`FBOS-202608292100-21c3ea757c`) was audited.
Target kickoff: `2026-08-29T21:00:00+08:00`; exclusive UTC cutoff: `2026-08-29T13:00:00Z`.
No provider, historical import, model, Champion, production, or frozen prediction was changed.

## Exact provider identity evidence

Nowscore match `2912253` is bound by the exact Sporttery/Prediction Universe fixture.
Prospective evidence records home ID `417` in 30/30 home-side rows and away ID `2088` in 30/30 away-side rows.
Frozen Nowscore analysis source SHA-256: `370f1bfc3d1a8c61566f7c8e740515fb7806eb6a58c11c23d1f1220a2ee33b19`; selectors: `teamNames[TeamId=417]`, `teamNames[TeamId=2088]`.

| side | provider ID | canonical team ID | mapping |
|---|---:|---|---|
| home | `417` | `team:sweden:if-elfsborg` | `project_provider_context_verified` |
| away | `2088` | `team:sweden:degerfors-if` | `project_provider_context_verified` |

Canonical candidates are corroborated by checked-in OpenFootball and football-data.co.uk identity evidence plus the authoritative direct historical meeting; no fuzzy or name-distance resolution is used.

## Authoritative historical validation

- Home usable history: **16** matches (`2025-04-23T00:00:00Z` — `2026-07-26T15:30:00Z`).
- Away usable history: **16** matches (`2025-05-03T15:00:00Z` — `2026-08-02T13:00:00Z`).
- Same `Sweden Allsvenskan` network: **True**; target-team induced component size: `16` teams.
- Direct historical edge: `match:competition:sweden-allsvenskan:2026-04-17:team:sweden:degerfors-if:team:sweden:if-elfsborg`.
- All selected rows satisfy `kickoff_at < target_kickoff`, are team-strength eligible, unique, and conflict-free; post-kickoff rows used: **0**.

## Checks

- `current_fixture_exact_nowscore_binding`: `True`
- `home_provider_id_exactly_verified`: `True`
- `away_provider_id_exactly_verified`: `True`
- `frozen_nowscore_analysis_source_hash_present`: `True`
- `source_cutoff_before_target_kickoff`: `True`
- `home_canonical_id_present`: `True`
- `away_canonical_id_present`: `True`
- `home_pre_kickoff_history_present`: `True`
- `away_pre_kickoff_history_present`: `True`
- `same_allsvenskan_historical_network`: `True`
- `no_post_kickoff_history_used`: `True`

## Evidence files

- `data/prediction_universe/2026-08-29.json`
- `data/schedule_updates/20260829_032017/20260829_032017_sporttery_2026-08-29.json`
- `data/prospective/football_evidence/FBOS-PRED-a4787da3359e9462042cb287.json`
- `data/model_governance/predictions/FBOS-PRED-a4787da3359e9462042cb287.json`
- `data/football_data/openfootball/identity_evidence.json`
- `data/football_data/football_data_uk/identity_evidence.json`
- `data/football_data/historical_result_samples/football_data_uk_sweden_2026.json`

The retained Nowscore raw-source hashes are recorded in the frozen input snapshot; raw source-cache files are not copied into this evidence package.

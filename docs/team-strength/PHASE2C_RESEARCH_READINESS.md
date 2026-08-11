# Phase 2C-1 Historical Research Readiness

Generated at: `2026-08-11T00:00:00Z`

This is a read-only, research-only walk-forward audit. It does not create predictions, formal benchmark records, model inputs, or Challenger code.

## Historical dataset

- Records: **1554**; deduplicated fixtures: **1554**
- Dataset digest: `710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e`
- Date range: `2025-02-22T00:00:00Z` to `2026-08-03T18:00:00Z`
- Competitions: **7**; unique teams: **113**
- Observed scope: all records in this dataset are `club` / `league`; this is not evidence of domestic-cup, continental, national-team, xG, lineup, or injury coverage.

## Walk-forward tiers

- Minimum research (`both >=5`, current recency, complete observed scope): **1197**
- Standard (`both >=10`, current recency, complete observed scope): **960**
- Strict (`both >=20`, current recency, complete observed scope, no bridge): **531**
- Verified bridge-only fixtures: **0**; kept outside Strict.
- Home prior-history distribution (p10/p25/median/p75/p90): **2.0 / 7.0 / 15.0 / 25.0 / 33.0**
- Away prior-history distribution (p10/p25/median/p75/p90): **2.0 / 7.0 / 15.0 / 26.0 / 34.0**

## Recommended cohort

- Tier: **standard_recommended**
- Cohort ID: `phase2c-1:standard_recommended:f351b9354ec969eefb85a7304799ed6228c8c96ba7243bcca63cca5ee11c4094`
- Size: **912**; competitions: **5**; teams: **78**
- Date range: `2025-06-01T16:00:00Z` to `2026-08-03T17:00:00Z`
- Excluded from recommended cohort for insufficient chronological span: `competition:sweden-allsvenskan`

## Chronological split proposal

Method: `global_date_order_60_20_20`; split boundaries use unique kickoff timestamps, never random sampling.
- Development: **532**, `2025-06-01T16:00:00Z` to `2026-03-01T03:30:00Z`
- Validation: **177**, `2026-03-01T15:30:00Z` to `2026-04-29T20:15:00Z`
- Held-out test: **203**, `2026-05-01T17:00:00Z` to `2026-08-03T17:00:00Z`

## Concentration

- Largest competition share: **0.25** (competition:norway-eliteserien)
- Largest season share: **0.245614** (season:portugal-primeira-liga:2025-26)
- Largest team appearance share: **0.020285** (team:finland:inter-turku)

## Source and deduplication

- Primary provider counts: `{"football-data.co.uk": 1422, "openfootball": 132}`
- Single-source fixtures: **1073**
- Multi-source corroborated fixtures: **481**
- Source conflicts: **0**; dedup conflicts: **0**

## Readiness decision

- `PHASE2C_1_RESEARCH_READY = True`
- Criteria: `{"concentration_within_audit_caps": true, "each_recommended_competition_has_chronological_train_validation_test": true, "eligible_competitions_at_least_3": true, "recommended_standard_fixtures_at_least_200": true, "unique_teams_at_least_30": true}`
- Blockers: `none`
- This result is offline research readiness only. It is not global model readiness, production readiness, formal benchmark evidence, or permission to create a Challenger.

## Formal benchmark health (read-only)

- Prospective comparisons: **0**
- Settled comparisons: **0**
- Benchmark errors: **0**; snapshot mismatches: **0**

## Governance boundaries

- Champion mathematics and inputs remain untouched.
- `validated_for_model=true` remains zero.
- Detailed eligibility rows and cohort IDs are stored under `${FOOTBALL_DATA_HOME}/research/phase2c_preflight/`; Git retains only compact manifests.

# Phase 2C-1 Historical Research Readiness

Generated at: `2026-08-11T00:00:00Z`

This is a read-only, research-only walk-forward audit. It does not create predictions, formal benchmark records, model inputs, or Challenger code.

## Historical dataset

- Records: **1554**; deduplicated fixtures: **1554**
- Dataset digest: `710b0fdc8046d69aa86411b748d9c1966c45fabd0ac83678f58719b1f3bbfb5e`
- Date range: `2025-02-22T00:00:00Z` to `2026-08-03T18:00:00Z`
- Competitions: **7**; unique teams: **113**
- Research population after sanity exclusions: **1184** fixtures; scope is reported per competition-season.
- Observed scope: all records in this dataset are `club` / `league`; this is not evidence of domestic-cup, continental, national-team, xG, lineup, or injury coverage.

## Walk-forward tiers

- Minimum research (`both >=5`, current recency, complete observed scope): **926**
- Standard (`both >=10`, current recency, complete observed scope): **736**
- Strict (`both >=20`, current recency, complete observed scope, no bridge): **400**
- Verified bridge-only fixtures: **0**; kept outside Strict.
- Home prior-history distribution (p10/p25/median/p75/p90): **3.0 / 7.0 / 15.0 / 26.0 / 35.7**
- Away prior-history distribution (p10/p25/median/p75/p90): **3.0 / 7.75 / 15.0 / 26.0 / 36.0**

## Recommended cohort

- Tier: **standard_recommended**
- Cohort ID: `phase2c-1:standard_recommended:aeca9b371975d229e598507257f0c26961ccbdb24184f38b42c464e6f8198257`
- Size: **688**; competitions: **4**; teams: **58**
- Date range: `2025-06-01T16:00:00Z` to `2026-08-03T17:00:00Z`
- Excluded from recommended cohort for insufficient chronological span: `competition:sweden-allsvenskan`
- Excluded competition-seasons for dataset sanity: `competition:portugal-primeira-liga|season:portugal-primeira-liga:2025-26`

## Chronological split proposal

Method: `global_date_order_60_20_20`; split boundaries use unique kickoff timestamps, never random sampling.
- Development: **410**, `2025-06-01T16:00:00Z` to `2026-03-11T22:00:00Z`
- Validation: **134**, `2026-03-11T23:00:00Z` to `2026-05-09T21:00:00Z`
- Held-out test: **144**, `2026-05-09T22:00:00Z` to `2026-08-03T17:00:00Z`

## Concentration

- Largest competition share: **0.331395** (competition:norway-eliteserien)
- Largest season share: **0.228198** (season:norway-eliteserien:2025)
- Largest team appearance share: **0.02689** (team:finland:inter-turku)

## Source and deduplication

- Primary provider counts: `{"football-data.co.uk": 1422, "openfootball": 132}`
- Single-source fixtures: **1073**
- Multi-source corroborated fixtures: **481**
- Source conflicts: **0**; dedup conflicts: **0**

## Competition-season sanity

- Audited slices: **12**; failed slices: **1**
- Portugal 2025/26 root cause: The complete source manifest declares 306 fixtures, while the canonical ledger has 370 (64 over the known complete population). The audit flags 66 source-observation identity-split duplicate groups and 0 additional exact ledger-key groups; they are not auto-merged. The overflow is therefore excluded from research until the canonical identity/time reconciliation is reviewed.
- Complete source fixture counts are corroborating observations, never additive capacity. Detailed per-record evidence remains outside Git under `${FOOTBALL_DATA_HOME}/research/phase2c_preflight/`.

## Readiness decision

- `PHASE2C_1_RESEARCH_READY = True`
- Criteria: `{"concentration_within_audit_caps": true, "each_recommended_competition_has_chronological_train_validation_test": true, "eligible_competitions_at_least_3": true, "recommended_cohort_dataset_sanity_passed": true, "recommended_standard_fixtures_at_least_200": true, "unique_teams_at_least_30": true}`
- Blockers: `none`
- This result is offline research readiness only. It is not global model readiness, production readiness, formal benchmark evidence, or permission to create a Challenger.
- Historical results do not include the same historical-time Champion market inputs and immutable pre-match snapshots. A future offline experiment may compare Team Strength with same-information research baselines, but cannot claim it beat Champion offline.

## Formal benchmark health (read-only)

- Prospective comparisons: **0**
- Settled comparisons: **0**
- Benchmark errors: **0**; snapshot mismatches: **0**

## Governance boundaries

- Champion mathematics and inputs remain untouched.
- `validated_for_model=true` remains zero.
- Detailed eligibility rows and cohort IDs are stored under `${FOOTBALL_DATA_HOME}/research/phase2c_preflight/`; Git retains only compact manifests.

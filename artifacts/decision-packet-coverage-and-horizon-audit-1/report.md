# Decision Packet coverage and horizon audit

- Issue: #183 — `DECISION-PACKET-COVERAGE-AND-HORIZON-AUDIT-1`
- Source `origin/main` SHA: `02b759c843be4dc20bff7c192969539b79d60f39`
- Top-level decision: **`DECISION_PACKET_CORE_READY_WITH_DEGRADED_FIELDS`**
- Scope: read-only audit of repository-resident frozen/prospective truth; no UI, API, new data acquisition, The Odds API, Reep, model, calibration, serving, or frozen-history change.
- Observation unit: **one football match = one unique `match_key`**. Version rows are counted only in the Change Awareness section.

## Authority and anti-leakage contract

The audit loads frozen prediction records through the existing governance reader and applies the existing formal eligibility reader. Input evidence is loaded from the stored input snapshot reader. Competition is a deterministic canonical join to the stored Prediction Universe fixture; it is not inferred from UI or collector code. Verified linkage uses only the formal ledger match key and a regulation-only result artifact. Postmatch result values are not read into any prematch field, are not used to choose a frozen version, and are not emitted in this report.

### Source paths

- `data/model_governance/predictions/*.json`
- `data/model_governance/input_snapshots/*.json`
- `data/prediction_universe/*.json`
- `data/base_prediction_jobs/*.json`
- `data/prospective/ledger.jsonl`
- `data/postmatch_automation/results/*.json`

### Readers

- `scripts/model_governance.py:load_frozen_prediction/load_input_snapshot`
- `scripts/prediction_universe.py:load_prediction_universe`
- `scripts/prospective_settlement.py:is_formally_eligible`
- `scripts/match_identity.py:canonical_match_id`

The one-observation representative is the latest **legal prematch** version by `(freeze_created_at, prediction_created_at, prediction_id)`. This is chronology-only and never uses a postmatch result. Earlier versions remain available for Change Awareness only.

## Inventory

```json
{
  "base_prediction_jobs": {
    "current_job_rows": 388,
    "status_counts": {
      "FROZEN": 291,
      "INSUFFICIENT_DATA": 21,
      "MISSED_PREMATCH_WINDOW": 76
    },
    "unique_matches": 388
  },
  "frozen_prediction_store": {
    "data_grades": {
      "C": 1444
    },
    "model_roles": {
      "champion": 1444
    },
    "prediction_status_counts": {
      "formal": 1449,
      "research_only": 75
    },
    "raw_formal_flag_rows": 1449,
    "raw_formal_flag_unique_matches": 322,
    "reader_accepted_formal_rows": 1444,
    "reader_accepted_formal_unique_matches": 317,
    "reader_rejected_rows": 0,
    "reader_valid_rows": 1524,
    "research_only_rows": 75
  },
  "prediction_universe": {
    "rows": 388,
    "unique_matches": 388
  },
  "prospective_ledger": {
    "duplicate_version_rows": 798,
    "unique_matches": 253,
    "version_rows": 1051
  },
  "result_artifacts": {
    "files_with_keys": 456,
    "unresolved_or_invalid_files": 37,
    "valid_regulation_only_files": 419
  }
}
```

## A. Unique-match sample funnel

| Stage | Rows | Unique matches |
|---|---:|---:|
| universe_candidates | 388 | 388 |
| current_base_job_rows | 388 | 388 |
| current_base_frozen_rows | 291 | 291 |
| formal_frozen_rows_accepted_by_existing_reader | 1444 | 317 |
| unique_frozen_matches | 317 | 317 |
| result_linked_unique_matches | 253 | 253 |
| verified_unique_matches | 216 | 216 |

`formal_frozen_rows_accepted_by_existing_reader` is intentionally a version-row count; `unique_frozen_matches` is the only product observation denominator. The current BASE job status is shown separately because it is an operational cross-check, not a rewrite of immutable frozen truth. A current-universe snapshot can also omit an already-frozen historical match; those reconciliation counts remain explicit rather than being silently dropped.

### Funnel drop reasons

```json
{
  "accepted_formal_to_result_linked": {
    "no_result_link": 64
  },
  "accepted_formal_unique_not_in_current_universe": 1,
  "raw_formal_flags_not_accepted_by_existing_reader": 5,
  "result_linked_to_verified": {
    "result_artifact_unresolved_or_invalid_90m": 37
  },
  "universe_to_accepted_formal_unique": {
    "base_reader_errors": 0,
    "by_current_base_status": {
      "INSUFFICIENT_DATA": 1,
      "MISSED_PREMATCH_WINDOW": 71
    },
    "missing_accepted_formal_freeze_unique_matches": 72,
    "universe_reader_errors": 0
  }
}
```

## B. Decision Packet field coverage

Coverage labels are fixed: `UNIVERSAL >=95%`, `BROAD 80–<95%`, `PARTIAL 50–<80%`, `SPARSE <50%`. Missing reasons are exhaustive for each field: eligible unique matches = present unique matches + reason counts.

| Field | Group | Eligible unique | Present unique | Coverage | Label | Product recommendation | Missing reasons |
|---|---|---:|---:|---:|---|---|---|
| Match identity (`match_identity`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Competition (`competition`) | core | 317 | 316 | 99.6845% | UNIVERSAL | STANDARD_REQUIRED | MISSING_AUTHORITATIVE_COMPETITION=1 |
| Kickoff (`kickoff`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Serving/degraded/unavailable state (`serving_state`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Frozen 1X2 probability vector (`frozen_1x2`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Exact Score Top1 with displayed probability (`exact_score_top1`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Exact Score Top3 with displayed probabilities (`exact_score_top3`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Exact Score Top5 with displayed probabilities (`exact_score_top5`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Full score-distribution availability flag (`full_score_distribution`) | core | 317 | 0 | 0.0000% | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=317 |
| Total-goals state/distribution (`total_goals`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| BTTS state/probability (`btts`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Source cutoff (`source_cutoff`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Frozen timestamp (`freeze_timestamp`) | core | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Frozen recent-form aggregate (`recent_form_aggregate`) | match | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Home/away recent-form context (`home_away_recent_form`) | match | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |
| Lineup publication (`lineup_publication`) | optional_match | 317 | 0 | 0.0000% | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT | NO_FROZEN_LINEUP_PUBLICATION_RECORD=317 |
| Injuries/availability (`injuries_availability`) | optional_match | 317 | 0 | 0.0000% | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT | NO_FROZEN_INJURY_AVAILABILITY_RECORD=317 |
| Weather (`weather`) | optional_match | 317 | 0 | 0.0000% | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT | NO_FROZEN_WEATHER_RECORD=317 |
| Venue/H2H (`venue_h2h`) | optional_match | 317 | 0 | 0.0000% | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT | NO_FROZEN_VENUE_OR_H2H_RECORD=317 |
| Timestamped frozen 1X2 quotes (`market_1x2_quotes`) | market | 317 | 315 | 99.3691% | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK | NO_FROZEN_1X2_QUOTE_ROWS=2 |
| AH line plus both-side water (`market_ah_line_water`) | market | 317 | 311 | 98.1073% | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=6 |
| O/U line plus both-side water (`market_ou_line_water`) | market | 317 | 315 | 99.3691% | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK | NO_FROZEN_OU_LINE_WITH_BOTH_WATERS=2 |
| Market snapshot timestamp (`market_snapshot_timestamp`) | market | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK | — |
| Market snapshot source-age inputs (`market_source_age_inputs`) | market | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK | — |
| Market/input quality/data-grade (`market_input_quality`) | market | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK | — |
| Verified-result linkage (`verified_result_linkage`) | trust | 317 | 216 | 68.1388% | PARTIAL | STANDARD_WITH_DEGRADED_FALLBACK | NO_RESULT_ARTIFACT=64, RESULT_ARTIFACT_UNRESOLVED=37 |
| Forecast lead time (`forecast_lead_time`) | trust | 317 | 317 | 100.0000% | UNIVERSAL | STANDARD_REQUIRED | — |

The following complete slice matrices cover competition, provider, source, data grade, and settlement status. They are generated from the same unique-match representatives and contain no postmatch values.

### competition
| Field | Slice | Eligible | Present | Coverage | Label | Missing reasons |
|---|---|---:|---:|---:|---|---|
| `match_identity` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `match_identity` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `competition` | UNKNOWN | 1 | 0 | 0.0000% | SPARSE | MISSING_AUTHORITATIVE_COMPETITION=1 |
| `competition` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `competition` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `competition` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `competition` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `competition` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `competition` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `competition` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `competition` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `competition` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `competition` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `competition` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `competition` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `competition` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `competition` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `competition` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `competition` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `competition` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `competition` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `competition` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `competition` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `competition` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `competition` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `competition` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `competition` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `competition` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `competition` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `competition` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `competition` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `competition` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `competition` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `competition` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `competition` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `competition` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `competition` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `competition` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `competition` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `competition` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `competition` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `kickoff` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `kickoff` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `serving_state` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `serving_state` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `full_score_distribution` | UNKNOWN | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 南美解放者杯 | 5 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=5 |
| `full_score_distribution` | 巴西杯 | 5 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=5 |
| `full_score_distribution` | 巴西甲 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 巴西甲级联赛 | 4 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=4 |
| `full_score_distribution` | 德乙 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 德国乙级联赛 | 3 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=3 |
| `full_score_distribution` | 德国杯 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 德国甲级联赛 | 6 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=6 |
| `full_score_distribution` | 德国超级杯 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 德甲 | 9 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=9 |
| `full_score_distribution` | 意大利甲级联赛 | 16 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=16 |
| `full_score_distribution` | 意杯 | 3 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=3 |
| `full_score_distribution` | 意甲 | 8 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=8 |
| `full_score_distribution` | 挪威超级联赛 | 8 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=8 |
| `full_score_distribution` | 挪超 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 日本乙级联赛 | 5 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=5 |
| `full_score_distribution` | 日本职业联赛 | 10 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=10 |
| `full_score_distribution` | 日职乙 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 日职联 | 7 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=7 |
| `full_score_distribution` | 日联杯 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 欧洲冠军联赛 | 10 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=10 |
| `full_score_distribution` | 欧罗巴联赛 | 16 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=16 |
| `full_score_distribution` | 沙特职业联赛 | 2 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=2 |
| `full_score_distribution` | 沙特联 | 5 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=5 |
| `full_score_distribution` | 法乙 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 法国乙级联赛 | 7 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=7 |
| `full_score_distribution` | 法国甲级联赛 | 9 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=9 |
| `full_score_distribution` | 法甲 | 7 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=7 |
| `full_score_distribution` | 瑞典超 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 瑞典超级联赛 | 12 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=12 |
| `full_score_distribution` | 美国职业大联盟 | 5 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=5 |
| `full_score_distribution` | 美职业 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 芬兰超级联赛 | 2 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=2 |
| `full_score_distribution` | 英冠 | 12 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=12 |
| `full_score_distribution` | 英格兰冠军联赛 | 6 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=6 |
| `full_score_distribution` | 英格兰社区盾杯 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 英格兰联赛杯 | 6 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=6 |
| `full_score_distribution` | 英格兰超级联赛 | 17 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=17 |
| `full_score_distribution` | 英超 | 9 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=9 |
| `full_score_distribution` | 荷乙 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 荷兰乙级联赛 | 2 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=2 |
| `full_score_distribution` | 荷兰甲级联赛 | 18 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=18 |
| `full_score_distribution` | 荷甲 | 3 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=3 |
| `full_score_distribution` | 葡萄牙超级联赛 | 11 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=11 |
| `full_score_distribution` | 葡超 | 3 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=3 |
| `full_score_distribution` | 西班牙甲级联赛 | 26 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=26 |
| `full_score_distribution` | 西甲 | 9 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=9 |
| `full_score_distribution` | 韩K联 | 3 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=3 |
| `full_score_distribution` | 韩国杯 | 1 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=1 |
| `full_score_distribution` | 韩国职业联赛 | 14 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=14 |
| `total_goals` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `total_goals` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `btts` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `btts` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `btts` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `btts` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `btts` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `btts` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `btts` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `btts` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `btts` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `btts` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `btts` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `btts` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `btts` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `btts` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `btts` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `btts` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `btts` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `btts` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `btts` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `btts` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `btts` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `btts` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `btts` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `btts` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `btts` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `btts` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `btts` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `btts` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `btts` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `btts` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `btts` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `btts` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `btts` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `btts` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `btts` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `btts` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `btts` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `btts` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `lineup_publication` | UNKNOWN | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 南美解放者杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=5 |
| `lineup_publication` | 巴西杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=5 |
| `lineup_publication` | 巴西甲 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 巴西甲级联赛 | 4 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=4 |
| `lineup_publication` | 德乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 德国乙级联赛 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=3 |
| `lineup_publication` | 德国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 德国甲级联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=6 |
| `lineup_publication` | 德国超级杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 德甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=9 |
| `lineup_publication` | 意大利甲级联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=16 |
| `lineup_publication` | 意杯 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=3 |
| `lineup_publication` | 意甲 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=8 |
| `lineup_publication` | 挪威超级联赛 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=8 |
| `lineup_publication` | 挪超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 日本乙级联赛 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=5 |
| `lineup_publication` | 日本职业联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=10 |
| `lineup_publication` | 日职乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 日职联 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=7 |
| `lineup_publication` | 日联杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 欧洲冠军联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=10 |
| `lineup_publication` | 欧罗巴联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=16 |
| `lineup_publication` | 沙特职业联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=2 |
| `lineup_publication` | 沙特联 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=5 |
| `lineup_publication` | 法乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 法国乙级联赛 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=7 |
| `lineup_publication` | 法国甲级联赛 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=9 |
| `lineup_publication` | 法甲 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=7 |
| `lineup_publication` | 瑞典超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 瑞典超级联赛 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=12 |
| `lineup_publication` | 美国职业大联盟 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=5 |
| `lineup_publication` | 美职业 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 芬兰超级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=2 |
| `lineup_publication` | 英冠 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=12 |
| `lineup_publication` | 英格兰冠军联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=6 |
| `lineup_publication` | 英格兰社区盾杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 英格兰联赛杯 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=6 |
| `lineup_publication` | 英格兰超级联赛 | 17 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=17 |
| `lineup_publication` | 英超 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=9 |
| `lineup_publication` | 荷乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 荷兰乙级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=2 |
| `lineup_publication` | 荷兰甲级联赛 | 18 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=18 |
| `lineup_publication` | 荷甲 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=3 |
| `lineup_publication` | 葡萄牙超级联赛 | 11 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=11 |
| `lineup_publication` | 葡超 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=3 |
| `lineup_publication` | 西班牙甲级联赛 | 26 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=26 |
| `lineup_publication` | 西甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=9 |
| `lineup_publication` | 韩K联 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=3 |
| `lineup_publication` | 韩国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=1 |
| `lineup_publication` | 韩国职业联赛 | 14 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=14 |
| `injuries_availability` | UNKNOWN | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 南美解放者杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=5 |
| `injuries_availability` | 巴西杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=5 |
| `injuries_availability` | 巴西甲 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 巴西甲级联赛 | 4 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=4 |
| `injuries_availability` | 德乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 德国乙级联赛 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=3 |
| `injuries_availability` | 德国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 德国甲级联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=6 |
| `injuries_availability` | 德国超级杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 德甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=9 |
| `injuries_availability` | 意大利甲级联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=16 |
| `injuries_availability` | 意杯 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=3 |
| `injuries_availability` | 意甲 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=8 |
| `injuries_availability` | 挪威超级联赛 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=8 |
| `injuries_availability` | 挪超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 日本乙级联赛 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=5 |
| `injuries_availability` | 日本职业联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=10 |
| `injuries_availability` | 日职乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 日职联 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=7 |
| `injuries_availability` | 日联杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 欧洲冠军联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=10 |
| `injuries_availability` | 欧罗巴联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=16 |
| `injuries_availability` | 沙特职业联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=2 |
| `injuries_availability` | 沙特联 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=5 |
| `injuries_availability` | 法乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 法国乙级联赛 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=7 |
| `injuries_availability` | 法国甲级联赛 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=9 |
| `injuries_availability` | 法甲 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=7 |
| `injuries_availability` | 瑞典超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 瑞典超级联赛 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=12 |
| `injuries_availability` | 美国职业大联盟 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=5 |
| `injuries_availability` | 美职业 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 芬兰超级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=2 |
| `injuries_availability` | 英冠 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=12 |
| `injuries_availability` | 英格兰冠军联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=6 |
| `injuries_availability` | 英格兰社区盾杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 英格兰联赛杯 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=6 |
| `injuries_availability` | 英格兰超级联赛 | 17 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=17 |
| `injuries_availability` | 英超 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=9 |
| `injuries_availability` | 荷乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 荷兰乙级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=2 |
| `injuries_availability` | 荷兰甲级联赛 | 18 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=18 |
| `injuries_availability` | 荷甲 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=3 |
| `injuries_availability` | 葡萄牙超级联赛 | 11 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=11 |
| `injuries_availability` | 葡超 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=3 |
| `injuries_availability` | 西班牙甲级联赛 | 26 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=26 |
| `injuries_availability` | 西甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=9 |
| `injuries_availability` | 韩K联 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=3 |
| `injuries_availability` | 韩国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=1 |
| `injuries_availability` | 韩国职业联赛 | 14 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=14 |
| `weather` | UNKNOWN | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 南美解放者杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=5 |
| `weather` | 巴西杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=5 |
| `weather` | 巴西甲 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 巴西甲级联赛 | 4 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=4 |
| `weather` | 德乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 德国乙级联赛 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=3 |
| `weather` | 德国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 德国甲级联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=6 |
| `weather` | 德国超级杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 德甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=9 |
| `weather` | 意大利甲级联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=16 |
| `weather` | 意杯 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=3 |
| `weather` | 意甲 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=8 |
| `weather` | 挪威超级联赛 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=8 |
| `weather` | 挪超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 日本乙级联赛 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=5 |
| `weather` | 日本职业联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=10 |
| `weather` | 日职乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 日职联 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=7 |
| `weather` | 日联杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 欧洲冠军联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=10 |
| `weather` | 欧罗巴联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=16 |
| `weather` | 沙特职业联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=2 |
| `weather` | 沙特联 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=5 |
| `weather` | 法乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 法国乙级联赛 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=7 |
| `weather` | 法国甲级联赛 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=9 |
| `weather` | 法甲 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=7 |
| `weather` | 瑞典超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 瑞典超级联赛 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=12 |
| `weather` | 美国职业大联盟 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=5 |
| `weather` | 美职业 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 芬兰超级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=2 |
| `weather` | 英冠 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=12 |
| `weather` | 英格兰冠军联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=6 |
| `weather` | 英格兰社区盾杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 英格兰联赛杯 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=6 |
| `weather` | 英格兰超级联赛 | 17 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=17 |
| `weather` | 英超 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=9 |
| `weather` | 荷乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 荷兰乙级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=2 |
| `weather` | 荷兰甲级联赛 | 18 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=18 |
| `weather` | 荷甲 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=3 |
| `weather` | 葡萄牙超级联赛 | 11 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=11 |
| `weather` | 葡超 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=3 |
| `weather` | 西班牙甲级联赛 | 26 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=26 |
| `weather` | 西甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=9 |
| `weather` | 韩K联 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=3 |
| `weather` | 韩国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=1 |
| `weather` | 韩国职业联赛 | 14 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=14 |
| `venue_h2h` | UNKNOWN | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 南美解放者杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=5 |
| `venue_h2h` | 巴西杯 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=5 |
| `venue_h2h` | 巴西甲 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 巴西甲级联赛 | 4 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=4 |
| `venue_h2h` | 德乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 德国乙级联赛 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=3 |
| `venue_h2h` | 德国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 德国甲级联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=6 |
| `venue_h2h` | 德国超级杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 德甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=9 |
| `venue_h2h` | 意大利甲级联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=16 |
| `venue_h2h` | 意杯 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=3 |
| `venue_h2h` | 意甲 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=8 |
| `venue_h2h` | 挪威超级联赛 | 8 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=8 |
| `venue_h2h` | 挪超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 日本乙级联赛 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=5 |
| `venue_h2h` | 日本职业联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=10 |
| `venue_h2h` | 日职乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 日职联 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=7 |
| `venue_h2h` | 日联杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 欧洲冠军联赛 | 10 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=10 |
| `venue_h2h` | 欧罗巴联赛 | 16 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=16 |
| `venue_h2h` | 沙特职业联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=2 |
| `venue_h2h` | 沙特联 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=5 |
| `venue_h2h` | 法乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 法国乙级联赛 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=7 |
| `venue_h2h` | 法国甲级联赛 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=9 |
| `venue_h2h` | 法甲 | 7 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=7 |
| `venue_h2h` | 瑞典超 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 瑞典超级联赛 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=12 |
| `venue_h2h` | 美国职业大联盟 | 5 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=5 |
| `venue_h2h` | 美职业 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 芬兰超级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=2 |
| `venue_h2h` | 英冠 | 12 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=12 |
| `venue_h2h` | 英格兰冠军联赛 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=6 |
| `venue_h2h` | 英格兰社区盾杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 英格兰联赛杯 | 6 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=6 |
| `venue_h2h` | 英格兰超级联赛 | 17 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=17 |
| `venue_h2h` | 英超 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=9 |
| `venue_h2h` | 荷乙 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 荷兰乙级联赛 | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=2 |
| `venue_h2h` | 荷兰甲级联赛 | 18 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=18 |
| `venue_h2h` | 荷甲 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=3 |
| `venue_h2h` | 葡萄牙超级联赛 | 11 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=11 |
| `venue_h2h` | 葡超 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=3 |
| `venue_h2h` | 西班牙甲级联赛 | 26 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=26 |
| `venue_h2h` | 西甲 | 9 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=9 |
| `venue_h2h` | 韩K联 | 3 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=3 |
| `venue_h2h` | 韩国杯 | 1 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=1 |
| `venue_h2h` | 韩国职业联赛 | 14 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=14 |
| `market_1x2_quotes` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 瑞典超级联赛 | 12 | 11 | 91.6667% | BROAD | NO_FROZEN_1X2_QUOTE_ROWS=1 |
| `market_1x2_quotes` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 英格兰超级联赛 | 17 | 16 | 94.1176% | BROAD | NO_FROZEN_1X2_QUOTE_ROWS=1 |
| `market_1x2_quotes` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 瑞典超级联赛 | 12 | 11 | 91.6667% | BROAD | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 英格兰超级联赛 | 17 | 16 | 94.1176% | BROAD | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | 英超 | 9 | 8 | 88.8889% | BROAD | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 葡萄牙超级联赛 | 11 | 10 | 90.9091% | BROAD | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | 葡超 | 3 | 2 | 66.6667% | PARTIAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | 西班牙甲级联赛 | 26 | 25 | 96.1538% | UNIVERSAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ah_line_water` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 瑞典超级联赛 | 12 | 11 | 91.6667% | BROAD | NO_FROZEN_OU_LINE_WITH_BOTH_WATERS=1 |
| `market_ou_line_water` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 英格兰超级联赛 | 17 | 16 | 94.1176% | BROAD | NO_FROZEN_OU_LINE_WITH_BOTH_WATERS=1 |
| `market_ou_line_water` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | UNKNOWN | 1 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 南美解放者杯 | 5 | 4 | 80.0000% | BROAD | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 巴西杯 | 5 | 2 | 40.0000% | SPARSE | NO_RESULT_ARTIFACT=2, RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 德乙 | 1 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 德国杯 | 1 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 德国甲级联赛 | 6 | 5 | 83.3333% | BROAD | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 德甲 | 9 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=8, RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 意杯 | 3 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=3 |
| `verified_result_linkage` | 意甲 | 8 | 1 | 12.5000% | SPARSE | NO_RESULT_ARTIFACT=7 |
| `verified_result_linkage` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 挪超 | 1 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 日本乙级联赛 | 5 | 4 | 80.0000% | BROAD | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 日职乙 | 1 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 日职联 | 7 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=4, RESULT_ARTIFACT_UNRESOLVED=3 |
| `verified_result_linkage` | 日联杯 | 1 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 沙特联 | 5 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=5 |
| `verified_result_linkage` | 法乙 | 1 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 法国乙级联赛 | 7 | 6 | 85.7143% | BROAD | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 法国甲级联赛 | 9 | 8 | 88.8889% | BROAD | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 法甲 | 7 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=4, RESULT_ARTIFACT_UNRESOLVED=3 |
| `verified_result_linkage` | 瑞典超 | 1 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 美国职业大联盟 | 5 | 4 | 80.0000% | BROAD | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 美职业 | 1 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 英冠 | 12 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=1, RESULT_ARTIFACT_UNRESOLVED=11 |
| `verified_result_linkage` | 英格兰冠军联赛 | 6 | 4 | 66.6667% | PARTIAL | NO_RESULT_ARTIFACT=2 |
| `verified_result_linkage` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 英超 | 9 | 1 | 11.1111% | SPARSE | NO_RESULT_ARTIFACT=8 |
| `verified_result_linkage` | 荷乙 | 1 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 荷甲 | 3 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=2, RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 葡萄牙超级联赛 | 11 | 10 | 90.9091% | BROAD | NO_RESULT_ARTIFACT=1 |
| `verified_result_linkage` | 葡超 | 3 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=2, RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 西班牙甲级联赛 | 26 | 24 | 92.3077% | BROAD | NO_RESULT_ARTIFACT=2 |
| `verified_result_linkage` | 西甲 | 9 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=8, RESULT_ARTIFACT_UNRESOLVED=1 |
| `verified_result_linkage` | 韩K联 | 3 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=3 |
| `verified_result_linkage` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | 韩国职业联赛 | 14 | 13 | 92.8571% | BROAD | NO_RESULT_ARTIFACT=1 |
| `forecast_lead_time` | UNKNOWN | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 南美解放者杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 巴西杯 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 巴西甲 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 巴西甲级联赛 | 4 | 4 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 德乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 德国乙级联赛 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 德国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 德国甲级联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 德国超级杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 德甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 意大利甲级联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 意杯 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 意甲 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 挪威超级联赛 | 8 | 8 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 挪超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 日本乙级联赛 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 日本职业联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 日职乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 日职联 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 日联杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 欧洲冠军联赛 | 10 | 10 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 欧罗巴联赛 | 16 | 16 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 沙特职业联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 沙特联 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 法乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 法国乙级联赛 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 法国甲级联赛 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 法甲 | 7 | 7 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 瑞典超 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 瑞典超级联赛 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 美国职业大联盟 | 5 | 5 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 美职业 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 芬兰超级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 英冠 | 12 | 12 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 英格兰冠军联赛 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 英格兰社区盾杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 英格兰联赛杯 | 6 | 6 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 英格兰超级联赛 | 17 | 17 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 英超 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 荷乙 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 荷兰乙级联赛 | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 荷兰甲级联赛 | 18 | 18 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 荷甲 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 葡萄牙超级联赛 | 11 | 11 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 葡超 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 西班牙甲级联赛 | 26 | 26 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 西甲 | 9 | 9 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 韩K联 | 3 | 3 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 韩国杯 | 1 | 1 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | 韩国职业联赛 | 14 | 14 | 100.0000% | UNIVERSAL | — |

### provider
| Field | Slice | Eligible | Present | Coverage | Label | Missing reasons |
|---|---|---:|---:|---:|---|---|
| `match_identity` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `match_identity` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `competition` | nowscore | 315 | 314 | 99.6825% | UNIVERSAL | MISSING_AUTHORITATIVE_COMPETITION=1 |
| `competition` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `kickoff` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `kickoff` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `serving_state` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `serving_state` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `full_score_distribution` | nowscore | 315 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=315 |
| `full_score_distribution` | sporttery | 2 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=2 |
| `total_goals` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `total_goals` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `btts` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `btts` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `lineup_publication` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=315 |
| `lineup_publication` | sporttery | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=2 |
| `injuries_availability` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=315 |
| `injuries_availability` | sporttery | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=2 |
| `weather` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=315 |
| `weather` | sporttery | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=2 |
| `venue_h2h` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=315 |
| `venue_h2h` | sporttery | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=2 |
| `market_1x2_quotes` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | sporttery | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_1X2_QUOTE_ROWS=2 |
| `market_ah_line_water` | nowscore | 315 | 311 | 98.7302% | UNIVERSAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=4 |
| `market_ah_line_water` | sporttery | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=2 |
| `market_ou_line_water` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | sporttery | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_OU_LINE_WITH_BOTH_WATERS=2 |
| `market_snapshot_timestamp` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | nowscore | 315 | 214 | 67.9365% | PARTIAL | NO_RESULT_ARTIFACT=64, RESULT_ARTIFACT_UNRESOLVED=37 |
| `verified_result_linkage` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | sporttery | 2 | 2 | 100.0000% | UNIVERSAL | — |

### source
| Field | Slice | Eligible | Present | Coverage | Label | Missing reasons |
|---|---|---:|---:|---:|---|---|
| `match_identity` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `match_identity` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `competition` | nowscore | 315 | 314 | 99.6825% | UNIVERSAL | MISSING_AUTHORITATIVE_COMPETITION=1 |
| `competition` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `kickoff` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `kickoff` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `serving_state` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `serving_state` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `full_score_distribution` | nowscore | 315 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=315 |
| `full_score_distribution` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=2 |
| `total_goals` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `total_goals` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `btts` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `btts` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `lineup_publication` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=315 |
| `lineup_publication` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=2 |
| `injuries_availability` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=315 |
| `injuries_availability` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=2 |
| `weather` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=315 |
| `weather` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=2 |
| `venue_h2h` | nowscore | 315 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=315 |
| `venue_h2h` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=2 |
| `market_1x2_quotes` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_1X2_QUOTE_ROWS=2 |
| `market_ah_line_water` | nowscore | 315 | 311 | 98.7302% | UNIVERSAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=4 |
| `market_ah_line_water` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=2 |
| `market_ou_line_water` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | sporttery_spf | 2 | 0 | 0.0000% | SPARSE | NO_FROZEN_OU_LINE_WITH_BOTH_WATERS=2 |
| `market_snapshot_timestamp` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | nowscore | 315 | 214 | 67.9365% | PARTIAL | NO_RESULT_ARTIFACT=64, RESULT_ARTIFACT_UNRESOLVED=37 |
| `verified_result_linkage` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | nowscore | 315 | 315 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | sporttery_spf | 2 | 2 | 100.0000% | UNIVERSAL | — |

### data_grade
| Field | Slice | Eligible | Present | Coverage | Label | Missing reasons |
|---|---|---:|---:|---:|---|---|
| `match_identity` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `competition` | C | 317 | 316 | 99.6845% | UNIVERSAL | MISSING_AUTHORITATIVE_COMPETITION=1 |
| `kickoff` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `serving_state` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `full_score_distribution` | C | 317 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=317 |
| `total_goals` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `btts` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `lineup_publication` | C | 317 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=317 |
| `injuries_availability` | C | 317 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=317 |
| `weather` | C | 317 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=317 |
| `venue_h2h` | C | 317 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=317 |
| `market_1x2_quotes` | C | 317 | 315 | 99.3691% | UNIVERSAL | NO_FROZEN_1X2_QUOTE_ROWS=2 |
| `market_ah_line_water` | C | 317 | 311 | 98.1073% | UNIVERSAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=6 |
| `market_ou_line_water` | C | 317 | 315 | 99.3691% | UNIVERSAL | NO_FROZEN_OU_LINE_WITH_BOTH_WATERS=2 |
| `market_snapshot_timestamp` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | C | 317 | 216 | 68.1388% | PARTIAL | NO_RESULT_ARTIFACT=64, RESULT_ARTIFACT_UNRESOLVED=37 |
| `forecast_lead_time` | C | 317 | 317 | 100.0000% | UNIVERSAL | — |

### settlement
| Field | Slice | Eligible | Present | Coverage | Label | Missing reasons |
|---|---|---:|---:|---:|---|---|
| `match_identity` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `match_identity` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `match_identity` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `competition` | CURRENT_UNSETTLED | 64 | 63 | 98.4375% | UNIVERSAL | MISSING_AUTHORITATIVE_COMPETITION=1 |
| `competition` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `competition` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `kickoff` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `kickoff` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `kickoff` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `serving_state` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `serving_state` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `serving_state` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `frozen_1x2` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `exact_score_top1` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `exact_score_top3` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `exact_score_top5` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `full_score_distribution` | CURRENT_UNSETTLED | 64 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=64 |
| `full_score_distribution` | RESULT_LINKED_UNRESOLVED | 37 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=37 |
| `full_score_distribution` | SETTLED_VERIFIED | 216 | 0 | 0.0000% | SPARSE | TOP_K_ONLY_NO_EXPLICIT_FULL_DISTRIBUTION_FLAG=216 |
| `total_goals` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `total_goals` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `total_goals` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `btts` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `btts` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `btts` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `source_cutoff` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `freeze_timestamp` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `recent_form_aggregate` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `home_away_recent_form` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `lineup_publication` | CURRENT_UNSETTLED | 64 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=64 |
| `lineup_publication` | RESULT_LINKED_UNRESOLVED | 37 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=37 |
| `lineup_publication` | SETTLED_VERIFIED | 216 | 0 | 0.0000% | SPARSE | NO_FROZEN_LINEUP_PUBLICATION_RECORD=216 |
| `injuries_availability` | CURRENT_UNSETTLED | 64 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=64 |
| `injuries_availability` | RESULT_LINKED_UNRESOLVED | 37 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=37 |
| `injuries_availability` | SETTLED_VERIFIED | 216 | 0 | 0.0000% | SPARSE | NO_FROZEN_INJURY_AVAILABILITY_RECORD=216 |
| `weather` | CURRENT_UNSETTLED | 64 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=64 |
| `weather` | RESULT_LINKED_UNRESOLVED | 37 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=37 |
| `weather` | SETTLED_VERIFIED | 216 | 0 | 0.0000% | SPARSE | NO_FROZEN_WEATHER_RECORD=216 |
| `venue_h2h` | CURRENT_UNSETTLED | 64 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=64 |
| `venue_h2h` | RESULT_LINKED_UNRESOLVED | 37 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=37 |
| `venue_h2h` | SETTLED_VERIFIED | 216 | 0 | 0.0000% | SPARSE | NO_FROZEN_VENUE_OR_H2H_RECORD=216 |
| `market_1x2_quotes` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `market_1x2_quotes` | SETTLED_VERIFIED | 216 | 214 | 99.0741% | UNIVERSAL | NO_FROZEN_1X2_QUOTE_ROWS=2 |
| `market_ah_line_water` | CURRENT_UNSETTLED | 64 | 63 | 98.4375% | UNIVERSAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | RESULT_LINKED_UNRESOLVED | 37 | 36 | 97.2973% | UNIVERSAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=1 |
| `market_ah_line_water` | SETTLED_VERIFIED | 216 | 212 | 98.1481% | UNIVERSAL | NO_FROZEN_AH_LINE_WITH_BOTH_WATERS=4 |
| `market_ou_line_water` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `market_ou_line_water` | SETTLED_VERIFIED | 216 | 214 | 99.0741% | UNIVERSAL | NO_FROZEN_OU_LINE_WITH_BOTH_WATERS=2 |
| `market_snapshot_timestamp` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `market_snapshot_timestamp` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `market_source_age_inputs` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `market_input_quality` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `verified_result_linkage` | CURRENT_UNSETTLED | 64 | 0 | 0.0000% | SPARSE | NO_RESULT_ARTIFACT=64 |
| `verified_result_linkage` | RESULT_LINKED_UNRESOLVED | 37 | 0 | 0.0000% | SPARSE | RESULT_ARTIFACT_UNRESOLVED=37 |
| `verified_result_linkage` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | CURRENT_UNSETTLED | 64 | 64 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | RESULT_LINKED_UNRESOLVED | 37 | 37 | 100.0000% | UNIVERSAL | — |
| `forecast_lead_time` | SETTLED_VERIFIED | 216 | 216 | 100.0000% | UNIVERSAL | — |


## C. Actual prematch freeze horizon

The raw distribution is reported before descriptive bands. Lead time is `kickoff_at - freeze_created_at`, using explicit timezone-aware frozen timestamps only; no source timestamp or guessed window is substituted.

### Raw lead-time distribution

- Eligible unique matches: 317
- Safe unique matches: 317
- Unsafe unique matches: 0
- min / p10 / p25 / median / p75 / p90 / max (minutes): 1.583973 / 45.736768 / 173.556499 / 472.314056 / 851.693585 / 1043.704741 / 2724.651485

```json
{
  "eligible_unique_matches": 317,
  "minutes_sorted": [
    1.583973,
    2.436985,
    2.758693,
    2.94526,
    6.468916,
    6.692649,
    6.901883,
    6.931144,
    7.12288,
    7.265286,
    7.332011,
    8.828231,
    9.044661,
    10.251418,
    13.58905,
    17.123054,
    24.274011,
    24.684344,
    24.83218,
    24.944479,
    25.248583,
    27.893595,
    32.161507,
    35.900743,
    36.133066,
    37.046795,
    38.106159,
    38.363936,
    38.617595,
    38.982039,
    40.246265,
    43.117198,
    47.483147,
    52.220139,
    53.28523,
    53.652014,
    55.016558,
    55.396312,
    56.937026,
    69.774008,
    71.672557,
    72.046354,
    72.270088,
    72.66727,
    76.950364,
    81.946078,
    84.33619,
    84.592354,
    84.873191,
    85.995235,
    86.063716,
    86.224037,
    86.276432,
    99.724837,
    99.977457,
    100.215582,
    100.426549,
    100.64159,
    108.322701,
    108.911216,
    111.497933,
    113.795034,
    114.048977,
    121.195627,
    121.397155,
    122.484794,
    123.015503,
    126.071321,
    126.362973,
    126.650717,
    130.167618,
    130.781131,
    140.732618,
    142.382514,
    142.658261,
    142.935492,
    144.745837,
    157.452628,
    157.692454,
    173.556499,
    180.892142,
    181.240855,
    181.331055,
    181.562987,
    181.579375,
    181.821558,
    181.839948,
    183.5607,
    187.014412,
    187.21341,
    187.340945,
    188.334123,
    196.068209,
    196.373449,
    196.583822,
    200.605361,
    201.955479,
    205.553615,
    205.763271,
    210.347973,
    210.642199,
    224.937782,
    226.837776,
    231.278698,
    231.483926,
    231.721895,
    242.467967,
    242.790138,
    243.081891,
    256.192966,
    256.436212,
    256.657659,
    260.974026,
    272.109272,
    286.396909,
    286.812817,
    301.39244,
    315.881319,
    316.1356,
    330.809341,
    335.240335,
    336.796918,
    339.355328,
    349.848384,
    350.072391,
    369.188951,
    374.994537,
    375.201179,
    375.420586,
    375.651422,
    378.963831,
    383.0893,
    383.279788,
    385.672342,
    385.833538,
    399.007195,
    404.721377,
    408.548585,
    408.760089,
    416.214779,
    419.488491,
    428.82888,
    434.038261,
    434.27828,
    435.7205,
    439.326704,
    442.716928,
    442.906151,
    445.485187,
    450.508633,
    458.636347,
    463.7068,
    465.068009,
    465.303848,
    465.843088,
    468.895692,
    469.534797,
    469.800198,
    472.314056,
    472.511491,
    488.418941,
    498.492572,
    500.754231,
    504.78872,
    517.620334,
    517.825014,
    519.213844,
    531.11538,
    532.100045,
    554.69757,
    558.084746,
    565.996851,
    584.104738,
    584.311379,
    591.201586,
    607.182193,
    609.062988,
    615.490378,
    617.600873,
    617.806967,
    620.973912,
    632.353656,
    639.603285,
    642.821617,
    647.142151,
    668.597609,
    670.699298,
    681.405623,
    681.638778,
    681.875723,
    696.951771,
    700.73419,
    703.029894,
    703.426942,
    706.819143,
    710.989993,
    711.191245,
    714.598074,
    717.79982,
    726.279296,
    726.506673,
    730.484334,
    731.911369,
    732.185567,
    732.421628,
    736.615172,
    737.223189,
    740.737807,
    753.387102,
    754.91136,
    755.143051,
    755.504235,
    755.55567,
    755.871901,
    756.108433,
    760.189121,
    765.083187,
    765.29213,
    766.849827,
    790.031945,
    790.286988,
    793.295137,
    793.501076,
    796.639019,
    815.199693,
    815.413274,
    824.878228,
    830.294553,
    834.618726,
    834.811643,
    842.667709,
    842.904666,
    849.291231,
    849.320455,
    849.825006,
    851.510621,
    851.532039,
    851.693585,
    852.248904,
    853.088946,
    855.874264,
    856.304928,
    856.591752,
    857.392327,
    859.373752,
    859.62722,
    859.874194,
    866.219189,
    874.33206,
    878.955596,
    880.991786,
    885.797079,
    895.452682,
    903.720176,
    904.113526,
    907.585048,
    909.602197,
    912.770198,
    913.295412,
    913.51636,
    915.606481,
    944.806119,
    945.073312,
    945.36408,
    949.524343,
    955.270478,
    957.458344,
    963.543023,
    963.815333,
    964.032282,
    964.268974,
    970.976971,
    972.053655,
    976.306453,
    978.670264,
    978.886458,
    979.13256,
    979.582819,
    980.47032,
    993.317377,
    1000.491115,
    1000.712155,
    1008.285068,
    1029.71474,
    1038.084133,
    1052.135653,
    1052.71463,
    1059.354022,
    1088.773727,
    1150.265669,
    1159.355803,
    1163.792259,
    1201.862707,
    1301.167117,
    1304.560545,
    1310.334868,
    1892.137901,
    2077.65937,
    2077.822949,
    2101.08422,
    2107.496575,
    2128.273782,
    2130.399594,
    2130.625938,
    2130.86543,
    2204.75088,
    2279.058186,
    2279.296955,
    2286.417403,
    2338.479072,
    2346.068514,
    2366.754985,
    2435.517908,
    2575.402498,
    2599.844862,
    2710.017436,
    2724.651485
  ],
  "missing_reasons": {},
  "safe_unique_matches": 317,
  "statistics_minutes": {
    "max": 2724.651485,
    "median": 472.314056,
    "min": 1.583973,
    "p10": 45.736768,
    "p25": 173.556499,
    "p75": 851.693585,
    "p90": 1043.704741
  },
  "unsafe_unique_matches": 0
}
```

### Deterministic descriptive bands and coverage

Bands use lower-inclusive / upper-exclusive intervals; `T-24h+` has no upper bound. Weak horizon is fixed to the first two bands (`<3h`) for descriptive concentration reporting only.

| Band | Unique matches | Share |
|---|---:|---:|
| T-0 to <60m (`T_0_TO_60M`) | 39 | 12.3028% |
| T-60m to <3h (`T_60_TO_180M`) | 41 | 12.9338% |
| T-3h to <6h (`T_3_TO_6H`) | 45 | 14.1956% |
| T-6h to <12h (`T_6_TO_12H`) | 74 | 23.3438% |
| T-12h to <24h (`T_12_TO_24H`) | 97 | 30.5994% |
| T-24h+ (`T_24H_PLUS`) | 21 | 6.6246% |

Field coverage by every horizon band is persisted in `summary.json` under `horizon_map.bands[].field_coverage`. Weak-competition concentration is below.

| Competition | Unique matches | Weak-horizon matches | Weak-horizon share | Material concentration | Band counts |
|---|---:|---:|---:|---|---|
| UNKNOWN | 1 | 0 | 0.0000% | False | {"T_12_TO_24H": 1} |
| 南美解放者杯 | 5 | 0 | 0.0000% | False | {"T_12_TO_24H": 4, "T_6_TO_12H": 1} |
| 巴西杯 | 5 | 4 | 80.0000% | True | {"T_0_TO_60M": 1, "T_60_TO_180M": 3, "T_6_TO_12H": 1} |
| 巴西甲 | 1 | 1 | 100.0000% | False | {"T_0_TO_60M": 1} |
| 巴西甲级联赛 | 4 | 1 | 25.0000% | False | {"T_12_TO_24H": 3, "T_60_TO_180M": 1} |
| 德乙 | 1 | 0 | 0.0000% | False | {"T_3_TO_6H": 1} |
| 德国乙级联赛 | 3 | 1 | 33.3333% | False | {"T_0_TO_60M": 1, "T_6_TO_12H": 2} |
| 德国杯 | 1 | 0 | 0.0000% | False | {"T_3_TO_6H": 1} |
| 德国甲级联赛 | 6 | 4 | 66.6667% | True | {"T_0_TO_60M": 1, "T_3_TO_6H": 2, "T_60_TO_180M": 3} |
| 德国超级杯 | 1 | 0 | 0.0000% | False | {"T_12_TO_24H": 1} |
| 德甲 | 9 | 0 | 0.0000% | False | {"T_12_TO_24H": 6, "T_24H_PLUS": 2, "T_6_TO_12H": 1} |
| 意大利甲级联赛 | 16 | 7 | 43.7500% | False | {"T_0_TO_60M": 5, "T_12_TO_24H": 5, "T_3_TO_6H": 2, "T_60_TO_180M": 2, "T_6_TO_12H": 2} |
| 意杯 | 3 | 3 | 100.0000% | True | {"T_0_TO_60M": 1, "T_60_TO_180M": 2} |
| 意甲 | 8 | 0 | 0.0000% | False | {"T_12_TO_24H": 2, "T_24H_PLUS": 4, "T_6_TO_12H": 2} |
| 挪威超级联赛 | 8 | 1 | 12.5000% | False | {"T_0_TO_60M": 1, "T_12_TO_24H": 4, "T_6_TO_12H": 3} |
| 挪超 | 1 | 0 | 0.0000% | False | {"T_3_TO_6H": 1} |
| 日本乙级联赛 | 5 | 0 | 0.0000% | False | {"T_6_TO_12H": 5} |
| 日本职业联赛 | 10 | 0 | 0.0000% | False | {"T_3_TO_6H": 3, "T_6_TO_12H": 7} |
| 日职乙 | 1 | 0 | 0.0000% | False | {"T_6_TO_12H": 1} |
| 日职联 | 7 | 0 | 0.0000% | False | {"T_24H_PLUS": 3, "T_3_TO_6H": 3, "T_6_TO_12H": 1} |
| 日联杯 | 1 | 0 | 0.0000% | False | {"T_3_TO_6H": 1} |
| 欧洲冠军联赛 | 10 | 5 | 50.0000% | True | {"T_0_TO_60M": 2, "T_12_TO_24H": 5, "T_60_TO_180M": 3} |
| 欧罗巴联赛 | 16 | 3 | 18.7500% | False | {"T_12_TO_24H": 9, "T_3_TO_6H": 3, "T_60_TO_180M": 3, "T_6_TO_12H": 1} |
| 沙特职业联赛 | 2 | 0 | 0.0000% | False | {"T_12_TO_24H": 2} |
| 沙特联 | 5 | 4 | 80.0000% | True | {"T_0_TO_60M": 2, "T_60_TO_180M": 2, "T_6_TO_12H": 1} |
| 法乙 | 1 | 0 | 0.0000% | False | {"T_6_TO_12H": 1} |
| 法国乙级联赛 | 7 | 0 | 0.0000% | False | {"T_12_TO_24H": 5, "T_3_TO_6H": 2} |
| 法国甲级联赛 | 9 | 2 | 22.2222% | False | {"T_0_TO_60M": 1, "T_12_TO_24H": 4, "T_3_TO_6H": 1, "T_60_TO_180M": 1, "T_6_TO_12H": 2} |
| 法甲 | 7 | 1 | 14.2857% | False | {"T_0_TO_60M": 1, "T_12_TO_24H": 2, "T_24H_PLUS": 2, "T_3_TO_6H": 1, "T_6_TO_12H": 1} |
| 瑞典超 | 1 | 0 | 0.0000% | False | {"T_3_TO_6H": 1} |
| 瑞典超级联赛 | 12 | 3 | 25.0000% | False | {"T_0_TO_60M": 2, "T_12_TO_24H": 3, "T_60_TO_180M": 1, "T_6_TO_12H": 6} |
| 美国职业大联盟 | 5 | 2 | 40.0000% | False | {"T_0_TO_60M": 1, "T_12_TO_24H": 3, "T_60_TO_180M": 1} |
| 美职业 | 1 | 1 | 100.0000% | False | {"T_0_TO_60M": 1} |
| 芬兰超级联赛 | 2 | 0 | 0.0000% | False | {"T_12_TO_24H": 2} |
| 英冠 | 12 | 9 | 75.0000% | True | {"T_0_TO_60M": 1, "T_3_TO_6H": 3, "T_60_TO_180M": 8} |
| 英格兰冠军联赛 | 6 | 0 | 0.0000% | False | {"T_12_TO_24H": 1, "T_6_TO_12H": 5} |
| 英格兰社区盾杯 | 1 | 0 | 0.0000% | False | {"T_6_TO_12H": 1} |
| 英格兰联赛杯 | 6 | 6 | 100.0000% | True | {"T_0_TO_60M": 2, "T_60_TO_180M": 4} |
| 英格兰超级联赛 | 17 | 5 | 29.4118% | False | {"T_0_TO_60M": 3, "T_12_TO_24H": 3, "T_3_TO_6H": 3, "T_60_TO_180M": 2, "T_6_TO_12H": 6} |
| 英超 | 9 | 0 | 0.0000% | False | {"T_12_TO_24H": 5, "T_24H_PLUS": 2, "T_6_TO_12H": 2} |
| 荷乙 | 1 | 0 | 0.0000% | False | {"T_6_TO_12H": 1} |
| 荷兰乙级联赛 | 2 | 0 | 0.0000% | False | {"T_12_TO_24H": 1, "T_3_TO_6H": 1} |
| 荷兰甲级联赛 | 18 | 3 | 16.6667% | False | {"T_0_TO_60M": 2, "T_12_TO_24H": 4, "T_3_TO_6H": 4, "T_60_TO_180M": 1, "T_6_TO_12H": 7} |
| 荷甲 | 3 | 0 | 0.0000% | False | {"T_12_TO_24H": 1, "T_24H_PLUS": 1, "T_6_TO_12H": 1} |
| 葡萄牙超级联赛 | 11 | 2 | 18.1818% | False | {"T_0_TO_60M": 2, "T_12_TO_24H": 5, "T_3_TO_6H": 2, "T_6_TO_12H": 2} |
| 葡超 | 3 | 1 | 33.3333% | False | {"T_0_TO_60M": 1, "T_12_TO_24H": 1, "T_24H_PLUS": 1} |
| 西班牙甲级联赛 | 26 | 8 | 30.7692% | False | {"T_0_TO_60M": 5, "T_12_TO_24H": 12, "T_3_TO_6H": 5, "T_60_TO_180M": 3, "T_6_TO_12H": 1} |
| 西甲 | 9 | 1 | 11.1111% | False | {"T_12_TO_24H": 3, "T_24H_PLUS": 4, "T_60_TO_180M": 1, "T_6_TO_12H": 1} |
| 韩K联 | 3 | 0 | 0.0000% | False | {"T_24H_PLUS": 2, "T_6_TO_12H": 1} |
| 韩国杯 | 1 | 0 | 0.0000% | False | {"T_6_TO_12H": 1} |
| 韩国职业联赛 | 14 | 2 | 14.2857% | False | {"T_0_TO_60M": 2, "T_3_TO_6H": 5, "T_6_TO_12H": 7} |

## D. Change Awareness previous-comparable snapshot

Only formal-reader-accepted legal prematch versions are considered. For each unique match with at least two legal versions, the current snapshot is the latest legal version and the previous snapshot is the immediately preceding legal version by frozen timestamp. This section does not use result artifacts to select either version and provides no causal interpretation.

```json
{
  "invalid_version_rows": 0,
  "legal_prematch_version_rows": 1444,
  "not_pairable_reasons": {},
  "pairable_matches": 173,
  "pairable_percent": 100.0,
  "safe_previous_comparable_matches": 173,
  "safe_previous_comparable_percent": 100.0,
  "surface_diff_status_counts": {
    "1x2": {
      "CHANGED": 136,
      "UNCHANGED": 37
    },
    "asian_handicap": {
      "CHANGED": 149,
      "NOT_DIFFABLE": 7,
      "UNCHANGED": 17
    },
    "exact_top1_top3": {
      "CHANGED": 136,
      "UNCHANGED": 37
    },
    "frozen_evidence": {
      "CHANGED": 173
    },
    "over_under": {
      "CHANGED": 148,
      "NOT_DIFFABLE": 3,
      "UNCHANGED": 22
    }
  },
  "surface_pairability": {
    "1x2": 173,
    "asian_handicap": 166,
    "exact_top1_top3": 173,
    "frozen_evidence": 173,
    "over_under": 170
  },
  "unique_matches_with_multiple_legal_prematch_versions": 173
}
```

### Per-match chronology and diffability

| Match key | Competition | Legal versions | Previous safe | Gap (min) | 1X2 diff | Exact Top1+Top3 diff | AH diff | O/U diff | Frozen evidence diff | Not-pairable reasons |
|---|---|---:|---|---:|---|---|---|---|---|---|
| `FBOS-202608260245-a9118e0810` | 英格兰联赛杯 | 2 | True | 588.690565 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608260300-23d6c1eed0` | 西班牙甲级联赛 | 3 | True | 118.848904 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608260300-2f875f6259` | 欧洲冠军联赛 | 3 | True | 118.905692 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608260300-4797271b30` | 英格兰联赛杯 | 3 | True | 118.82857 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608260300-710d2470b0` | 英格兰联赛杯 | 3 | True | 118.854827 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608260300-91aca455d3` | 欧洲冠军联赛 | 3 | True | 118.96545 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608261830-ae9a5ea41b` | 韩国职业联赛 | 10 | True | 56.815926 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608261830-b968d86c1d` | 韩国职业联赛 | 10 | True | 56.709633 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270245-010ed6f4a1` | 英格兰联赛杯 | 16 | True | 22.461768 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270245-f065f8793c` | 英格兰联赛杯 | 16 | True | 22.40319 | CHANGED | CHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202608270300-0c5ae31bd7` | 英格兰联赛杯 | 14 | True | 21.89464 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270300-3ddac2f1f8` | 欧洲冠军联赛 | 18 | True | 22.072138 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270300-7962ab88e3` | 欧洲冠军联赛 | 16 | True | 21.957119 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270300-96f5de7648` | 欧洲冠军联赛 | 18 | True | 21.973243 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270300-db11228440` | 西班牙甲级联赛 | 18 | True | 21.737865 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270830-56ecec1b70` | 巴西杯 | 15 | True | 192.950513 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608270830-c5671d2d51` | 巴西杯 | 18 | True | 192.991046 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280100-3c9760e5f8` | 欧罗巴联赛 | 4 | True | 236.687019 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280100-4d7817bdd5` | 欧罗巴联赛 | 3 | True | 258.013861 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280100-c71929d8a4` | 欧罗巴联赛 | 4 | True | 236.72289 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280200-2578f83226` | 欧罗巴联赛 | 3 | True | 235.682663 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280230-85983132fc` | 欧罗巴联赛 | 4 | True | 235.639927 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280230-bd20918d08` | 欧罗巴联赛 | 4 | True | 235.617535 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280230-cf1b3370e0` | 西班牙甲级联赛 | 5 | True | 235.62263 | CHANGED | CHANGED | NOT_DIFFABLE | NOT_DIFFABLE | CHANGED | — |
| `FBOS-202608280300-827db91a0d` | 西班牙甲级联赛 | 5 | True | 235.610641 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608280700-7d928c6dcb` | 巴西杯 | 5 | True | 235.588566 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608290100-18dfb7e9df` | 西班牙甲级联赛 | 5 | True | 160.3307 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608290200-18f3735b53` | 荷兰甲级联赛 | 5 | True | 160.547278 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608290200-8670e17d82` | 法国乙级联赛 | 5 | True | 160.462312 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608290200-cc085d9cc6` | 荷兰乙级联赛 | 5 | True | 160.661802 | CHANGED | CHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202608290230-0a22a3adb3` | 德国甲级联赛 | 5 | True | 160.769744 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608290245-86b5c937a4` | 意大利甲级联赛 | 5 | True | 160.837433 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608290300-a88bc3fa35` | 英格兰超级联赛 | 5 | True | 160.840333 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608290330-d9c7b7118b` | 西班牙甲级联赛 | 5 | True | 160.946971 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608292100-21c3ea757c` | 瑞典超级联赛 | 2 | True | 522.833637 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608292130-4915373995` | 德国甲级联赛 | 2 | True | 522.996678 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608292130-c460378ee5` | 德国甲级联赛 | 2 | True | 522.979905 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608292200-3668cc2366` | 英格兰超级联赛 | 2 | True | 523.077247 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608292300-b8036f9762` | 西班牙甲级联赛 | 2 | True | 523.194266 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608292315-e037b78b36` | 法国甲级联赛 | 2 | True | 523.216348 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300030-173996ba53` | 英格兰超级联赛 | 3 | True | 44.646235 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300030-2332e71505` | 意大利甲级联赛 | 4 | True | 44.601104 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300030-b284e94c16` | 德国甲级联赛 | 3 | True | 44.672077 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300030-ba773f40b9` | 意大利甲级联赛 | 3 | True | 44.520685 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300045-04a25a1ad9` | 荷兰甲级联赛 | 4 | True | 44.555693 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300100-c1c6f9a466` | 葡萄牙超级联赛 | 4 | True | 44.708108 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300100-d76acfaa2a` | 西班牙甲级联赛 | 4 | True | 44.58645 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300245-dd2d5dc45f` | 意大利甲级联赛 | 6 | True | 57.136187 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300330-c7af399447` | 西班牙甲级联赛 | 7 | True | 36.694143 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608300730-f27653808e` | 美国职业大联盟 | 9 | True | 54.756338 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608301815-e2551b7616` | 荷兰甲级联赛 | 3 | True | 86.119219 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608301830-61d5c05bf5` | 韩国职业联赛 | 3 | True | 86.160383 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608301830-b076c9a937` | 韩国职业联赛 | 2 | True | 86.163524 | UNCHANGED | UNCHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202608301930-f13be44452` | 德国乙级联赛 | 5 | True | 49.919544 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302000-a4e915a22d` | 瑞典超级联赛 | 5 | True | 49.908186 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302030-56608cd4cb` | 荷兰甲级联赛 | 5 | True | 57.795021 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302030-e7ed2bd3e5` | 挪威超级联赛 | 6 | True | 57.778943 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302100-33647ada3d` | 英格兰超级联赛 | 6 | True | 57.796856 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302100-4bbe7e7593` | 英格兰超级联赛 | 6 | True | 57.781156 | CHANGED | CHANGED | NOT_DIFFABLE | NOT_DIFFABLE | CHANGED | — |
| `FBOS-202608302100-9045b65c0e` | 法国甲级联赛 | 5 | True | 57.851012 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302245-937c28f3f7` | 荷兰甲级联赛 | 5 | True | 49.242179 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302300-f7c819b9a7` | 西班牙甲级联赛 | 6 | True | 57.796529 | UNCHANGED | UNCHANGED | NOT_DIFFABLE | CHANGED | CHANGED | — |
| `FBOS-202608302330-3488780e79` | 英格兰超级联赛 | 5 | True | 57.783999 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608302330-f1c8cc9a15` | 德国甲级联赛 | 5 | True | 57.754002 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310030-d4e3b34791` | 意大利甲级联赛 | 7 | True | 244.332671 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310130-3ece2285eb` | 西班牙甲级联赛 | 8 | True | 9.930024 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310200-45c20faf16` | 荷兰甲级联赛 | 6 | True | 9.853072 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310245-9bf0da2c06` | 法国甲级联赛 | 7 | True | 9.873503 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310245-c3f8734cde` | 意大利甲级联赛 | 8 | True | 9.89088 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310245-efe897a8e6` | 意大利甲级联赛 | 7 | True | 9.836876 | UNCHANGED | UNCHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202608310300-910132c529` | 巴西甲级联赛 | 7 | True | 9.875931 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310330-dcee94a3cb` | 葡萄牙超级联赛 | 9 | True | 167.447952 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310330-ebf8ea8163` | 西班牙甲级联赛 | 11 | True | 167.493165 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202608310700-1a4ca05d83` | 美国职业大联盟 | 8 | True | 322.951264 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609010030-aa50d55edc` | 意大利甲级联赛 | 6 | True | 106.316759 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609010100-28f0df8c97` | 瑞典超级联赛 | 7 | True | 106.38707 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609010100-dc27e2679d` | 瑞典超级联赛 | 3 | True | 186.900256 | CHANGED | CHANGED | NOT_DIFFABLE | NOT_DIFFABLE | CHANGED | — |
| `FBOS-202609010245-1c07512e55` | 法国乙级联赛 | 7 | True | 106.294526 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609010245-203b078189` | 意大利甲级联赛 | 7 | True | 106.328376 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609010300-7c61d91bce` | 英格兰超级联赛 | 7 | True | 106.242384 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609010315-4d787db3f3` | 葡萄牙超级联赛 | 7 | True | 106.235653 | CHANGED | CHANGED | NOT_DIFFABLE | CHANGED | CHANGED | — |
| `FBOS-202609010315-6cd2253355` | 葡萄牙超级联赛 | 6 | True | 106.255529 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609010330-d316e7142d` | 西班牙甲级联赛 | 7 | True | 106.293003 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020200-af3a8a4a89` | 沙特联 | 10 | True | 58.374654 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020245-1a0eeb4eea` | 英冠 | 6 | True | 66.201536 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020245-2146533297` | 英冠 | 5 | True | 65.937352 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020245-2d48f7532b` | 英冠 | 10 | True | 58.403171 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020245-41c2bfc27e` | 英冠 | 7 | True | 58.267335 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020245-723f2752da` | 英冠 | 7 | True | 58.285755 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020245-cce88b7c9e` | 英冠 | 10 | True | 58.30857 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020300-bd6bc31879` | 英冠 | 9 | True | 58.227193 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020300-f884e4bdb3` | 意杯 | 10 | True | 58.227818 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609020300-f95a1a6071` | 英冠 | 9 | True | 65.68253 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609021730-210bdaebc8` | 日联杯 | 10 | True | 180.606816 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609021800-71d3eff633` | 日职联 | 13 | True | 180.595892 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609021800-cc0849bb81` | 日职联 | 13 | True | 180.609145 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609021800-d5a4716579` | 日职联 | 9 | True | 180.589028 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609022100-a51812db34` | 意杯 | 14 | True | 327.061755 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030000-9498793c32` | 意杯 | 17 | True | 25.069982 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030245-6e7fb294ea` | 英冠 | 5 | True | 25.000465 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030245-71258434c8` | 英冠 | 6 | True | 25.039963 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030245-8bd256da52` | 德国杯 | 14 | True | 24.971793 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030245-ef13f3a255` | 英冠 | 5 | True | 25.048691 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030300-2bcbbcfaa9` | 英冠 | 6 | True | 194.053368 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030630-b950ece651` | 巴西甲 | 6 | True | 168.257942 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609030830-5c33bdb759` | 巴西杯 | 8 | True | 138.041653 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609032355-27472289f8` | 沙特联 | 8 | True | 282.050512 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609040030-fc4507fed4` | 沙特联 | 9 | True | 282.173977 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609040100-806c3ec8ac` | 瑞典超 | 8 | True | 282.314385 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609040200-afc3854289` | 沙特联 | 10 | True | 236.83451 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609040245-3a6fa70946` | 法甲 | 8 | True | 236.76015 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609040300-2e859b25ca` | 西甲 | 11 | True | 236.678389 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609040700-e958497ccb` | 巴西杯 | 9 | True | 187.033391 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050030-19f21c5d29` | 德乙 | 16 | True | 200.857938 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050100-0710b887b9` | 法甲 | 17 | True | 200.860959 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050100-f660ff23c3` | 挪超 | 12 | True | 200.879323 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050200-1fd675e659` | 法乙 | 13 | True | 200.876869 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050200-6903481e21` | 荷甲 | 13 | True | 200.867665 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050200-e121728916` | 荷乙 | 14 | True | 200.859281 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050200-f9fd33d3b7` | 沙特联 | 13 | True | 200.881981 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050230-8c4bcd78f7` | 德甲 | 17 | True | 200.906007 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050245-c82b563304` | 意甲 | 12 | True | 200.910763 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050300-025bdb255c` | 西甲 | 12 | True | 200.816462 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050300-51223cb0d7` | 英超 | 13 | True | 200.853211 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050305-bba137c7cd` | 法甲 | 13 | True | 11.674774 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609050315-739f9e0e2a` | 葡超 | 14 | True | 441.686214 | CHANGED | CHANGED | NOT_DIFFABLE | CHANGED | CHANGED | — |
| `FBOS-202609050730-5c15c07c04` | 美职业 | 16 | True | 110.901069 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609051800-2b08fe48af` | 韩K联 | 7 | True | 110.779263 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609051800-9816e14d4f` | 日职乙 | 10 | True | 125.359764 | UNCHANGED | UNCHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609051800-cde2ab334b` | 日职联 | 11 | True | 125.317954 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609051930-0fcf9ec39b` | 英超 | 7 | True | 125.457682 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052100-6e0924dd40` | 意甲 | 13 | True | 125.489593 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052130-2630695606` | 德甲 | 11 | True | 110.687883 | CHANGED | CHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609052130-28c59f0f8b` | 德甲 | 11 | True | 110.702205 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052130-478f9acd46` | 德甲 | 11 | True | 110.743766 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052130-897756eb97` | 德甲 | 9 | True | 125.555175 | CHANGED | CHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609052130-ee3f69da74` | 德甲 | 11 | True | 125.593093 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052200-07d3ad7d39` | 英超 | 9 | True | 125.712057 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052200-52b572bd6d` | 英超 | 9 | True | 125.662384 | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052200-7077268ca4` | 英超 | 8 | True | 110.6862 | CHANGED | CHANGED | NOT_DIFFABLE | CHANGED | CHANGED | — |
| `FBOS-202609052200-9297e1e363` | 英超 | 10 | True | 125.753649 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052215-1cb8bb1d9b` | 西甲 | 13 | True | 110.612159 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609052315-50c132a32f` | 法甲 | 9 | True | 110.59917 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609060000-8e837be7b0` | 意甲 | 11 | True | 125.757186 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609060030-59f3829691` | 英超 | 11 | True | 125.791674 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609060030-dc8113cfc8` | 西甲 | 11 | True | 125.816995 | UNCHANGED | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609060030-ecdcc63e73` | 德甲 | 12 | True | 110.523178 | CHANGED | CHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609060100-51c9d7b707` | 葡超 | 8 | True | 110.502793 | CHANGED | CHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609060200-04efbbf9ce` | 荷甲 | 11 | True | 125.850045 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609060245-42f0fad4d9` | 意甲 | 9 | True | 125.886886 | CHANGED | CHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609060245-734aed323b` | 法甲 | 6 | True | 110.477452 | UNCHANGED | UNCHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609060300-2e3ea64dbe` | 西甲 | 7 | True | 125.907932 | CHANGED | CHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609061700-07913b2e02` | 日职联 | 2 | True | 137.815703 | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609061700-9026c6b118` | 日职联 | 3 | True | 236.310506 | UNCHANGED | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609061800-31877c5e61` | 韩K联 | 3 | True | 110.273564 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609061800-7ee6392892` | 韩K联 | 3 | True | 110.281337 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609061830-abfae80ea0` | 日职联 | 3 | True | 110.262116 | UNCHANGED | UNCHANGED | CHANGED | CHANGED | CHANGED | — |
| `FBOS-202609062030-1c4927f18d` | 荷甲 | 4 | True | 126.227669 | CHANGED | CHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609062100-0611aa6106` | 英超 | 4 | True | 126.27015 | CHANGED | CHANGED | UNCHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609062100-13eb8f0ce8` | 意甲 | 4 | True | 126.320845 | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609062100-592239314f` | 意甲 | 4 | True | 126.368015 | UNCHANGED | UNCHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609062100-faf7539331` | 法甲 | 2 | True | 137.774546 | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609062130-e8ae29d9a5` | 德甲 | 3 | True | 110.142582 | UNCHANGED | UNCHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609062215-6077b95545` | 西甲 | 4 | True | 126.492803 | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609062230-24c59c6a96` | 葡超 | 3 | True | 110.109278 | CHANGED | CHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609062330-5be468dd05` | 英超 | 4 | True | 126.580026 | CHANGED | CHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609062330-bb7e9693da` | 德甲 | 3 | True | 126.637848 | UNCHANGED | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609070000-ac45356eaf` | 意甲 | 3 | True | 110.065221 | CHANGED | CHANGED | UNCHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609070030-29dee741e7` | 西甲 | 3 | True | 236.736379 | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | CHANGED | — |
| `FBOS-202609070030-74c7656092` | 西甲 | 2 | True | 137.935215 | CHANGED | CHANGED | UNCHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609070245-d0330d3f0d` | 意甲 | 2 | True | 137.968281 | UNCHANGED | UNCHANGED | CHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609070245-df9edaf3bc` | 法甲 | 3 | True | 109.991931 | UNCHANGED | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | — |
| `FBOS-202609070300-7d549fdcbc` | 西甲 | 2 | True | 138.014953 | UNCHANGED | UNCHANGED | UNCHANGED | UNCHANGED | CHANGED | — |

## E. Product-contract recommendation

Recommendations are deterministic consequences of measured unique-match coverage and the fixed labels; they do not change thresholds or model behavior.

| Field | Coverage label | Recommendation |
|---|---|---|
| Match identity (`match_identity`) | UNIVERSAL | STANDARD_REQUIRED |
| Competition (`competition`) | UNIVERSAL | STANDARD_REQUIRED |
| Kickoff (`kickoff`) | UNIVERSAL | STANDARD_REQUIRED |
| Serving/degraded/unavailable state (`serving_state`) | UNIVERSAL | STANDARD_REQUIRED |
| Frozen 1X2 probability vector (`frozen_1x2`) | UNIVERSAL | STANDARD_REQUIRED |
| Exact Score Top1 with displayed probability (`exact_score_top1`) | UNIVERSAL | STANDARD_REQUIRED |
| Exact Score Top3 with displayed probabilities (`exact_score_top3`) | UNIVERSAL | STANDARD_REQUIRED |
| Exact Score Top5 with displayed probabilities (`exact_score_top5`) | UNIVERSAL | STANDARD_REQUIRED |
| Full score-distribution availability flag (`full_score_distribution`) | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT |
| Total-goals state/distribution (`total_goals`) | UNIVERSAL | STANDARD_REQUIRED |
| BTTS state/probability (`btts`) | UNIVERSAL | STANDARD_REQUIRED |
| Source cutoff (`source_cutoff`) | UNIVERSAL | STANDARD_REQUIRED |
| Frozen timestamp (`freeze_timestamp`) | UNIVERSAL | STANDARD_REQUIRED |
| Frozen recent-form aggregate (`recent_form_aggregate`) | UNIVERSAL | STANDARD_REQUIRED |
| Home/away recent-form context (`home_away_recent_form`) | UNIVERSAL | STANDARD_REQUIRED |
| Lineup publication (`lineup_publication`) | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT |
| Injuries/availability (`injuries_availability`) | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT |
| Weather (`weather`) | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT |
| Venue/H2H (`venue_h2h`) | SPARSE | NOT_READY_FOR_PRODUCT_CONTRACT |
| Timestamped frozen 1X2 quotes (`market_1x2_quotes`) | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK |
| AH line plus both-side water (`market_ah_line_water`) | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK |
| O/U line plus both-side water (`market_ou_line_water`) | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK |
| Market snapshot timestamp (`market_snapshot_timestamp`) | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK |
| Market snapshot source-age inputs (`market_source_age_inputs`) | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK |
| Market/input quality/data-grade (`market_input_quality`) | UNIVERSAL | STANDARD_WITH_DEGRADED_FALLBACK |
| Verified-result linkage (`verified_result_linkage`) | PARTIAL | STANDARD_WITH_DEGRADED_FALLBACK |
| Forecast lead time (`forecast_lead_time`) | UNIVERSAL | STANDARD_REQUIRED |

## Integrity and delivery boundary

```json
{
  "accepted_formal_unique_match_count": 317,
  "base_reader_errors": [],
  "chronology_failures": [],
  "formal_record_identity_mismatch_count": 0,
  "frozen_store_reader_rejections_are_excluded": true,
  "integrity_failures": [],
  "ledger_reader_errors": [],
  "model_frozen_history_serving_mutated": false,
  "postmatch_fields_used_for_prematch_selection": false,
  "reader_rejected_formal_flags": [
    {
      "match_key": "FBOS-202608130600-7a41f60733",
      "prediction_id": "FBOS-PRED-1d3ca4c14c557e80c3fdde4e",
      "reason": "EXISTING_FORMAL_ELIGIBILITY_READER_REJECTED"
    },
    {
      "match_key": "FBOS-202608140600-6d0ca13224",
      "prediction_id": "FBOS-PRED-9ca56a09f35a3b3cfc144495",
      "reason": "EXISTING_FORMAL_ELIGIBILITY_READER_REJECTED"
    },
    {
      "match_key": "FBOS-202608130300-1cd74be608",
      "prediction_id": "FBOS-PRED-9e1a66cba32b117bcc677907",
      "reason": "EXISTING_FORMAL_ELIGIBILITY_READER_REJECTED"
    },
    {
      "match_key": "FBOS-202608130600-d08d687191",
      "prediction_id": "FBOS-PRED-b25713ec653527d99ce6b05e",
      "reason": "EXISTING_FORMAL_ELIGIBILITY_READER_REJECTED"
    },
    {
      "match_key": "FBOS-202608140830-0c039788c1",
      "prediction_id": "FBOS-PRED-d209d8f123a7a15a70dcb067",
      "reason": "EXISTING_FORMAL_ELIGIBILITY_READER_REJECTED"
    }
  ],
  "reader_rejected_frozen_records": 0,
  "result_reader_errors": [],
  "universe_reader_errors": []
}
```

No model, Champion/Challenger, calibration, serving, frozen record, or frozen-history file is modified by this research-only audit. The output is ready for independent acceptance; **DO NOT MERGE** until that acceptance is complete.

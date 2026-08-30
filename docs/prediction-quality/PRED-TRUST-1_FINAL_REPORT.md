# PRED-TRUST-1 — Unique-Match Prediction Integrity & Multi-Market Quality Audit

Status: `READY_FOR_ACCEPTANCE` (audit evidence only; no model or production mutation)

## 0. Scope and immutable evidence boundary

- Audited data commit: `73994d32fc148da49295a5bfef2e1e42e042a22e`
- Accepted production run: `33294381128`
- Accepted write-back commit: `73994d32fc148da49295a5bfef2e1e42e042a22e`
- Latest synced main commit: `724ac875df1899dad8d155688e0b11ccd744b2de`
- Current-day cohort: `2026-08-30`, pinned to the accepted write-back; no later refresh is substituted.
- Post-acceptance refresh handling: The later synced main contains an automatic generated-data refresh; the accepted 22 frozen / 3 insufficient production cohort remains the audit source so today's prospective evidence is not silently replaced.
- The audit reads immutable prediction/result/ledger artifacts and writes only the audit JSON and this report.
- Today’s frozen predictions, historical frozen files, prospective ledger, Champion, providers, aliases, and health gate are unchanged.

## 1. Unique-match evaluation cohort

Selection order: `match_id → all legal pre-kickoff frozen versions → final selected legal prematch prediction → one prediction per unique match`.
Pilot, excluded, post-kickoff, illegal timestamp, superseded, and non-selected duplicate versions are excluded from metrics without deleting their files.

- Loaded prediction rows: `562`
- Historical legal rows: `491`
- Historical unique matches: `217`
- Historical superseded versions excluded from evaluation: `274`
- Prospective ledger rows / unique prediction IDs: `436` / `436`

## 2. DUPLICATE_FROZEN_PREDICTION classification

- Health duplicate groups: `51`
- Unique affected matches: `51`
- Classification counts: `{'A': 51, 'B': 0, 'C': 0, 'D': 0}`
- Real immutable/frozen integrity violation: `False`
- Prediction integrity status: `CLEAR`
- Health-rule false-positive groups under canonical selection: `51`

| class | meaning | count |
|---|---|---:|
| A | legitimate immutable prematch version history with one final selected version | 51 |
| B | actual duplicate final: two legal final candidates with tied chronology | 0 |
| C | identity collision: one health group contains different match identity | 0 |
| D | health false positive: duplicate group has no second legal prematch candidate | 0 |

Bounded recommendation: Bounded repair recommendation only: teach the health monitor the canonical unique-match selector and alert on unresolved B/C groups; do not patch the monitor or rewrite history in PRED-TRUST-1.

## 3. Exact-score Top1 distribution

### A. Current `2026-08-30` cohort (`22` matches)

| score | count | share |
|---|---:|---:|
| 1-1 | 16 | 72.73% |
| 0-0 | 0 | 0.00% |
| 2-1 | 3 | 13.64% |
| 1-2 | 1 | 4.55% |
| 2-2 | 0 | 0.00% |
| high-score (>=4 total) | 0 | 0.00% |
| home-margin | 4 | 18.18% |
| away-margin | 2 | 9.09% |

1X2 leader counts: `{'AWAY': 6, 'HOME': 16}`.

### B. All legal historical/prospective unique-match cohort (`217` matches)

| score | count | share |
|---|---:|---:|
| 1-1 | 166 | 76.50% |
| 0-0 | 0 | 0.00% |
| 2-1 | 20 | 9.22% |
| 1-2 | 7 | 3.23% |
| 2-2 | 0 | 0.00% |
| high-score (>=4 total) | 0 | 0.00% |
| home-margin | 38 | 17.51% |
| away-margin | 13 | 5.99% |

1X2 leader counts: `{'AWAY': 74, 'HOME': 143}`.

Historical Top1 distribution: `{'1-1': 166, '2-1': 20, '1-0': 18, '1-2': 7, '0-1': 6}`

## 4. Lambda distribution

### Current cohort
- sample_count: `22`
- lambda_home P10/P25/P50/P75/P90: `{'P10': 1.190536, 'P25': 1.319048, 'P50': 1.467731, 'P75': 1.777114, 'P90': 2.142368}`
- lambda_away P10/P25/P50/P75/P90: `{'P10': 1.069658, 'P25': 1.22463, 'P50': 1.313704, 'P75': 1.551092, 'P90': 1.798879}`
- lambda_total P10/P25/P50/P75/P90: `{'P10': 2.397, 'P25': 2.6225, 'P50': 2.995, 'P75': 3.2375, 'P90': 3.499}`
- abs(lambda_home-lambda_away) P10/P25/P50/P75/P90: `{'P10': 0.100413, 'P25': 0.215579, 'P50': 0.415594, 'P75': 0.649787, 'P90': 0.924737}`
- gap < 0.25: `{'count': 7, 'share': 0.318182}`; gap < 0.5: `{'count': 14, 'share': 0.636364}`
- total < 2: `{'count': 0, 'share': 0.0}`; total 2–3: `{'count': 12, 'share': 0.545455}`; total > 3: `{'count': 10, 'share': 0.454545}`
- HOME leader stratum: `{'sample_count': 16, 'lambda_home': {'P10': 1.29735, 'P25': 1.422898, 'P50': 1.609171, 'P75': 1.878801, 'P90': 2.216197}, 'lambda_away': {'P10': 1.062759, 'P25': 1.08407, 'P50': 1.234143, 'P75': 1.349913, 'P90': 1.365321}, 'lambda_total': {'P10': 2.37, 'P25': 2.58, 'P50': 2.93, 'P75': 3.1725, 'P90': 3.445}, 'absolute_gap': {'P10': 0.095148, 'P25': 0.114713, 'P50': 0.390355, 'P75': 0.652602, 'P90': 0.987394}, 'gap_lt_0_25': {'count': 7, 'share': 0.4375}, 'gap_lt_0_5': {'count': 11, 'share': 0.6875}, 'total_lt_2': {'count': 0, 'share': 0.0}, 'total_2_to_3': {'count': 9, 'share': 0.5625}, 'total_gt_3': {'count': 7, 'share': 0.4375}}`
- DRAW leader stratum: `{'sample_count': 0, 'lambda_home': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'lambda_away': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'lambda_total': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'absolute_gap': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'gap_lt_0_25': {'count': 0, 'share': None}, 'gap_lt_0_5': {'count': 0, 'share': None}, 'total_lt_2': {'count': 0, 'share': None}, 'total_2_to_3': {'count': 0, 'share': None}, 'total_gt_3': {'count': 0, 'share': None}}`
- AWAY leader stratum: `{'sample_count': 6, 'lambda_home': {'P10': 1.042409, 'P25': 1.199566, 'P50': 1.307646, 'P75': 1.391349, 'P90': 1.456608}, 'lambda_away': {'P10': 1.542488, 'P25': 1.604629, 'P50': 1.772457, 'P75': 1.947666, 'P90': 2.048393}, 'lambda_total': {'P10': 2.615, 'P25': 2.825, 'P50': 3.05, 'P75': 3.4025, 'P90': 3.505}, 'absolute_gap': {'P10': 0.324707, 'P25': 0.396672, 'P50': 0.550545, 'P75': 0.649787, 'P90': 0.681421}, 'gap_lt_0_25': {'count': 0, 'share': 0.0}, 'gap_lt_0_5': {'count': 3, 'share': 0.5}, 'total_lt_2': {'count': 0, 'share': 0.0}, 'total_2_to_3': {'count': 3, 'share': 0.5}, 'total_gt_3': {'count': 3, 'share': 0.5}}`

### Historical unique-match cohort
- sample_count: `217`
- lambda_home P10/P25/P50/P75/P90: `{'P10': 1.102188, 'P25': 1.255355, 'P50': 1.476375, 'P75': 1.705873, 'P90': 1.978457}`
- lambda_away P10/P25/P50/P75/P90: `{'P10': 1.034835, 'P25': 1.128118, 'P50': 1.269333, 'P75': 1.455829, 'P90': 1.726225}`
- lambda_total P10/P25/P50/P75/P90: `{'P10': 2.36, 'P25': 2.53, 'P50': 2.77, 'P75': 3.13, 'P90': 3.418}`
- abs(lambda_home-lambda_away) P10/P25/P50/P75/P90: `{'P10': 0.065331, 'P25': 0.141304, 'P50': 0.35688, 'P75': 0.599364, 'P90': 0.859536}`
- gap < 0.25: `{'count': 76, 'share': 0.35023}`; gap < 0.5: `{'count': 144, 'share': 0.663594}`
- total < 2: `{'count': 3, 'share': 0.013825}`; total 2–3: `{'count': 146, 'share': 0.672811}`; total > 3: `{'count': 68, 'share': 0.313364}`
- HOME leader stratum: `{'sample_count': 143, 'lambda_home': {'P10': 1.291099, 'P25': 1.418257, 'P50': 1.597369, 'P75': 1.80737, 'P90': 2.121828}, 'lambda_away': {'P10': 0.97701, 'P25': 1.071255, 'P50': 1.173198, 'P75': 1.296261, 'P90': 1.395813}, 'lambda_total': {'P10': 2.352, 'P25': 2.56, 'P50': 2.8, 'P75': 3.09, 'P90': 3.396}, 'absolute_gap': {'P10': 0.076342, 'P25': 0.178044, 'P50': 0.407432, 'P75': 0.694484, 'P90': 0.919306}, 'gap_lt_0_25': {'count': 47, 'share': 0.328671}, 'gap_lt_0_5': {'count': 86, 'share': 0.601399}, 'total_lt_2': {'count': 3, 'share': 0.020979}, 'total_2_to_3': {'count': 95, 'share': 0.664336}, 'total_gt_3': {'count': 45, 'share': 0.314685}}`
- DRAW leader stratum: `{'sample_count': 0, 'lambda_home': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'lambda_away': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'lambda_total': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'absolute_gap': {'P10': None, 'P25': None, 'P50': None, 'P75': None, 'P90': None}, 'gap_lt_0_25': {'count': 0, 'share': None}, 'gap_lt_0_5': {'count': 0, 'share': None}, 'total_lt_2': {'count': 0, 'share': None}, 'total_2_to_3': {'count': 0, 'share': None}, 'total_gt_3': {'count': 0, 'share': None}}`
- AWAY leader stratum: `{'sample_count': 74, 'lambda_home': {'P10': 1.020487, 'P25': 1.103188, 'P50': 1.205165, 'P75': 1.38332, 'P90': 1.565917}, 'lambda_away': {'P10': 1.285979, 'P25': 1.382358, 'P50': 1.519962, 'P75': 1.739406, 'P90': 1.987348}, 'lambda_total': {'P10': 2.383, 'P25': 2.4925, 'P50': 2.71, 'P75': 3.175, 'P90': 3.481}, 'absolute_gap': {'P10': 0.05098, 'P25': 0.117259, 'P50': 0.289997, 'P75': 0.475188, 'P90': 0.677291}, 'gap_lt_0_25': {'count': 29, 'share': 0.391892}, 'gap_lt_0_5': {'count': 58, 'share': 0.783784}, 'total_lt_2': {'count': 0, 'share': 0.0}, 'total_2_to_3': {'count': 51, 'share': 0.689189}, 'total_gt_3': {'count': 23, 'share': 0.310811}}`

## 5. Cross-market consistency

Leader probability buckets are `<40%`, `40–45%`, `45–50%`, `50–55%`, and `55%+`; strong HOME/AWAY means that side probability is at least 55%. These are descriptive consistency statistics, not error labels.

Current cross-market summary: `{'home_leader_plus_draw_score_top1': {'count': 12, 'share': 0.75, 'cohort_share': 0.545455}, 'draw_leader_plus_draw_score_top1': {'count': 0, 'share': None, 'cohort_share': 0.0}, 'away_leader_plus_draw_score_top1': {'count': 4, 'share': 0.666667, 'cohort_share': 0.181818}, 'strong_home_probability_plus_1_1': {'count': 1, 'share': 0.25, 'strong_home_sample_count': 4, 'cohort_share': 0.045455}, 'strong_away_probability_plus_1_1': {'count': 0, 'share': None, 'strong_away_sample_count': 0, 'cohort_share': 0.0}, 'leader_probability_buckets': {'<40%': {'sample_count': 4, 'leaders': {'HOME': 4}, 'top1_scores': {'1-1': 4}}, '40–45%': {'sample_count': 4, 'leaders': {'AWAY': 1, 'HOME': 3}, 'top1_scores': {'1-1': 4}}, '45–50%': {'sample_count': 6, 'leaders': {'AWAY': 2, 'HOME': 4}, 'top1_scores': {'1-1': 5, '1-0': 1}}, '50–55%': {'sample_count': 4, 'leaders': {'AWAY': 3, 'HOME': 1}, 'top1_scores': {'1-1': 2, '0-1': 1, '1-2': 1}}, '55%+': {'sample_count': 4, 'leaders': {'HOME': 4}, 'top1_scores': {'1-1': 1, '2-1': 3}}}, 'btts_yes_probability': {'sample_count': 22, 'quantiles': {'P10': 0.470186, 'P25': 0.521895, 'P50': 0.579026, 'P75': 0.624964, 'P90': 0.655159}}, 'totals_expected_goals': {'sample_count': 22, 'quantiles': {'P10': 2.397, 'P25': 2.6225, 'P50': 2.995, 'P75': 3.2375, 'P90': 3.499}}, 'totals_over_2_5_probability': {'sample_count': 22, 'quantiles': {'P10': 0.429498, 'P25': 0.487158, 'P50': 0.575688, 'P75': 0.627743, 'P90': 0.678968}}, 'profile_1_1_vs_other': {'score_1_1': {'sample_count': 16, 'btts_yes_median': 0.571651, 'lambda_total_median': 2.925, 'over_2_5_probability_median': 0.559645}, 'other_top1': {'sample_count': 6, 'btts_yes_median': 0.630131, 'lambda_total_median': 3.445, 'over_2_5_probability_median': 0.668779}}, 'tension_flags': {'lambda_total_ge_3_and_1_1': {'count': 7, 'share': 0.318182}, 'totals_over_2_5_ge_0_65_and_1_1': {'count': 1, 'share': 0.045455}, 'btts_yes_ge_0_65_and_1_1': {'count': 1, 'share': 0.045455}}}`

Historical cross-market summary: `{'home_leader_plus_draw_score_top1': {'count': 105, 'share': 0.734266, 'cohort_share': 0.483871}, 'draw_leader_plus_draw_score_top1': {'count': 0, 'share': None, 'cohort_share': 0.0}, 'away_leader_plus_draw_score_top1': {'count': 61, 'share': 0.824324, 'cohort_share': 0.281106}, 'strong_home_probability_plus_1_1': {'count': 9, 'share': 0.290323, 'strong_home_sample_count': 31, 'cohort_share': 0.041475}, 'strong_away_probability_plus_1_1': {'count': 0, 'share': 0.0, 'strong_away_sample_count': 5, 'cohort_share': 0.0}, 'leader_probability_buckets': {'<40%': {'sample_count': 46, 'leaders': {'AWAY': 18, 'HOME': 28}, 'top1_scores': {'1-1': 44, '1-0': 2}}, '40–45%': {'sample_count': 55, 'leaders': {'AWAY': 23, 'HOME': 32}, 'top1_scores': {'1-1': 49, '1-0': 4, '0-1': 2}}, '45–50%': {'sample_count': 50, 'leaders': {'AWAY': 20, 'HOME': 30}, 'top1_scores': {'1-1': 41, '1-0': 6, '0-1': 2, '1-2': 1}}, '50–55%': {'sample_count': 30, 'leaders': {'AWAY': 8, 'HOME': 22}, 'top1_scores': {'1-1': 23, '2-1': 4, '0-1': 1, '1-2': 2}}, '55%+': {'sample_count': 36, 'leaders': {'AWAY': 5, 'HOME': 31}, 'top1_scores': {'1-1': 9, '2-1': 16, '1-2': 4, '1-0': 6, '0-1': 1}}}, 'btts_yes_probability': {'sample_count': 217, 'quantiles': {'P10': 0.471498, 'P25': 0.508983, 'P50': 0.548868, 'P75': 0.607768, 'P90': 0.650187}}, 'totals_expected_goals': {'sample_count': 217, 'quantiles': {'P10': 2.36, 'P25': 2.53, 'P50': 2.77, 'P75': 3.13, 'P90': 3.418}}, 'totals_over_2_5_probability': {'sample_count': 217, 'quantiles': {'P10': 0.419807, 'P25': 0.463859, 'P50': 0.523365, 'P75': 0.605296, 'P90': 0.663716}}, 'profile_1_1_vs_other': {'score_1_1': {'sample_count': 166, 'btts_yes_median': 0.548343, 'lambda_total_median': 2.755, 'over_2_5_probability_median': 0.51975}, 'other_top1': {'sample_count': 51, 'btts_yes_median': 0.595533, 'lambda_total_median': 3.23, 'over_2_5_probability_median': 0.626322}}, 'tension_flags': {'lambda_total_ge_3_and_1_1': {'count': 44, 'share': 0.202765}, 'totals_over_2_5_ge_0_65_and_1_1': {'count': 10, 'share': 0.046083}, 'btts_yes_ge_0_65_and_1_1': {'count': 12, 'share': 0.0553}}}`

Historical market-fusion summary: `{'available_count': 217, 'market_model_leader_disagreement': {'count': 33, 'share': 0.152074}, 'market_leader_to_model_leader': {'AWAY->AWAY': 55, 'AWAY->HOME': 14, 'HOME->AWAY': 19, 'HOME->HOME': 129}, 'mean_model_minus_market_probability': {'home': -0.016644, 'draw': -0.00418, 'away': 0.020824}}`

Tension flags (lambda/BTTS/totals versus 1-1): `{'lambda_total_ge_3_and_1_1': {'count': 44, 'share': 0.202765}, 'totals_over_2_5_ge_0_65_and_1_1': {'count': 10, 'share': 0.046083}, 'btts_yes_ge_0_65_and_1_1': {'count': 12, 'share': 0.0553}}`

## 6. Verified prospective evaluation

Verified 90m result artifacts: `{'artifact_count': 382, 'verified_final_artifact_count': 382, 'invalid_or_unverified_artifact_count': 0, 'indexed_identity_count': 382}`
Formal unique-match sample: `181`; missing result: `0`; result conflicts: `0`.

| market | sample | accuracy / hit rate | Brier | LogLoss |
|---|---:|---:|---:|---:|
| 1X2 | 181 | 51.93% | 0.596239 | 0.997551 |
| Exact Score Top1 | 181 | 11.60% | — | — |
| Exact Score Top3 | 181 | 28.73% | — | — |
| BTTS | 181 | 60.22% | 0.233452 | — |
| O/U 2.5 | 181 | 62.43% | 0.224801 | — |

Mean probability assigned to the actual exact score: `0.083332` over `117` rows where the actual score was present in the stored distribution.
Actual-score empirical baseline: `{'1-1': 19, '3-0': 16, '0-1': 13, '2-0': 13, '2-2': 13, '2-1': 12, '1-2': 11, '1-0': 10, '3-1': 9, '0-2': 8, '3-2': 8, '1-3': 6, '1-4': 5, '2-3': 5, '4-1': 5, '0-3': 4, '0-4': 4, '3-3': 3, '4-0': 3, '5-1': 3}`.

## 7. Health-gate audit

Legacy threshold: `0.875` dominant-share; observed health population: `{'schema_version': '1.0', 'sample_count': 491, 'eligible_record_count': 491, 'missing_top1_count': 0, 'dominant_score': '1-1', 'dominant_count': 373, 'dominant_share': 0.759674, 'compressed_count': 316, 'compressed_share': 0.643585, 'lambda_gap_sample_count': 491, 'missing_lambda_gap_count': 0, 'runner_up_count': 55, 'runner_up_share': 0.112016, 'dominant_share_gap': 0.647658, 'gap_threshold': 0.5, 'compression_rule': 'abs(lambda_home-lambda_away) < gap_threshold', 'dominant_share_threshold': 0.875, 'compressed_count_threshold': 7, 'compressed_share_threshold': 0.75, 'status': 'HEALTHY', 'reasons': []}`.
Threshold origin: `LEGACY_FIXED_GUARDRAIL` — `sample>=8 and dominant_count>=7 and dominant_share>=0.875`; the repository records the rule in `scripts/production_health_watch.py:41 / commit 50772724e3` but no empirical football-product calibration rationale is recorded.
Runtime health remains `ALERT` with `['DUPLICATE_FROZEN_PREDICTION']` and `53` consecutive problem cycles.
Uniform exact-score baseline: `{'definition': 'uniform random top1 over 36 cells (0-0 through 5-5)', 'grid_size': 36, 'dominant_share': 0.027778}`.
Uniform 1X2 baseline: `{'definition': 'uniform random top1 over HOME/DRAW/AWAY', 'grid_size': 3, 'dominant_share': 0.333333}`.
Historical actual-score baseline: `{'sample_count': 181, 'most_frequent_actual_score': '1-1', 'count': 19, 'share': 0.104972}`.

| Champion time window | n | dominant Top1 | share | 1-1 count | gap<0.5 |
|---|---:|---|---:|---:|---:|
| 2026-08-13..2026-08-20 | 74 | 1-1 | 82.43% | 61 | 74.32% |
| 2026-08-21..2026-08-27 | 79 | 1-1 | 77.22% | 61 | 68.35% |
| 2026-08-28..2026-09-01 | 64 | 1-1 | 68.75% | 44 | 54.69% |

Top competition strata by selected-match count:

| competition | n | 1-1 share | gap<0.5 | total<2 | total 2–3 | total>3 |
|---|---:|---:|---:|---:|---:|---:|
| 西班牙甲级联赛 | 25 | 84.00% | 76.00% | 0.00% | 76.00% | 24.00% |
| 荷兰甲级联赛 | 17 | 64.71% | 41.18% | 0.00% | 11.76% | 88.24% |
| 欧罗巴联赛 | 16 | 81.25% | 56.25% | 0.00% | 50.00% | 50.00% |
| 英格兰超级联赛 | 16 | 100.00% | 75.00% | 0.00% | 75.00% | 25.00% |
| 意大利甲级联赛 | 14 | 64.29% | 57.14% | 0.00% | 85.71% | 14.29% |
| 韩国职业联赛 | 13 | 84.62% | 92.31% | 0.00% | 100.00% | 0.00% |
| 瑞典超级联赛 | 11 | 72.73% | 45.45% | 0.00% | 72.73% | 27.27% |
| 日本职业联赛 | 10 | 80.00% | 60.00% | 0.00% | 100.00% | 0.00% |
| 欧洲冠军联赛 | 10 | 90.00% | 70.00% | 0.00% | 40.00% | 60.00% |
| 葡萄牙超级联赛 | 10 | 40.00% | 80.00% | 0.00% | 100.00% | 0.00% |

Assessment: `NO` — 76% of matches sharing one exact-score Top1 should not be treated as healthy from a football-product perspective, even though the legacy 87.5% gate does not fire. Recommendation: `REPLACE_WITH_MULTI_SIGNAL`; gate action this milestone: `KEEP_GATE_UNCHANGED`.

## 8. Root-cause ranking (no parameter change)

- **P0 — C. LAMBDA_GENERATION**: `PRIMARY_EVIDENCE`; evidence `{'historical_gap_lt_0_5': {'count': 144, 'share': 0.663594}, 'current_gap_lt_0_5': {'count': 14, 'share': 0.636364}, 'historical_lambda_total_median': 2.77, 'current_lambda_total_median': 2.995}`
- **P1 — E. PRODUCT_PRESENTATION**: `PRIMARY_PRODUCT_RISK`; evidence `{'historical_top1_score_support_size': 5, 'historical_1_1_share': 0.764977, 'current_1_1_share': 0.727273, 'exact_score_top1_hit_rate_is_prospective': 'see prospective block'}`
- **P2 — B. MARKET_FUSION**: `SECONDARY_SIGNAL`; evidence `{'market_model_leader_disagreement': {'count': 33, 'share': 0.152074}, 'market_mean_model_minus_market_probability': {'home': -0.016644, 'draw': -0.00418, 'away': 0.020824}}`

- A. INPUT / FOOTBALL EVIDENCE: `{'recent_form_status': {'READY': 217}, 'market_intelligence_quality': {'FULL': 214, 'LIMITED': 3}, 'assessment': 'NOT_ESTABLISHED_BY_THIS_AUDIT', 'reason': 'The selected records expose readiness/quality labels, but not enough feature-depth evidence to claim shallow recent form as the cause.'}`
- D. SCORE_SELECTOR: `{'assessment': 'NOT_SUPPORTED_BY_THIS_AUDIT', 'independent_poisson_map_matches_top1': 217, 'comparable_sample_count': 217, 'reason': 'The stored Top1 equals the independent Poisson joint MAP for the comparable selected cohort; selector-only failure is not demonstrated.'}`

Product conclusion: `MIXED`.

## 9. One next milestone

`PRED-TRUST-2 — Strength/Lambda Challenger Experiment Design & Bounded Prospective Shadow Plan` — design only; prospective shadow/promotion gates remain mandatory. No automatic implementation starts from this audit.

## 10. STOP state

No PRED-AVAIL-3, ID-AUTO-2, new provider, manual alias, league-specific coverage, Publisher validation, B2 work, model tuning, Champion modification, frozen rewrite, lambda patch, score-selector patch, draw penalty, quota, or randomization was performed.

Full machine-readable evidence is stored beside this report in `data/prediction_quality/pred_trust_1/`.

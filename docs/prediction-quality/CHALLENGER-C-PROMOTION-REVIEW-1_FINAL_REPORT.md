# CHALLENGER-C-PROMOTION-REVIEW-1

Decision: **`KEEP CHAMPION / KEEP C SHADOW`**
Safety Gate: **`FAIL`**

## Stop state

The final review stops before Champion promotion, merge, and production verification.
No new Challenger was created and no frozen/prospective history was rewritten.

## Source and cohort

- Latest shadow artifact: `data/prediction_quality/market_side_shadow_1/latest.json`
- Existing result artifacts only; no new matches fetched: `data/postmatch_automation/results`
- Pair rows: `124`; promotion-eligible rows: `123`
- Verified promotion-eligible rows: `112`
- Verified unique matches: `29`
- Duplicate verified-match groups: `26`; duplicate rows beyond one per match: `83`

The accepted `112` value is therefore a pair-row count, not 112 independent matches. The repository promotion gate requires unique-match evaluation, and the current cohort has `29` unique matches against a minimum of `50`.

## Accepted 112-row reproduction

| Scope | Candidate | n | Exact Top1 | Exact Top3 | Exact NLL | 1X2 Acc | 1X2 Brier | 1X2 LogLoss | BTTS Acc | BTTS Brier | BTTS LogLoss | BTTS ECE | O/U Acc | O/U Brier | O/U LogLoss | 1-1 Top1 | Median Lambda Gap | Lambda Gap < 0.5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 112 pair rows | champion | 112 | 0.107143 | 0.285714 | 3.028905 | 0.821429 | 0.435565 | 0.771895 | 0.428571 | 0.276516 | 0.748053 | 0.156400 | 0.660714 | 0.226805 | 0.645221 | 0.660714 | 0.486788 | 0.526786 |
| 112 pair rows | challenger | 112 | 0.125000 | 0.303571 | 2.974157 | 0.803571 | 0.378420 | 0.687060 | 0.455357 | 0.281726 | 0.759252 | 0.163670 | 0.660714 | 0.226805 | 0.645221 | 0.383929 | 0.773430 | 0.285714 |

Reproduction check: **`PASS`**; mismatches: `0`.

## Bounded robustness slices

Slices below use one deterministic latest pre-match row per unique match. Only groups with at least `10` unique matches are shown; smaller league/regime groups are count-only and are not decision signals.

| Slice | Candidate | n | Exact Top1 | Exact Top3 | Exact NLL | 1X2 Acc | 1X2 Brier | 1X2 LogLoss | BTTS Acc | BTTS Brier | BTTS LogLoss | BTTS ECE | O/U Acc | O/U Brier | O/U LogLoss | 1-1 Top1 | Median Lambda Gap | Lambda Gap < 0.5 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| chronological_earlier | champion | 14 | 0.071429 | 0.142857 | 3.243904 | 0.642857 | 0.553241 | 0.938453 | 0.642857 | 0.243458 | 0.681078 | 0.130440 | 0.714286 | 0.190076 | 0.568246 | 0.642857 | 0.334287 | 0.571429 |
| chronological_earlier | challenger | 14 | 0.071429 | 0.214286 | 3.175485 | 0.642857 | 0.543735 | 0.922298 | 0.642857 | 0.249768 | 0.693447 | 0.292233 | 0.714286 | 0.190076 | 0.568247 | 0.428571 | 0.961060 | 0.428571 |
| chronological_later | champion | 15 | 0.133333 | 0.333333 | 2.903938 | 0.866667 | 0.396273 | 0.717769 | 0.333333 | 0.290159 | 0.775614 | 0.297740 | 0.666667 | 0.226193 | 0.643629 | 0.666667 | 0.531618 | 0.466667 |
| chronological_later | challenger | 15 | 0.133333 | 0.333333 | 2.865175 | 0.866667 | 0.343293 | 0.640523 | 0.400000 | 0.290473 | 0.776967 | 0.290897 | 0.666667 | 0.226193 | 0.643629 | 0.400000 | 0.878820 | 0.266667 |
| market_side::home_leaning | champion | 18 | 0.055556 | 0.166667 | 3.097973 | 0.722222 | 0.450993 | 0.792908 | 0.500000 | 0.267085 | 0.729152 | 0.131993 | 0.722222 | 0.195910 | 0.580437 | 0.611111 | 0.518819 | 0.500000 |
| market_side::home_leaning | challenger | 18 | 0.055556 | 0.222222 | 3.091629 | 0.722222 | 0.447249 | 0.777540 | 0.500000 | 0.281699 | 0.759266 | 0.155636 | 0.722222 | 0.195910 | 0.580437 | 0.388889 | 0.703020 | 0.333333 |
| favorite_strength::strong | champion | 10 | 0.100000 | 0.200000 | 3.352109 | 0.900000 | 0.363319 | 0.675362 | 0.500000 | 0.262150 | 0.718124 | 0.198223 | 0.900000 | 0.156660 | 0.498537 | 0.500000 | 0.717877 | 0.200000 |
| favorite_strength::strong | challenger | 10 | 0.100000 | 0.200000 | 3.158207 | 0.900000 | 0.254351 | 0.531848 | 0.700000 | 0.251707 | 0.698683 | 0.201195 | 0.900000 | 0.156660 | 0.498537 | 0.000000 | 1.385949 | 0.000000 |

Slice counts not reported as decision signals:
`{"excluded_league_groups_below_minimum": ["巴西甲级联赛", "德国乙级联赛", "德国甲级联赛", "意大利甲级联赛", "挪威超级联赛", "法国乙级联赛", "法国甲级联赛", "瑞典超级联赛", "美国职业大联盟", "英格兰超级联赛", "荷兰甲级联赛", "葡萄牙超级联赛", "西班牙甲级联赛"], "favorite_strength": {"balanced": 6, "moderate": 9, "strong": 10}, "league": {"巴西甲级联赛": 1, "德国乙级联赛": 1, "德国甲级联赛": 1, "意大利甲级联赛": 5, "挪威超级联赛": 1, "法国乙级联赛": 1, "法国甲级联赛": 2, "瑞典超级联赛": 3, "美国职业大联盟": 1, "英格兰超级联赛": 4, "荷兰甲级联赛": 3, "葡萄牙超级联赛": 2, "西班牙甲级联赛": 4}, "market_side": {"away_leaning": 7, "balanced": 4, "home_leaning": 18}, "minimum_meaningful_slice": 10}`

## Gate evidence

| Gate | Result |
|---|---|
| pair_freeze_integrity | `PASS` |
| accepted_overall_112_reproduce | `PASS` |
| unique_match_promotion_gate | `FAIL` |
| meaningful_subgroup_safety | `PASS` |
| exact_score_improvement_not_confined | `PASS` |
| one_one_reduction_broad | `PASS` |
| btts_regression_bounded | `PASS` |
| no_post_match_information_in_generation | `PASS` |

Safety floors used:
`{"btts_brier": 0.08, "one_x_two_brier": 0.1, "one_x_two_log_loss": 0.2, "ou_2_5_brier": 0.08}`

Overall safety-floor triggers: `[]`.
Subgroup safety: **`PASS`**; checked slices: `4`; triggers: `0`.

## Integrity and production boundary

- Pair/freeze integrity: **`PASS`**
- Post-match generation flag: `123/123` false
- Result identity mismatches: `0`
- No promotion implementation, merge, production run, or production mutation was attempted after the failed gate.
- Current Champion remains `recent_form_market_calibrated_poisson_v2`; C remains shadow-only.

## Exact stop decision

`KEEP CHAMPION / KEEP C SHADOW`

Required next action is to repair/replace the prospective cohort capture so that the formal review has the required unique-match population. Do not refit C and do not create another Challenger in this stopped milestone.

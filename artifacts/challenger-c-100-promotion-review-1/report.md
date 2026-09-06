# CHALLENGER-C-100-PROMOTION-REVIEW-1

Decision: **`C_PROMOTION_REVIEW_INCONCLUSIVE`**
Integrity: **`PASS`**

## Scope and stop state

- Formal observation unit: `unique football match`.
- Formal route-reference sample: `109` unique matches.
- Natural growth after the 109-match route snapshot: `2`; included in decision: `False`.
- Read-only statistics only. Champion, C, Market parameters, selector, serving, UI, and frozen history were not changed.
- Automatic promotion, replay, backfill, provider/network access, and new data-source access were not attempted.

## Authority and immutable Exact proof

- Memory-Hub authority: [PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-PUBLIC-LAUNCH-TRUST-MARKET-READINESS-RESULT-R1.md](https://github.com/gemini077/Memory-Hub/blob/main/PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-PUBLIC-LAUNCH-TRUST-MARKET-READINESS-RESULT-R1.md) (blob SHA `860ba05aa8dbd94b5311f3ec0653ee1d11422cf7`).
- Persisted pair-file/digest audit: `PASS`; checked `1313` promotion-eligible version rows.
- C/Champion representation: `persisted candidate-time explicit 0..12 x 0..12 finite normalized 169-cell grid`.
- Formal actual-score support: `109/109`; out-of-support/missing: `0`.
- Result affected selection/generation: `PASS` / `False`.

## Primary Exact endpoint

C - Champion; lower NLL is better. IID bootstrap is 10,000 resamples with the fixed seed; moving-block bootstrap is circular, chronological, fixed block length max(2, round(sqrt(n))).

- Champion Exact NLL: `3.072403452`.
- C Exact NLL: `3.042121649`.
- Mean delta: `-0.030281803`; median delta: `-0.003277721`.
- IID 95% CI: `[-0.09193381098951457, 0.02730067889380867]`; block 95% CI: `[-0.08208967543732618, 0.01879136688728162]`.
- P(mean delta < 0): `0.851100000`.
- LOO max absolute shift: `0.014533683`; sign flip: `False`.
- C assigned higher actual-score probability in `56/109` matches (`0.513761468`).

| Candidate | n | Exact Top1 | Exact Top3 | Exact NLL | Mean p(actual) | 1X2 Acc | 1X2 Brier | 1X2 LogLoss | 1X2 RPS | BTTS Brier | O/U 2.5 Brier | 1-1 Top1 | Median |λH-λA| |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Champion | 109 | 0.100917431 | 0.220183486 | 3.072403452 | 0.059799036 | 0.587155963 | 0.561082138 | 0.949069510 | 0.209696617 | 0.243165704 | 0.230557057 | 0.669724771 | 0.512888000 |
| C | 109 | 0.100917431 | 0.266055046 | 3.042121649 | 0.062005722 | 0.605504587 | 0.544945418 | 0.926482703 | 0.203270111 | 0.241991417 | 0.230557162 | 0.449541284 | 0.680680000 |

## 1X2 and Market control

- C vs Champion accuracy delta: `0.018348624`; Brier delta: `-0.016136720`; LogLoss delta: `-0.022586807`; RPS delta: `-0.006426506`.
- Market control: `COMPARABLE` on `107` identical frozen-input unique matches.
- Market control C-minus-Market Brier mean/CI: `-0.000258900` / `[-0.004289803422883891, 0.0038771756256184083]`.
- Market control C-minus-Market LogLoss mean/CI: `0.000323338` / `[-0.006106835115969616, 0.006857055409419918]`.
- Credible Market dominance on both 1X2 scores: `False`.
- Contract: same-time frozen 1X2 proportional inverse-odds de-vig/equal-bookmaker consensus; positive HK water to decimal; exact quarter-line settlement; per-book total-intensity solve with median; home-share solve; rho=0; AH held out; no closing quote or outcome-conditioned reconstruction.

## Slices

Slices are descriptive only. Every slice below with n < 10 is explicitly `INSUFFICIENT_SAMPLE`; no slice tunes or changes a formula.

| Slice | n | Status | C - Champion Exact NLL |
|---|---:|---|---:|
| chronological_third_1 | 36 | DESCRIPTIVE | -0.032405492 |
| chronological_third_2 | 36 | DESCRIPTIVE | -0.028098004 |
| chronological_third_3 | 37 | DESCRIPTIVE | -0.030340289 |
| horizon::T_0_TO_60M | 38 | DESCRIPTIVE | -0.014831838 |
| horizon::T_60_TO_180M | 35 | DESCRIPTIVE | -0.032466666 |
| horizon::T_3_TO_6H | 24 | DESCRIPTIVE | -0.053661393 |
| horizon::T_6_TO_12H | 12 | DESCRIPTIVE | -0.026074998 |
| horizon::T_12_TO_24H | 0 | INSUFFICIENT_SAMPLE | NA |
| horizon::T_24H_PLUS | 0 | INSUFFICIENT_SAMPLE | NA |
| horizon::HORIZON_UNSAFE | 0 | INSUFFICIENT_SAMPLE | NA |
| competition::巴西杯 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::巴西甲 | 2 | INSUFFICIENT_SAMPLE | NA |
| competition::巴西甲级联赛 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::德乙 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::德国乙级联赛 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::德国杯 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::德国甲级联赛 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::德甲 | 7 | INSUFFICIENT_SAMPLE | NA |
| competition::意大利甲级联赛 | 5 | INSUFFICIENT_SAMPLE | NA |
| competition::意杯 | 3 | INSUFFICIENT_SAMPLE | NA |
| competition::意甲 | 6 | INSUFFICIENT_SAMPLE | NA |
| competition::挪威超级联赛 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::挪超 | 3 | INSUFFICIENT_SAMPLE | NA |
| competition::日职乙 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::日职联 | 7 | INSUFFICIENT_SAMPLE | NA |
| competition::日联杯 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::沙特联 | 6 | INSUFFICIENT_SAMPLE | NA |
| competition::法乙 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::法国乙级联赛 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::法国甲级联赛 | 2 | INSUFFICIENT_SAMPLE | NA |
| competition::法甲 | 6 | INSUFFICIENT_SAMPLE | NA |
| competition::瑞典超 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::瑞典超级联赛 | 3 | INSUFFICIENT_SAMPLE | NA |
| competition::美国职业大联盟 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::英冠 | 13 | DESCRIPTIVE | 0.021732425 |
| competition::英格兰超级联赛 | 4 | INSUFFICIENT_SAMPLE | NA |
| competition::英超 | 6 | INSUFFICIENT_SAMPLE | NA |
| competition::荷乙 | 1 | INSUFFICIENT_SAMPLE | NA |
| competition::荷兰甲级联赛 | 3 | INSUFFICIENT_SAMPLE | NA |
| competition::荷甲 | 3 | INSUFFICIENT_SAMPLE | NA |
| competition::葡萄牙超级联赛 | 2 | INSUFFICIENT_SAMPLE | NA |
| competition::葡超 | 3 | INSUFFICIENT_SAMPLE | NA |
| competition::西班牙甲级联赛 | 4 | INSUFFICIENT_SAMPLE | NA |
| competition::西甲 | 5 | INSUFFICIENT_SAMPLE | NA |
| competition::韩K联 | 2 | INSUFFICIENT_SAMPLE | NA |

## Required paired artifact and final decision

- `summary.json` contains `109` formal paired rows sufficient to recompute the primary delta, both bootstrap inputs, LOO, 1X2 deltas, and secondary metrics.
- Decision checks: `{"1x2_no_ci_entirely_worse": true, "1x2_point_estimates_not_worse": true, "exact_block_ci_upper_negative": false, "exact_iid_ci_upper_negative": false, "exact_mean_delta_negative": true, "loo_no_sign_flip": true, "market_control_not_credible_both_score_dominance": true}`.
- Final decision: **`C_PROMOTION_REVIEW_INCONCLUSIVE`**.
- STOP: research-only evidence; no merge and no automatic promotion.

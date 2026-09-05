# FOOTBALL-MARKET-FUSION-INCREMENTAL-VALUE-1

Research-only, read-only bounded audit. **DO NOT MERGE.**

- Source `origin/main`: `793ff549f`
- Top-level decision: **`CURRENT_FUSION_DILUTES_MARKET`**
- Stop state: `READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE`
- Observation unit: `one football match = one unique match_key`

## Scope and lane contract

The audit uses only frozen legal prematch prediction-time inputs, the accepted Issue #189 market baseline semantics, the existing frozen Champion record, and already persisted regulation-only result artifacts. It makes no network/API/provider calls, does not fetch later or closing odds, and does not modify production, serving, UI, calibration, provider/data, or frozen history.

| Lane | Definition |
|---|---|
| `FOOTBALL_ONLY` | Current Champion recent-form football component with `target_total=form_total` and `share=form_share`; no market predictive state; fail closed if immutable form inputs are missing. |
| `MARKET_ONLY` | Accepted #189 same-time frozen 1X2 proportional inverse-odds de-vig plus O/U line and both prices solved under exact Asian settlement; AH held out. |
| `CURRENT_FUSION` | Persisted/frozen current Champion 1X2; full score matrix is reconstructed only after immutable lambda + Top1/3/5 replay parity. |

### Current Champion implementation truth

- Football state: recent-form `goals_for` / `goals_against` venue and overall rates from the immutable input snapshot, averaged with the current production weighting.
- Market state: current Champion uses market total target and market-derived 1X2 share; the MARKET_ONLY lane is the fixed #189 control, not a fitted component.
- Combination: production uses the fixed `0.60 * form_total + 0.40 * market_total` total and `0.65 * form_share + 0.35 * market_share` direction share before the persisted Champion lambdas; no weights or model parameters are changed here.
- Football-only reconstruction removes the market target/share inputs while retaining the current fixed non-market calibration transforms; its `market_predictive_state_used` flag is false.

## Unique-match funnel

| Stage | Unique matches |
|---|---:|
| Selected legal unique frozen matches | 321 |
| Verified regulation-90m result linkage | 253 |
| Market-only evaluable | 319 |
| Current Fusion replay-valid | 321 |
| Football-only reconstructible | 321 |
| All-three paired unique matches | **251** |
| AH held-out evaluable | 315 |

All three lanes use exactly the same verified unique-match denominator; no lane is allowed to select on the realized score or persisted Champion Top5 membership.

## FT 1X2 paired scorecard

Point estimates and unique-match paired bootstrap 95% CIs. Pairwise delta is left lane minus right lane; lower is better for losses.

| Metric | Football-only | Market-only | Current Fusion | Fusion − Market decision | Football − Market decision | Fusion − Football decision |
|---|---:|---:|---:|---|---|---|
| Top1 accuracy | 0.505976 | 0.585657 | 0.553785 | INDISTINGUISHABLE_WITH_95CI (-0.031873, [-0.071713, 0.003984]) | RIGHT_BETTER (-0.079681, [-0.139442, -0.019920]) | LEFT_BETTER (0.047809, [0.003984, 0.091633]) |
| Log loss | 1.023644 | 0.917834 | 0.972295 | RIGHT_BETTER (0.054461, [0.030270, 0.079834]) | RIGHT_BETTER (0.105810, [0.065624, 0.146685]) | LEFT_BETTER (-0.051349, [-0.067648, -0.036960]) |
| Brier | 0.616038 | 0.539484 | 0.578086 | RIGHT_BETTER (0.038602, [0.020335, 0.055313]) | RIGHT_BETTER (0.076554, [0.046737, 0.106740]) | LEFT_BETTER (-0.037952, [-0.049528, -0.026365]) |
| RPS | 0.230355 | 0.193753 | 0.211543 | RIGHT_BETTER (0.017789, [0.009302, 0.026028]) | RIGHT_BETTER (0.036602, [0.023011, 0.050747]) | LEFT_BETTER (-0.018813, [-0.024333, -0.013160]) |

### Class mix and recall

- `football_only`: `{"actual_class_mix": {"away": {"n": 85, "share": 0.338645}, "draw": {"n": 47, "share": 0.187251}, "home": {"n": 119, "share": 0.474104}}, "per_class_recall": {"away": {"hits": 44, "n": 85, "recall": 0.517647}, "draw": {"hits": 0, "n": 47, "recall": 0.0}, "home": {"hits": 83, "n": 119, "recall": 0.697479}}, "predicted_class_mix": {"away": {"n": 96, "share": 0.38247}, "draw": {"n": 0, "share": 0.0}, "home": {"n": 155, "share": 0.61753}}}`
- `market_only`: `{"actual_class_mix": {"away": {"n": 85, "share": 0.338645}, "draw": {"n": 47, "share": 0.187251}, "home": {"n": 119, "share": 0.474104}}, "per_class_recall": {"away": {"hits": 52, "n": 85, "recall": 0.611765}, "draw": {"hits": 0, "n": 47, "recall": 0.0}, "home": {"hits": 95, "n": 119, "recall": 0.798319}}, "predicted_class_mix": {"away": {"n": 93, "share": 0.370518}, "draw": {"n": 0, "share": 0.0}, "home": {"n": 158, "share": 0.629482}}}`
- `current_fusion`: `{"actual_class_mix": {"away": {"n": 85, "share": 0.338645}, "draw": {"n": 47, "share": 0.187251}, "home": {"n": 119, "share": 0.474104}}, "per_class_recall": {"away": {"hits": 48, "n": 85, "recall": 0.564706}, "draw": {"hits": 0, "n": 47, "recall": 0.0}, "home": {"hits": 91, "n": 119, "recall": 0.764706}}, "predicted_class_mix": {"away": {"n": 91, "share": 0.36255}, "draw": {"n": 0, "share": 0.0}, "home": {"n": 160, "share": 0.63745}}}`

## Research-reconstructed exact-score surface

- Status: **`RIGHT_BETTER`** pairwise scorecard; distribution label: `RESEARCH_RECONSTRUCTED`.
- `FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH=NO`.
- Explicit full-distribution persistence: `0/321`.
- Reconstructed matrices are not historical frozen full-support truth. If replay parity fails, reconstructed Exact NLL and actual-score rank are omitted fail closed.
- Cohort rule: all-three paired unique verified matches; no actual-score-in-Champion-Top5 filter.

| Exact metric | Football-only | Market-only | Current Fusion | Fusion − Market | Football − Market | Fusion − Football |
|---|---:|---:|---:|---|---|---|
| Exact NLL | 3.181543 | 3.023062 | 3.101359 | RIGHT_BETTER (0.078297, [0.041223, 0.115613]) | RIGHT_BETTER (0.158480, [0.098713, 0.222999]) | LEFT_BETTER (-0.080184, [-0.106685, -0.056542]) |
| Full actual-score rank | 9.505976 | 8.298805 | 8.892430 | RIGHT_BETTER (0.593625, [0.286653, 0.900498]) | RIGHT_BETTER (1.207171, [0.736952, 1.701195]) | LEFT_BETTER (-0.613546, [-0.844622, -0.398307]) |

### Exact Top-k hits

| Metric | Football-only | Market-only | Current Fusion |
|---|---:|---:|---:|
| Top1 hit | 0.091633 | 0.123506 | 0.115538 |
| Top3 hit | 0.247012 | 0.310757 | 0.278884 |
| Top5 hit | 0.402390 | 0.430279 | 0.406375 |

## Fusion damage/compression diagnostics

`{"fusion_draw_probability": {"max": 0.323168, "mean": 0.242373, "median": 0.243432, "min": 0.145211, "n": 251, "p10": 0.206975, "p90": 0.274567}, "fusion_minus_market_lambda_gap": {"max": 2.16329, "mean": -0.075652, "median": -0.0565, "min": -1.56851, "n": 251, "p10": -0.64316, "p90": 0.55541}, "fusion_minus_market_lambda_total": {"max": 0.79346, "mean": -0.029783, "median": -0.03059, "min": -1.02883, "n": 251, "p10": -0.35985, "p90": 0.29224}, "market_draw_probability": {"max": 0.301138, "mean": 0.228202, "median": 0.240213, "min": 0.060497, "n": 251, "p10": 0.165205, "p90": 0.272444}, "market_minus_fusion_entropy": {"max": 0.251336, "mean": -0.021145, "median": -0.019559, "min": -0.331051, "n": 251, "p10": -0.148334, "p90": 0.100674}, "market_minus_fusion_top1_probability": {"max": 0.040339, "mean": 0.001551, "median": 0.000931, "min": -0.031168, "n": 251, "p10": -0.009355, "p90": 0.013871}, "n": 251, "note": "lambda totals and gaps are persisted in match_rows; this section reports matrix concentration and draw-compression state without tuning", "predicted_draw_top1_rate": {"current_fusion": 0.0, "market_only": 0.0}, "status": "EVALUABLE", "top1_score_frequency": {"current_fusion": {"0-1": 7, "1-0": 20, "1-1": 185, "1-2": 12, "2-0": 3, "2-1": 24}, "market_only": {"0-1": 12, "0-2": 13, "0-4": 1, "1-0": 28, "1-1": 143, "1-2": 11, "2-0": 26, "2-1": 13, "3-0": 3, "3-1": 1}}}`
Per-match Market-vs-Fusion lambda home/away/total/gap, concentration and top-score fields are persisted in `summary.json` under `fusion_diagnostics.per_match` and `match_rows`.

The diagnostics are descriptive only: no tuning, weight search, model change or selection rule is applied.

## Replay parity and exclusions

- Replay parity: **`321/321`**; status `CHAMPION_FULL_DISTRIBUTION_NOT_FORMALLY_RECONSTRUCTIBLE`.
- Research reconstruction gate: **`RESEARCH_RECONSTRUCTED`**.
- Formal Champion Exact NLL: `None`; formal Top-k probability calibration: `None`.
- Exclusion reasons: `{"1x2": {"NO_FROZEN_1X2_QUOTE_ROWS": 2}, "ah": {"NO_FROZEN_YAZHI_QUOTE_ROWS": 3, "NO_VALID_YAZHI_QUOTE_ROWS": 3}, "baseline": {"NO_FROZEN_1X2_QUOTE_ROWS": 2}, "football": {}, "fusion": {}, "ou": {"NO_FROZEN_DAXIAO_QUOTE_ROWS": 2}, "result": {"NO_VERIFIED_RESULT_LINKAGE_IN_PROSPECTIVE_LEDGER": 68}}`

## Horizon and fixed slices

Horizon, competition and data-grade slices are fixed descriptive views of the same selected observations. Small cells remain descriptive/INSUFFICIENT_SAMPLE and do not authorize a decision.
- Horizon bands: `[{"baseline_evaluable": 38, "id": "T_0_TO_60M", "label": "T-0 to <60m", "lower_minutes": 0.0, "unique_frozen_matches": 39, "upper_minutes": 60.0, "verified_unique_matches": 36}, {"baseline_evaluable": 43, "id": "T_60_TO_180M", "label": "T-60m to <3h", "lower_minutes": 60.0, "unique_frozen_matches": 43, "upper_minutes": 180.0, "verified_unique_matches": 37}, {"baseline_evaluable": 51, "id": "T_3_TO_6H", "label": "T-3h to <6h", "lower_minutes": 180.0, "unique_frozen_matches": 51, "upper_minutes": 360.0, "verified_unique_matches": 43}, {"baseline_evaluable": 84, "id": "T_6_TO_12H", "label": "T-6h to <12h", "lower_minutes": 360.0, "unique_frozen_matches": 85, "upper_minutes": 720.0, "verified_unique_matches": 66}, {"baseline_evaluable": 81, "id": "T_12_TO_24H", "label": "T-12h to <24h", "lower_minutes": 720.0, "unique_frozen_matches": 81, "upper_minutes": 1440.0, "verified_unique_matches": 71}, {"baseline_evaluable": 22, "id": "T_24H_PLUS", "label": "T-24h+", "lower_minutes": 1440.0, "unique_frozen_matches": 22, "upper_minutes": null, "verified_unique_matches": 0}]`
- Slice keys: `competition, data_grade, horizon`

## Product consequence

**CURRENT_FUSION_DILUTES_MARKET** — Stop treating current Fusion as a proprietary edge; do not tune in place. Project Gate must choose between rebuilding Football State Memory and a market-anchored residual.

No Champion, Challenger, calibration, serving, UI, provider/data or frozen-history change is made by this audit.

STOP: `READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE`.

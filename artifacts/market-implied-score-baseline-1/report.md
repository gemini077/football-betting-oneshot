# MARKET-IMPLIED-SCORE-BASELINE-1

Research-only, read-only audit. **DO NOT MERGE.**

- Source `origin/main`: `793ff549f`
- Observation unit: `one football match = one unique match_key`
- Top-level decision: **`MARKET_BASELINE_EVALUABLE`**
- Stop state: `READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE`

## Scope and immutable cohort

The audit reads only repository-resident frozen Champion records, their content-addressed input snapshots, the existing prospective ledger, and already persisted regulation-90m result artifacts. It does not fetch odds, use later/closing quotes, call a provider, or mutate Champion, Challenger, calibration, serving, UI, or frozen history.

Version selection is deterministic: `existing is_formally_eligible gate, then select_latest_legal_prematch by source_cutoff_at, freeze_created_at, prediction_created_at, prediction_id; identity/chronology guarded`. The result is selected before any result artifact is consulted.

## Unique-match funnel

| Stage | Unique matches |
|---|---:|
| Unique frozen selected | 321 |
| Verified regulation-90m result linkage | 253 |
| Raw frozen 1X2 valid (all selected) | 319 |
| Raw frozen O/U valid (all selected) | 319 |
| Verified + raw 1X2 valid | 251 |
| Verified + raw O/U valid | 251 |
| Market baseline evaluable | 319 |
| Paired Champion vs market 1X2 | 251 |
| AH held-out evaluable | 315 |

The all-selected quote counts are reported separately because verified-result linkage is a post-match denominator; they are not silently substituted for paired evaluation n.

## Construction contract

- 1X2: `current spf_current decimal odds, proportional inverse-odds de-vig per bookmaker, equal-weight fair vectors`
- O/U: `current line + both current waters; exact quarter-line Asian settlement; solve lambda_total per bookmaker; aggregate by fixed median`
- Home/away split: `rho=0; bounded deterministic golden-section loss against frozen 1X2 consensus; no AH input`
- AH: `held-out settlement-correct consistency surface only`
- O/U line directly used as expected goals: `False`

## O/U and AH diagnostics

- O/U evaluable matches: `319`; failed: `2`.
- Per-book O/U lambda residual summary: `{"max": 0.0, "mean": -0.0, "median": -0.0, "min": -0.0, "n": 2339, "p10": -0.0, "p90": 0.0}`
- AH was used in the primary fit: `False`.
- AH held-out mean absolute error summary: `{"max": 0.250748, "mean": 0.029233, "median": 0.008457, "min": 0.000178, "n": 315, "p10": 0.004108, "p90": 0.069142}`

## Champion vs market paired scorecard

Values are paired point estimates with deterministic unique-match bootstrap 95% intervals. A delta is Champion minus market; lower is better for loss/error metrics and higher is better for hit metrics.

### FT 1X2

| Metric | Champion | Market | Paired delta | Decision |
|---|---:|---:|---:|---|
| Top1 accuracy | 0.553785 | 0.585657 | -0.031873 [-0.071813, 0.007968] | INDISTINGUISHABLE_WITH_95CI |
| Log loss | 0.972295 | 0.917834 | 0.054461 [0.028786, 0.079840] | MARKET_BETTER |
| Brier | 0.578086 | 0.539484 | 0.038602 [0.020997, 0.055932] | MARKET_BETTER |
| RPS | 0.211543 | 0.193753 | 0.017789 [0.009559, 0.025866] | MARKET_BETTER |

Champion predicted class mix / recall: `{"actual_class_mix": {"away": {"n": 85, "share": 0.338645}, "draw": {"n": 47, "share": 0.187251}, "home": {"n": 119, "share": 0.474104}}, "per_class_recall": {"away": {"hits": 48, "n": 85, "recall": 0.564706}, "draw": {"hits": 0, "n": 47, "recall": 0.0}, "home": {"hits": 91, "n": 119, "recall": 0.764706}}, "predicted_class_mix": {"away": {"n": 91, "share": 0.36255}, "draw": {"n": 0, "share": 0.0}, "home": {"n": 160, "share": 0.63745}}}`
Market predicted class mix / recall: `{"actual_class_mix": {"away": {"n": 85, "share": 0.338645}, "draw": {"n": 47, "share": 0.187251}, "home": {"n": 119, "share": 0.474104}}, "per_class_recall": {"away": {"hits": 52, "n": 85, "recall": 0.611765}, "draw": {"hits": 0, "n": 47, "recall": 0.0}, "home": {"hits": 95, "n": 119, "recall": 0.798319}}, "predicted_class_mix": {"away": {"n": 93, "share": 0.370518}, "draw": {"n": 0, "share": 0.0}, "home": {"n": 158, "share": 0.629482}}}`

### Exact Score Top-k

| Metric | Champion | Market | Paired delta | Decision |
|---|---:|---:|---:|---|
| Top1 hit | 0.115538 | 0.123506 | -0.007968 [-0.043825, 0.027888] | INDISTINGUISHABLE_WITH_95CI |
| Top3 hit | 0.278884 | 0.310757 | -0.031873 [-0.075697, 0.015936] | INDISTINGUISHABLE_WITH_95CI |
| Top5 hit | 0.406375 | 0.430279 | -0.023904 [-0.063745, 0.019920] | INDISTINGUISHABLE_WITH_95CI |

### Actual-score rank surface

Ranks are reported only on the comparable surface: Champion's persisted Top5 list versus the market's full normalized score-matrix ranking. Champion ranks outside persisted Top5 are not reconstructed.
- Comparable unique matches: `102`; not comparable: `149`.
- Champion actual-score rank: `2.666667`; market actual-score rank: `2.862745`; paired delta Champion - market: `-0.196078` [-0.460784, 0.088235].

Market-only descriptive Exact Score NLL: `{"ci95": [2.905987, 3.142485], "iterations": 2000, "n": 251, "point": 3.023062, "seed": 288}`. This is not a paired Champion-vs-market NLL verdict.

### Derived scoring state

BTTS and Over 2.5 Brier are included only because the frozen Champion stores those probability vectors. Missing Champion probabilities are not manufactured.

- BTTS Brier: Champion `0.235656`, market `0.238311`, paired delta `-0.002654` (INDISTINGUISHABLE_WITH_95CI).
- Over 2.5 Brier: Champion `0.225809`, market `0.228072`, paired delta `-0.002263` (INDISTINGUISHABLE_WITH_95CI).

## Full-distribution replay parity

- Status: **`CHAMPION_FULL_DISTRIBUTION_NOT_FORMALLY_RECONSTRUCTIBLE`**
- Replay parity pass: `321/321`
- Explicit full-distribution persistence: `0/321`
- Formal Champion Exact NLL and Top-k probability calibration are omitted. Top1/3/5 hits do not constitute a persisted full-support probability distribution.

## Horizon and slices

Raw horizon statistics: `{"max": 2724.651485, "mean": 563.555155, "median": 442.906151, "min": 1.583973, "n": 321, "p10": 47.483147, "p90": 1029.71474}`

| Horizon band | Unique | Verified | Baseline evaluable |
|---|---:|---:|---:|
| T-0 to <60m | 39 | 36 | 38 |
| T-60m to <3h | 43 | 37 | 43 |
| T-3h to <6h | 51 | 43 | 51 |
| T-6h to <12h | 85 | 66 | 84 |
| T-12h to <24h | 81 | 71 | 81 |
| T-24h+ | 22 | 0 | 22 |

Competition, horizon and data-grade scorecards are persisted in `summary.json` under `slices`; tiny slices are descriptive only and are not treated as superiority evidence.

## Missing/exclusion reasons and integrity

- Exact stage reasons: `{"1x2": {"NO_FROZEN_1X2_QUOTE_ROWS": 2}, "ah": {"NO_FROZEN_YAZHI_QUOTE_ROWS": 3, "NO_VALID_YAZHI_QUOTE_ROWS": 3}, "baseline": {"NO_FROZEN_1X2_QUOTE_ROWS": 2}, "ou": {"NO_FROZEN_DAXIAO_QUOTE_ROWS": 2}, "result": {"NO_VERIFIED_RESULT_LINKAGE_IN_PROSPECTIVE_LEDGER": 68}}`
- Integrity status: **`PASS`**
- Integrity details: `{"ah_used_in_primary_fit": false, "champion_challenger_calibration_serving_ui_mutated": false, "external_provider_calls": 0, "frozen_history_mutated": false, "identity_or_chronology_failures": [], "integrity_status": "PASS", "later_or_closing_quotes_used": false, "network_calls": 0, "postmatch_values_used_to_select_prematch_version": false, "read_only": true}`

## Top-level decision

**`MARKET_BASELINE_EVALUABLE`** — the market baseline is a deterministic research control on the paired cohort; this decision does not authorize Champion/Challenger/model or product changes.

STOP: `READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE`.

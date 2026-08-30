# PRED-TRUST-2 — Strength/Lambda Challenger Shootout

Status: `READY_FOR_ACCEPTANCE`
Decision: `NO_CHALLENGER_BEATS_CHAMPION`

## Scope and pinned evidence

- Accepted production run: `33294381128`
- Accepted write-back commit: `73994d32fc148da49295a5bfef2e1e42e042a22e`
- PRED-TRUST-1 head: `599e7d82b1938e564d2f622c0eb412dd537d2662`
- Replay cohort: `217` unique final legal prematch matches; `181` verified 90m results
- No new data, no parameter fitting, and no post-match field entered lambda generation.

## Short dependency map

```text
football evidence → recent form → form_home/form_away → strength share
market baseline → frozen 1X2 + total line → market share/target total
strength + market boundary → lambda_home/lambda_away
lambda → independent Poisson matrix (rho=0) → 1X2 / BTTS / totals / exact score
calibration is present in the contract but inactive/shadow_only in this pin
```

## Candidate registry

| Candidate | Fixed hypothesis | Changed boundary |
|---|---|---|
| Champion | `current_recent_form_market_calibrated_poisson_v2` | none; replay stored Champion from frozen input |
| Challenger A | `recent_form_strength_separation` | lambda side share only |
| Challenger B | `market_to_goal_separation` | lambda total and side share |

## Verified 90m metrics

| Metric | Champion | Challenger A | Challenger B |
|---|---:|---:|---:|
| 1X2 accuracy | 0.5193 | 0.4641 | 0.5635 |
| 1X2 Brier | 0.5962 | 0.6378 | 0.5536 |
| 1X2 LogLoss | 0.9976 | 1.0544 | 0.9368 |
| Exact Top1 hit | 0.1160 | 0.0994 | 0.1050 |
| Exact Top3 hit | 0.2873 | 0.2541 | 0.3039 |
| Actual-score probability | 0.0612 | 0.0584 | 0.0664 |
| BTTS accuracy | 0.6022 | 0.5912 | 0.5580 |
| BTTS Brier | 0.2335 | 0.2344 | 0.2365 |
| O/U 2.5 accuracy | 0.6243 | 0.6243 | 0.5138 |
| O/U 2.5 Brier | 0.2248 | 0.2248 | 0.2388 |
| 1X2 macro ECE | 0.0853 | 0.0944 | 0.0637 |

## Lambda and score diversity

| Metric | Champion | Challenger A | Challenger B |
|---|---:|---:|---:|
| 1-1 Top1 share | 0.7650 | 0.8018 | 0.4931 |
| Top1 support size | 5.0000 | 8.0000 | 10.0000 |
| High-score Top1 share | 0.0000 | 0.0046 | 0.0046 |
| Gap <0.5 share | 0.6636 | 0.7373 | 0.4931 |
| Median absolute lambda gap | 0.3569 | 0.3275 | 0.5050 |
| Mean P(total >=4) | 0.3169 | 0.3169 | 0.2920 |
| Mean P(total >=5) | 0.1633 | 0.1633 | 0.1467 |
| Mean P(total >=6) | 0.0741 | 0.0741 | 0.0652 |

Actual verified tail reference: `P(total>=4)=0.4144`, `P(total>=5)=0.2210`, `P(total>=6)=0.0939` over `n=181`.

## Machine trade-off table

Every challenger cell is marked against Champion using the pre-registered `±0.005` SAME tolerance.

| Metric | Champion | Challenger A value/status | Challenger B value/status |
|---|---:|---:|---:|
| 1X2 accuracy | 0.5193 | 0.4641 / **WORSE** | 0.5635 / **BETTER** |
| 1X2 Brier | 0.5962 | 0.6378 / **WORSE** | 0.5536 / **BETTER** |
| 1X2 LogLoss | 0.9976 | 1.0544 / **WORSE** | 0.9368 / **BETTER** |
| Exact Score Top1 hit | 0.1160 | 0.0994 / **WORSE** | 0.1050 / **WORSE** |
| Exact Score Top3 hit | 0.2873 | 0.2541 / **WORSE** | 0.3039 / **BETTER** |
| Actual-score probability | 0.0612 | 0.0584 / **SAME** | 0.0664 / **BETTER** |
| Exact Score NLL | 3.1330 | 3.2201 / **WORSE** | 3.0717 / **BETTER** |
| BTTS accuracy | 0.6022 | 0.5912 / **WORSE** | 0.5580 / **WORSE** |
| BTTS Brier | 0.2335 | 0.2344 / **SAME** | 0.2365 / **SAME** |
| O/U 2.5 accuracy | 0.6243 | 0.6243 / **SAME** | 0.5138 / **WORSE** |
| O/U 2.5 Brier | 0.2248 | 0.2248 / **SAME** | 0.2388 / **WORSE** |
| 1X2 macro ECE | 0.0853 | 0.0944 / **WORSE** | 0.0637 / **BETTER** |
| BTTS ECE | 0.0986 | 0.0946 / **SAME** | 0.1795 / **WORSE** |
| O/U 2.5 ECE | 0.2387 | 0.2387 / **SAME** | 0.2951 / **WORSE** |
| 1-1 Top1 share | 0.7650 | 0.8018 / **WORSE** | 0.4931 / **BETTER** |
| Top1 support size | 5.0000 | 8.0000 / **BETTER** | 10.0000 / **BETTER** |
| High-score Top1 share | 0.0000 | 0.0046 / **SAME** | 0.0046 / **SAME** |
| Gap <0.5 share | 0.6636 | 0.7373 / **WORSE** | 0.4931 / **BETTER** |
| Median absolute lambda gap | 0.3569 | 0.3275 / **WORSE** | 0.5050 / **BETTER** |
| Mean P(total >=4) | 0.3169 | 0.3169 / **SAME** | 0.2920 / **WORSE** |

## Qualification and decision

- `challenger_a_strength_separation`: `FAIL`; failed checks: `concentration_materially_improves, exact_top3_not_unacceptable, one_x_two_brier_not_materially_worse, one_x_two_log_loss_not_materially_worse, lambda_gap_distribution_separates`.
- `challenger_b_market_to_goal_separation`: `FAIL`; failed checks: `btts_not_materially_worse, ou_not_materially_worse, right_tail_probability_not_worse`.

Final bounded decision: **NO_CHALLENGER_BEATS_CHAMPION**.
Unique next milestone: **return to inputs / football evidence / market fusion; do not continue lambda patch series**.

## Product interpretation

Preferred option: **D. single Top1 + uncertainty warning**.
Keep the current exact-score contract while explicitly warning that the single Top1 is concentrated and not a high-confidence claim; do not change frontend in this milestone.

## STOP state

Champion, production, shadow, frozen predictions, prospective ledger, health monitor, health gate, providers, UI, and parameter sweeps were not changed.

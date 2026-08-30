# PRED-TRUST-3 - Market-Side-Only Hybrid Knockout

Status: `READY_FOR_ACCEPTANCE`
Decision: `MARKET_SIDE_ONLY_NOT_SUFFICIENT`

## Pinned scope

- PRED-TRUST-2 replay SHA-256: `ebf5d83acc506bfa74dd97e8a9ce58bf37a8156178c41d71aa381cce1b0bb0d3`
- Accepted production run: `33294381128`
- Accepted write-back commit: `73994d32fc148da49295a5bfef2e1e42e042a22e`
- Cohort: `217` unique final legal prematch; `181` verified 90m
- Exactly one new candidate C; no new data, fitting, selector rerun, or post-match parameter input.

## Candidate formulas

```text
Champion: total=0.60*form_total+0.40*market_total; share=0.65*form_share+0.35*market_share
Existing B: total=market_total; share=market_share
New C: total=Champion total; share=market_share
All candidates: clamp + independent Poisson + rho=0 + same score matrix
```

Challenger A remains excluded because PRED-TRUST-2 already marked it REJECT.

## Verified 90m metrics

| Metric | Champion | Existing B | New C |
|---|---:|---:|---:|
| 1X2 accuracy | 0.5193 | 0.5635 | 0.5635 |
| 1X2 Brier | 0.5962 | 0.5536 | 0.5486 |
| 1X2 LogLoss | 0.9976 | 0.9368 | 0.9301 |
| 1X2 macro ECE | 0.0853 | 0.0637 | 0.0554 |
| Exact Top1 hit | 0.1160 | 0.1050 | 0.1160 |
| Exact Top3 hit | 0.2873 | 0.3039 | 0.3039 |
| Exact NLL | 3.1330 | 3.0717 | 3.0306 |
| Actual-score probability | 0.0612 | 0.0664 | 0.0664 |
| BTTS accuracy | 0.6022 | 0.5580 | 0.6022 |
| BTTS Brier | 0.2335 | 0.2365 | 0.2312 |
| BTTS ECE | 0.0986 | 0.1795 | 0.1420 |
| O/U 2.5 accuracy | 0.6243 | 0.5138 | 0.6243 |
| O/U 2.5 Brier | 0.2248 | 0.2388 | 0.2248 |
| O/U 2.5 ECE | 0.2387 | 0.2951 | 0.2387 |

## Lambda and score distribution (n=217)

| Metric | Champion | Existing B | New C |
|---|---:|---:|---:|
| Median lambda total | 2.7700 | 2.5000 | 2.7700 |
| Median absolute lambda gap | 0.3569 | 0.5050 | 0.5340 |
| Gap <0.25 share | 0.3502 | 0.2995 | 0.2673 |
| Gap <0.5 share | 0.6636 | 0.4931 | 0.4793 |
| 1-1 Top1 share | 0.7650 | 0.4931 | 0.5484 |
| Top1 support size | 5.0000 | 10.0000 | 9.0000 |
| Home-margin Top1 share | 0.1751 | 0.3456 | 0.3226 |
| Draw Top1 share | 0.7650 | 0.5023 | 0.5484 |
| Away-margin Top1 share | 0.0599 | 0.1521 | 0.1290 |
| High-score Top1 share | 0.0000 | 0.0046 | 0.0046 |
| Mean P(total>=4) | 0.3169 | 0.2920 | 0.3169 |
| Mean P(total>=5) | 0.1633 | 0.1467 | 0.1633 |
| Mean P(total>=6) | 0.0741 | 0.0652 | 0.0741 |

Actual verified tail: total>=4 `0.4144`, total>=5 `0.2210`, total>=6 `0.0939`.

## Machine trade-off table

Every Existing B/New C cell is `BETTER`, `SAME`, or `WORSE` against Champion using the fixed SAME tolerance.

| Metric | Champion | Existing B value/status | New C value/status |
|---|---:|---:|---:|
| 1X2 accuracy | 0.5193 | 0.5635 / **BETTER** | 0.5635 / **BETTER** |
| 1X2 Brier | 0.5962 | 0.5536 / **BETTER** | 0.5486 / **BETTER** |
| 1X2 LogLoss | 0.9976 | 0.9368 / **BETTER** | 0.9301 / **BETTER** |
| Exact Score Top1 hit | 0.1160 | 0.1050 / **WORSE** | 0.1160 / **SAME** |
| Exact Score Top3 hit | 0.2873 | 0.3039 / **BETTER** | 0.3039 / **BETTER** |
| Actual-score probability | 0.0612 | 0.0664 / **BETTER** | 0.0664 / **BETTER** |
| Exact Score NLL | 3.1330 | 3.0717 / **BETTER** | 3.0306 / **BETTER** |
| BTTS accuracy | 0.6022 | 0.5580 / **WORSE** | 0.6022 / **SAME** |
| BTTS Brier | 0.2335 | 0.2365 / **SAME** | 0.2312 / **SAME** |
| O/U 2.5 accuracy | 0.6243 | 0.5138 / **WORSE** | 0.6243 / **SAME** |
| O/U 2.5 Brier | 0.2248 | 0.2388 / **WORSE** | 0.2248 / **SAME** |
| 1X2 macro ECE | 0.0853 | 0.0637 / **BETTER** | 0.0554 / **BETTER** |
| BTTS ECE | 0.0986 | 0.1795 / **WORSE** | 0.1420 / **WORSE** |
| O/U 2.5 ECE | 0.2387 | 0.2951 / **WORSE** | 0.2387 / **SAME** |
| 1-1 Top1 share | 0.7650 | 0.4931 / **BETTER** | 0.5484 / **BETTER** |
| Top1 support size | 5.0000 | 10.0000 / **BETTER** | 9.0000 / **BETTER** |
| High-score Top1 share | 0.0000 | 0.0046 / **SAME** | 0.0046 / **SAME** |
| Gap <0.25 share | 0.3502 | 0.2995 / **BETTER** | 0.2673 / **BETTER** |
| Gap <0.5 share | 0.6636 | 0.4931 / **BETTER** | 0.4793 / **BETTER** |
| Median absolute lambda gap | 0.3569 | 0.5050 / **BETTER** | 0.5340 / **BETTER** |
| Mean P(total >=4) | 0.3169 | 0.2920 / **WORSE** | 0.3169 / **SAME** |
| Mean P(total >=5) | 0.1633 | 0.1467 / **WORSE** | 0.1633 / **SAME** |
| Mean P(total >=6) | 0.0741 | 0.0652 / **WORSE** | 0.0741 / **SAME** |

## Decision

New C qualification: `FAIL`.
Failed checks: `btts_ece_not_materially_worse`.
Final bounded decision: **MARKET_SIDE_ONLY_NOT_SUFFICIENT**.
Next sole milestone: **football evidence / team strength representation; stop market/lambda patch series**.

## Product interpretation

Keep a single exact-score Top1 with an insufficient-confidence warning. No UI change is part of this milestone.

## STOP state

Champion, production, shadow, frozen predictions, prospective ledger, health monitor/gate, providers, and frontend were not changed.

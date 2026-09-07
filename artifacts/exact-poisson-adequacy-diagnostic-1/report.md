# EXACT-POISSON-ADEQUACY-DIAGNOSTIC-1

- Decision: `POISSON_MISSPECIFICATION_SIGNAL_ESTABLISHED`
- Misspecification dimension: `LOW_SCORE`
- Fixed cohort: `107/107` unique matches; authority `PASS`
- Chronology: `2026-08-30T19:30:00+08:00` to `2026-09-06T23:00:00+08:00`
- Lambda reference digest: `57394d420957baa87b3efeae51545d21849c10cc59d136b170d213526019b911`

## Fixed parameter-free diagnostics

| Quantity | Observed | Predicted / reference | Bootstrap 95% CI |
|---|---:|---:|---:|
| Home goals mean | 1.682243 | 1.603315 | [-0.137921, 0.297775] gap |
| Home goals dispersion | 0.872095 | 1.000000 | [0.648302, 1.134052] |
| Away goals mean | 1.672897 | 1.405626 | [0.051290, 0.488806] gap |
| Away goals dispersion | 1.028182 | 1.000000 | [0.732039, 1.406752] |
| Total goals mean | 3.355140 | 3.008941 | [0.044203, 0.650677] gap |
| Total goals dispersion | 0.879331 | 1.000000 | [0.645271, 1.159899] |

### Home/away dependence
- Standardized residual covariance: `-0.043284`; CI `[-0.205757, 0.116354]`
- Standardized residual correlation: `-0.060771`; CI `[-0.236893, 0.100618]`

### Randomized PIT
- home: seed `2251502`, bins `10`, max bin gap `0.062617`, mean-minus-0.5 CI `[-0.016688, 0.083588]`, repeated max-gap mean `0.051794`
- away: seed `2251503`, bins `10`, max bin gap `0.114953`, mean-minus-0.5 CI `[0.025305, 0.133192]`, repeated max-gap mean `0.077533`
- total: seed `2251504`, bins `10`, max bin gap `0.071963`, mean-minus-0.5 CI `[0.021092, 0.119092]`, repeated max-gap mean `0.069495`

### Right tails

| Tail | Observed | Predicted | Gap | CI | Signal |
|---|---:|---:|---:|---:|---|
| total >= 4 | 0.429907 | 0.353826 | 0.076080 | [-0.013525, 0.167459] | False |
| total >= 5 | 0.242991 | 0.191246 | 0.051745 | [-0.025019, 0.134052] | False |
| total >= 6 | 0.084112 | 0.091609 | -0.007497 | [-0.056001, 0.049025] | False |

### Low-score cells

| Score | Observed | Predicted | Gap | CI | Signal |
|---|---:|---:|---:|---:|---|
| 0-0 | 0.000000 | 0.054290 | -0.054290 | [-0.058517, -0.050303] | True |
| 1-0 | 0.056075 | 0.081685 | -0.025610 | [-0.064384, 0.021920] | False |
| 0-1 | 0.074766 | 0.071943 | 0.002823 | [-0.043685, 0.054581] | False |
| 1-1 | 0.084112 | 0.101302 | -0.017190 | [-0.065517, 0.037493] | False |

### Exact-score context only
- Exact NLL: `3.037954`; IID bootstrap 95% CI `[2.880190, 3.213311]`
- Top1: `0.112150`; Top3: `0.271028`; mean actual-score probability `0.061951`
- Actual-score rank quantiles: `{"P10": 1.0, "P25": 3.0, "P50": 7.0, "P75": 11.0, "P90": 16.200000000000017}`
- 1-1 top-score share: `0.514019`

### Score space / tails / support
- Fixed Market lambda was reconstructed with the accepted #189 same-time contract and the fixed 20x20 score matrix; matrix tail mass is carried per match.
- Poisson tail diagnostics use analytic independent-Poisson total-goal tails; no tail renormalization or new score family was introduced.
- Actual scores outside the supported matrix would fail closed; all 107 actual scores were in support.

### Scope / integrity
- No training, parameter fitting, alternative-family comparison, serving/UI/history change, replay/backfill, new source, or automatic promotion.
- Bootstrap resamples: `10000`; fixed PIT seed: `2251501`; PIT randomization replicates: `100`.
- Integrity: `PASS`

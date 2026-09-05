# Exact distribution freeze

## Current production trace

The current deterministic Champion path is unchanged mathematically:

```text
lambda_home / lambda_away / rho
  -> risk_engine.dixon_coles_score_matrix(max_goals=12)
  -> approved dispersion mixture, when enabled
  -> approved direction reweight, when enabled
  -> effective Exact matrix
  -> automatic_model_core._model_rows(matrix)
  -> score_top1 / score_top3 / score_top5 and the frozen governance record
```

`automatic_model_core.build_automatic_model(..., include_exact_distribution=True)` captures the matrix at the effective-matrix/display boundary, after every currently approved transformation and before Top score projection. The normal model return is unchanged; the capture is an additive freeze-time state used by the two existing Champion freeze paths.

## Frozen contract

New formal Champion records contain `exact_score_distribution` inline. Its
`content_sha256` is calculated from canonical UTF-8 JSON (`sort_keys=true`,
compact separators, `allow_nan=false`) with cells ordered by home goals and then
away goals. The contract stores the governed model/run identity, unrounded
prediction-time lambda/rho state, transformation trace, every effective cell,
normalization diagnostics, finite boundaries, and the production path.

The current matrix is exactly 169 explicit cells covering `0..12 × 0..12`.
It is a **FINITE_NORMALIZED_GRID**, has `full_support=false`, and has no tail
bucket. A realized score outside this domain is
`OUT_OF_EXPLICIT_SUPPORT`; no overflow probability is invented.

The risk engine exposes the normalized finite grid but not a frozen
pre-normalization infinite-support tail mass. Therefore the contract records
`tail_diagnostic.status=UNRESOLVED_NOT_REPRESENTED`, with a null omitted-mass
value. This is intentional and makes the delivery result
`EXACT_DISTRIBUTION_FREEZE_PARTIAL`, rather than calling the finite grid full
support.

## Formal evaluation

`prospective_settlement.evaluate_prediction` reads the inline contract only
for formal Exact log-score eligibility. It distinguishes:

- `FORMAL_EXACT_DISTRIBUTION_FROZEN`;
- `FINITE_GRID_EXACTLY_REPRESENTED`;
- `OUT_OF_EXPLICIT_SUPPORT`;
- `FORMAL_EXACT_LOG_SCORE_ELIGIBLE`.

Old records remain readable without the new object. Their historical Exact
metrics remain `RESEARCH_RECONSTRUCTED` and
`FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH=false`; no old record or input snapshot
is rewritten.

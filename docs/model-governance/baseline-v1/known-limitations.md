# Baseline v1 Known Limitations

- The current Champion has 311 model-output records and 37 deduplicated
  matches in the report history. A/B formal prediction records number 265.
- There are no settled Champion reviews that are both model-version matched
  and grade A/B. Formal Champion Brier Score, Log Loss, win/draw/loss,
  over/under, BTTS, score Top 1/3/5, mean score rank, ROI, CLV, and maximum
  drawdown are therefore `null` in `current-metrics.json`.
- Existing v0.19.0 post-match reviews are grade C research records. They are
  intentionally excluded from Champion formal metrics.
- `rho` is fixed at zero. The implementation uses a Poisson score matrix with
  this zero value; it is not evidence of an estimated Dixon-Coles correction.
- The formal model uses recent actual-goal form and market calibration. A
  separately validated xG, Elo, and lineup-capacity model is not part of this
  Champion baseline.
- The repository has no reliable verified real executable price and closing
  price series for formal Champion samples. ROI and CLV remain null.
- Historical reports contain multiple releases and older records with missing
  version, snapshot, or governance fields. They are not backfilled and are
  kept outside the Champion record set.
- The baseline inventory is derived from immutable timestamped report snapshots;
  the new governance ledger under `data/model_governance/predictions/` is empty
  until the next production prediction. The baseline is therefore an observed
  historical report inventory, not a retroactively fabricated ledger.
- The legacy `data/analysis_reports/current/` view is a replaceable convenience
  view. Phase 0 does not rewrite it; only new records under the governance
  prediction root receive immutable id conflict protection.
- Historical report snapshots do not provide a complete same-match,
  same-time, reproducible input chain for every record. Missing fields remain
  null and prevent formal eligibility.
- The existing post-match generator emits schema version 3.0 while the old
  checked-in schema declared 1.0. Phase 0 aligns the schema declaration for new
  records; old records are not rewritten.
- Current evidence does not demonstrate that the Champion beats a market or
  simple baseline. No Challenger is eligible for promotion in Phase 0.

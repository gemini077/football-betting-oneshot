# Baseline v1 Known Limitations

- The historical report inventory contains repeated timestamped reports and a
  replaceable `data/analysis_reports/current/` view. The view is excluded from
  the independent inventory and is not counted as another sample.
- Historical reports without a governance `prediction_id` remain
  `historical_report_inventory` only. They are not retroactively called frozen
  predictions.
- The Phase 0.1 governance ledger is empty until a production run writes a
  record under `data/model_governance/predictions/`. Therefore
  `true_governance_frozen_predictions`, formal model samples, and exact-settled
  formal samples may be zero even when the historical report inventory is
  large.
- There are no exact-settled Champion A/B model-only reviews in the current
  governance ledger. Formal Brier Score, Log Loss, win/draw/loss, over/under,
  BTTS, score Top 1/3/5, mean score rank, ROI, CLV, and maximum drawdown remain
  `null` until that exact join exists.
- `rho` is fixed at zero. The model uses a Poisson score matrix with that
  configured value; this is not evidence of an estimated Dixon-Coles
  correction.
- The Champion currently uses recent actual-goal form and market calibration.
  A separately validated xG, Elo, or lineup-capacity model is not part of this
  baseline.
- No reliable verified real executable price and closing-price series exists
  for formal Champion samples. ROI and CLV therefore remain `null`.
- Existing releases and post-match files have incomplete governance metadata.
  They are not rewritten, guessed, or merged into Champion formal metrics.
- Historical input snapshots do not prove that every old report can be
  re-run from the exact pre-match sources. New frozen records store a
  content-addressed input snapshot and its source references; old records do
  not receive a fabricated snapshot.
- The model report may have narrative or DeepSeek content that does not alter
  deterministic probabilities. That narrative is intentionally excluded from
  the Champion deterministic input hash. A future Challenger using narrative
  as a feature would require its own declared identity and input contract.
- A manual override can be saved for research and presentation, but it is
  isolated as `human_assisted` and cannot be used to claim pure model accuracy.
- Current evidence does not establish that the Champion beats a market or
  simple baseline. No Challenger is registered or eligible for promotion in
  Phase 0.1.

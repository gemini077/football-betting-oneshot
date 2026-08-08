# Model Governance

Football Betting OneShot is an event analysis and probability platform. Betting
reference is a downstream, separately gated output. An analysis may exist
without a prediction, and a prediction may exist without an evaluable betting
reference when no real executable price is available.

## Champion and Challenger

Phase 0 freezes one Champion:

- Core: `recent_form_market_calibrated_poisson_v2`
- Release: `v0.19.0`
- Family: the exact family name emitted by `scripts/automatic_model_core.py`
- `rho`: fixed at `0.0`; this is not an estimated Dixon-Coles parameter
- Challengers: none

Future changes follow this sequence:

1. Freeze the current Champion.
2. Run a Challenger in shadow mode on the same match and the same snapshot.
3. Compare the market baseline, a simple baseline, and the Champion.
4. Validate out of sample with reproducible inputs.
5. Promote only after the gates pass and a human approves; otherwise keep the
   Champion and record the rejection.

The current Champion is never replaced by a later report or by a single match
result. Rollback means selecting the last frozen Champion configuration and its
recorded file hashes.

## Formal Samples

All matches can remain research analysis. Only grades A and B can be formal
Champion samples. Grades C and D are `formal_eligible=false` and
`prediction_status=research_only`. Missing critical input is recorded as
`missing_critical_fields`; it is not guessed or backfilled.

Each new frozen prediction records the repository commit, model, feature,
data-pipeline, report-schema, post-match-schema, and prompt versions; timestamps
for creation, kickoff, source cutoff, and odds snapshot; data grade; override
status; input hash; final prediction hash; lambdas; probabilities; score ranks;
and the three output classes:

- `analysis_output`
- `prediction_output`
- `betting_reference_output`

The immutable record is stored under `data/model_governance/predictions/` by
the production report generator. Re-freezing the same content is idempotent.
Reusing an id with different content raises a conflict. Match results,
settlement, and post-match review are not written into that frozen record.
The fixed-core path uses prompt version `fixed-python-core.none`; the optional
DeepSeek path records `deepseek_system_prompt.v1`.

## Correction Policy

No single match can update formal parameters. A promotion requires at least 50
holdout samples, same-match same-snapshot comparison, out-of-sample validation,
reproducible inputs, a market baseline, and a simple baseline. Brier Score must
improve and Log Loss must not deteriorate. Automatic promotion is disabled.

See `baseline-v1/manifest.json`, `baseline-v1/current-metrics.json`, and
`baseline-v1/known-limitations.md` for the frozen Phase 0 evidence.

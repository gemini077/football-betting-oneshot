# Phase A owner map — Issue #236

Scope: `KERNEL-CONSOLIDATION-A1` only. This map records the implementation
ownership after parity migration from the latest `origin/main`; it does not
authorize Issue #235 or any model-policy change.

| Domain behavior | Old implementation owners | Canonical owner | Remaining callers / compatibility | Duplicate disposition |
| --- | --- | --- | --- | --- |
| Champion bookmaker quote validation, proportional de-vig, mean consensus, total/handicap extraction, and expected-total line pricing | `automatic_model_core.py`, plus quote/de-vig helpers in `base_prediction_runner.py` | `scripts/market_engine.py` (`CHAMPION_MARKET_POLICY = champion.multibook_proportional_devig_mean.v1`) | `automatic_model_core.py`, `base_prediction_runner.py`, `prediction_trust_2_replay.py` | Moved; old private implementations deleted. |
| `market_reference.v1` raw frozen-market extraction, provider/bookmaker identity, deduplication, de-vig, median consensus, and line extraction | `model_baselines.py` | `scripts/market_engine.py` (`MARKET_REFERENCE_POLICY = market_reference.v1`) | `model_baselines.py` re-exports the canonical function for API compatibility; benchmark callers continue through that public name | Moved; `model_baselines.py` contains no duplicate Market implementation. |
| Asian total/handicap contract semantics (realized score -> settlement units/category) | `market_contracts.py`, `market_engine.py`, `score_engine.py` | `scripts/market_contracts.py::settle_asian_contract` | `settle_contract()` and Market/Score pricing aggregators consume the primitive; product/contract and pricing responsibilities remain separate | Duplicate delta/component/full-half-push-loss rules deleted from pricing owners. |
| 90-minute quarter-line contract settlement | `market_contracts.py` | `scripts/market_contracts.py` | Market/Score owners consume the canonical Asian primitive; existing settlement callers remain | Retained as the low-level contract owner. |
| Dixon-Coles/Poisson finite score matrix | `risk_engine.py`, with simple-Poisson construction in `model_baselines.py` | `scripts/score_engine.py` | `risk_engine.py` re-exports the four legacy public risk symbols; production callers use `score_engine.py` | Matrix builders deleted from old owners. |
| Matrix → 1X2, exact Top-k, totals, BTTS, benchmark score rows/distribution | `automatic_model_core.py`, `model_baselines.py`, `baseline_production.py`, report projection code | `scripts/score_engine.py` | Champion, simple-Poisson baseline, benchmark replay, and report callers use public projections | Duplicate projection implementations deleted; presentation-only row readers remain outside the kernel. |
| Matrix → Asian total/handicap and exact-total pricing | `risk_engine.py`, `automatic_model_core.py` | `scripts/score_engine.py` | `risk_engine.py` keeps import-only compatibility aliases; Champion uses `matrix_settlement_probability` | Duplicate pricing code deleted; quarter-line splitting remains in `market_contracts.py`. |
| Immutable Exact serialization/freeze | `scripts/exact_distribution.py` | `scripts/exact_distribution.py` | Consumes the effective matrix supplied by `score_engine.py` | Intentionally retained; it serializes and validates, it does not rebuild the model. |

## Compatibility removal triggers

- Remove the `model_baselines.py` `build_market_reference` re-export after all
  external benchmark consumers import `market_engine` directly.
- Remove the `risk_engine.py` score re-exports after the public risk API has a
  separately accepted compatibility migration. They contain no score logic.
- Revisit immutable `exact_distribution.py` provenance strings only with an
  explicit contract/version decision; existing frozen records remain untouched.

## Policy boundary

Champion and `market_reference.v1` intentionally retain different aggregation
semantics. This PR changes ownership only; it does not unify averaging,
bookmaker selection, de-vig, line selection, score formulas, calibration,
serving, UI, or frozen history.

## Phase B — Issue #238 evaluation ownership

This section records the behavior-preserving evaluation migration.  It does
not make `evaluation_kernel.py` a model, serving, wager-contract, or Exact
freeze owner.

| Domain behavior | Old implementation owners | Canonical owner | Migrated callers | Duplicate disposition |
| --- | --- | --- | --- | --- |
| Verified regulation-90m result normalization and outcome identity | `baseline_settlement.py`, `prospective_settlement.py`, postmatch review inputs | `scripts/evaluation_kernel.py::normalize_verified_result` | benchmark settlement, prospective settlement, production review evaluation | Old parsing/normalization implementations deleted; `prospective_settlement.py::normalize_result` remains a shape/legacy-label wrapper only. |
| 1X2 outcome probability, Brier, Log Loss and Top-1 evaluation | `baseline_settlement.py`, `automatic_postmatch_review.py`, `prospective_settlement.py` | `scripts/evaluation_kernel.py::evaluate_1x2_probabilities` | benchmark settlement, production review, formal prospective settlement | Duplicate formulas deleted; report/benchmark/prospective output shaping remains local. |
| Exact actual-score probability/rank, Top-k and NLL evaluation | `baseline_settlement.py`, `automatic_postmatch_review.py`, `prospective_settlement.py` | `scripts/evaluation_kernel.py::evaluate_exact_score` | benchmark settlement, production review, formal prospective settlement | Shared row/rank/NLL semantics deleted from old owners; `exact_distribution.py` remains the formal frozen authority and is consumed, not reconstructed. |
| Lambda/goal residual diagnostics | `baseline_settlement.py`, `automatic_postmatch_review.py`, `prospective_settlement.py` | `scripts/evaluation_kernel.py::evaluate_goal_residuals` | benchmark settlement, production review, formal prospective settlement | Signed/absolute residual formulas now have one owner; report and benchmark field names remain compatibility shaping. |

Intentionally retained outside the evaluation owner: `market_contracts.py`
wager settlement, `exact_distribution.py` formal immutable freeze/classification,
JC total-goals/handicap-specific evaluation, benchmark persistence, postmatch
report text/presentation, and model/score construction.

## Generated-state bounded index — Issue #242

This slice changes only the generated current view.  Immutable Market-Side
pair files and verified result artifacts remain the evidence authorities; the
current view is a derived summary/index and never a second history store.

| Domain behavior | Canonical owner | Consumers / boundary | Guard |
| --- | --- | --- | --- |
| Immutable Market-Side pair capture and pair-file persistence | `scripts/market_side_shadow.py::persist_pair` and `load_persisted_pairs` | `data/prediction_quality/market_side_shadow_1/pairs/*.json` remains the pair/version evidence authority | Pair files are loaded by the compact index and are not rewritten by refresh. |
| Current generated summary/index shape and atomic refresh | `scripts/market_side_shadow_refresh.py::build_compact_shadow_view`, `build_bounded_current_evaluation`, `refresh_shadow` | `market_side_shadow_1/latest.json` retains bounded counts, checkpoint, consumer-required candidate/early-kill aggregates and pointer metadata without embedding pair documents or representative history arrays | `tests/test_generated_state_architecture_guard.py` and production-shaped compact-view size/shape tests. |
| Evaluation, checkpoint and one-match-one-observation semantics | `scripts/market_side_shadow.py::evaluate_paired_cohort`, `checkpoint_status`, `build_shadow_document` | Refresh computes the accepted full semantic document, then persists only the bounded consumer projection; Challenger C reloads canonical pairs and recomputes representative provenance | Compact refresh parity tests compare counts/checkpoint and consumer-required evaluation aggregates to the full semantic document. |
| Challenger C review pair input | `scripts/market_side_shadow_refresh.py::load_indexed_pairs` | `scripts/challenger_c_promotion_review.py::run_review` loads the canonical pair root named by `pair_index` and verifies its pair count/content digest; review/promotion policy remains unchanged | Architecture guard forbids direct `latest["pairs"]` consumption and per-pair current-index entries. |
| Production cycle summary | `scripts/market_side_shadow_refresh.py::refresh_shadow` return payload | `scripts/automation_cycle.py::_summary` consumes bounded status/count fields only; Pages stages the directory as before | Production refresh regression checks pair/result hashes and compact output size. |

The compact current-view schema is `market_side_shadow_1.current.v2`, with
`market_side_shadow_1.pair_index.v2` bounded `root` + `pair_count` +
`pair_set_digest` metadata.  The digest is computed over sorted canonical
pair identity/content records; review reloads the pair root and verifies both
count and digest before evaluation.  No pair, frozen
prediction, verified result, model, serving, UI, promotion, runner, package,
workflow, or Git-history authority is moved by this slice.

# Phase A owner map — Issue #236

Scope: `KERNEL-CONSOLIDATION-A1` only. This map records the implementation
ownership after parity migration from the latest `origin/main`; it does not
authorize Issue #235 or any model-policy change.

| Domain behavior | Old implementation owners | Canonical owner | Remaining callers / compatibility | Duplicate disposition |
| --- | --- | --- | --- | --- |
| Champion bookmaker quote validation, proportional de-vig, mean consensus, total/handicap extraction, and expected-total line pricing | `automatic_model_core.py`, plus quote/de-vig helpers in `base_prediction_runner.py` | `scripts/market_engine.py` (`CHAMPION_MARKET_POLICY = champion.multibook_proportional_devig_mean.v1`) | `automatic_model_core.py`, `base_prediction_runner.py`, `prediction_trust_2_replay.py` | Moved; old private implementations deleted. |
| `market_reference.v1` raw frozen-market extraction, provider/bookmaker identity, deduplication, de-vig, median consensus, and line extraction | `model_baselines.py` | `scripts/market_engine.py` (`MARKET_REFERENCE_POLICY = market_reference.v1`) | `model_baselines.py` re-exports the canonical function for API compatibility; benchmark callers continue through that public name | Moved; `model_baselines.py` contains no duplicate Market implementation. |
| 90-minute quarter-line contract settlement | `market_contracts.py` | `scripts/market_contracts.py` | Market/Score owners call `split_quarter_line`; existing settlement callers remain | Retained as the low-level contract owner. |
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

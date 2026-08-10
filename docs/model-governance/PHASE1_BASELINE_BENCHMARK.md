# Phase 1.1 — Same-Snapshot Baseline Benchmark

This is an internal, prospective-only experiment. It does not change the
Champion mathematics, Champion weights, lambda, rho, calibration, selectors,
confidence, public pages, betting state, or user-facing terminology.

The three independent pre-match outputs are:

1. Market Reference — `market_reference.v1`
2. Simple Poisson — `simple_poisson.v1`
3. Current Champion — an existing formal frozen prediction reference

The comparison contract remains `benchmark_comparison.v1`.

## Production flow

The only formal production path is:

```text
Phase 0 frozen Champion prediction
  -> immutable governance input snapshot
  -> benchmark_snapshot.v1 adapter
  -> Market Reference + Simple Poisson
  -> same-snapshot comparison freeze
  -> verified 90-minute result
  -> separate settlement freeze
```

`build_benchmark_snapshot_from_frozen_prediction` loads the exact
`data/model_governance/input_snapshots/<sha256>.json` content referenced by the
Champion record. It validates the record hash, snapshot hash, snapshot id, and
content-addressed filename. It never fetches a provider, reparses HTML, reads
the latest workspace, or reruns the Champion.

The adapter output stores the exact `model_input` from
`deterministic_model_input.v1`, plus `checkpoint_stage`, target/capture times,
and the frozen Champion identity. Invalid or unavailable input is a benchmark
error/status only; the normal match report remains successful.

## Snapshot identity and checkpoint provenance

All predictor outputs carry the same:

```text
match_key
snapshot_id
canonical_model_input_sha256
source_cutoff_at
market_snapshot_at
checkpoint_stage
```

`comparison_id` is the SHA-256 digest of:

```text
match_key + "|" + snapshot_id + "|" + benchmark_contract_version
```

Checkpoint metadata comes from the production
`prematch_market_monitor.checkpoint_meta` path and the scheduled task stage.
The code never infers `T-30M` merely from minutes-to-kickoff. If the production
record cannot prove a registered stage, it is `unclassified` and cannot enter
the primary cohort. `T-30M` is primary only when the actual scheduled stage,
target time, capture time, and trusted source/market timestamps are present.
`T-8H`, `T-2H`, and other registered stages are secondary diagnostics.

## Market Reference v1

Only real 1X2 quotes in the immutable model input are read. Each valid company
is independently de-vigged using reciprocal odds. At least two unique
companies must have three odds strictly greater than `1`. De-vigged
home/draw/away probabilities are median-aggregated by direction and normalized
again. Raw company de-vig probabilities, min/max, dispersion, provider, and
canonical bookmaker id are retained.

The fixed provider priority is `nowscore` primary, then `500_deep` fallback.
The same normalized bookmaker name is counted once across providers. Asian
Handicap and O/U lines and real quotes are recorded only; no market lambda,
expected-goal value, BTTS probability, or score matrix is invented.

Market Reference supports 1X2 fair probabilities, Brier, Log Loss, Top-1,
bookmaker count, and market dispersion. Market-only score/goal/BTTS metrics are
`null`.

## Simple Poisson v1

The baseline reads only recent actual goals from
`benchmark_snapshot.model_input.source_snapshots` in the fixed provider order,
then the explicit `prematch_fundamentals.recent_form` fallback. It never reads
1X2, Asian Handicap, O/U, BTTS markets, Champion output, LLM/news text,
calibration, or a price timeline.

The venue fallback is independent per side:

```text
home row = home_home, else home_overall
away row = away_away, else away_overall
```

Therefore mixed `home_home + away_overall` and
`home_overall + away_away` are valid and explicitly recorded. The fixed safety
range is `0.15 <= lambda <= 4.0`; the matrix is independent Poisson with
`rho=0`. The output includes lambda, expected goals, 1X2, BTTS, total-goal
distribution, score matrix, and score Top-1/3/5/10.

## Paired statistics and eligibility

Individual availability diagnostics are separate from head-to-head conclusions.
For example, “Market evaluable 61/100” is not a three-way comparison result.

`paired_3way_1x2` contains only the exact same sorted `match_keys` for which
Market Reference, Simple Poisson, and the frozen Champion all have evaluable
1X2 probabilities. Its Brier, Log Loss, and Top-1 values use that one paired
set.

`paired_model_distribution` has an availability diagnostic, but it is not a
head-to-head sample size. Every formal distribution metric has its own object:

```json
{
  "score_top5": {
    "n": 0,
    "match_keys": [],
    "simple_poisson": null,
    "champion": null
  }
}
```

The supported paired metrics are BTTS accuracy, total-goal absolute error,
expected-goal error, and score Top-1/3/5/10. Each metric includes only matches
where both models have a non-null value, so its `n` and `match_keys` cannot be
borrowed from another metric.

The frozen Champion score output is Top-10 only. Therefore formal paired
actual-score rank and actual-score probability are paused with explicit
statuses (`unsupported_for_champion_full_distribution` and
`unsupported_until_full_champion_distribution_is_frozen`). A Top-10 hit may
remain in the individual settlement diagnostic, but it is never averaged as a
full-distribution head-to-head result.

A formal record must satisfy all of:

```text
benchmark_scope == prospective
comparison_status == complete
same_snapshot == true
synthetic == false
excluded_from_formal_metrics == false
prospective_origin == production_new_freeze
```

Primary aggregation additionally requires `cohort=primary` and
`primary_benchmark_eligible=true`. Secondary stages remain separate. If one
match has multiple primary records, all are marked
`duplicate_primary_conflict` and excluded conservatively; aggregation never
depends on file traversal order.

Historical reports are not backfilled. Prototype files are research-only.
The formal production path is only a newly created frozen Champion record:
`freeze_prediction(...)["status"] == "created"`. Existing frozen records are
reported as `skipped_existing_prediction` and cannot create a prospective
comparison. Manual/CLI runs default to `historical_exploratory`, which is
always excluded from formal aggregation. The formal prospective start is the
Phase 1.1 production-wiring merge; the implementation also records the
minimum boundary `a14a654e3d80186bb8c93561939e51a4b1ec4ff4`.

## Immutable files and settlement

```text
data/model_benchmarks/
  predictions/<comparison_id>.json
  settlements/<comparison_id>.json
  summaries/
```

Prediction and settlement files are create-only. Identical re-writes are
idempotent; different content for an existing id raises
`BenchmarkConflictError`. Settlement uses the verified regulation
90-minute result (`regulation_90m_plus_stoppage`) and excludes extra time and
penalties. Missing comparison is a no-op. ROI and CLV remain `null` without a
confirmed real transaction price.

## Synthetic smoke and verification

`python scripts/run_baseline_synthetic_smoke.py` runs `Test Home vs Test Away`
through real Phase 0 functions (`build_deterministic_model_input_snapshot`,
`build_prediction_record`, `freeze_prediction`), the production adapter,
both baselines, comparison freeze, the production settlement hook, and
aggregation. The smoke fixture and all outputs are synthetic and have
`excluded_from_formal_metrics=true`; formal paired `n` remains zero.

```bash
python -m pytest tests/test_model_baselines.py -q
python -m pytest tests/test_baseline_shadow_runner.py -q
python -m pytest tests/test_baseline_settlement.py -q
python -m pytest tests/test_baseline_synthetic_smoke.py -q
python -m pytest tests/test_baseline_production_integration.py -q
```

Observation gates are diagnostic only: 10 matches for a system check, 25 for
data quality, 50 independent primary matches for a first statistical
diagnostic, 100 for stability observation, 300 before discussing structural
changes, and 500+ for slices. None authorizes single-match correction or
Champion tuning.

# Phase 1 — Same-Snapshot Baseline Benchmark Foundation

Phase 1 is an internal, prospective-only comparison of three independent
pre-match outputs for the same match and the same frozen snapshot:

1. `Market Reference` — `market_reference.v1`
2. `Simple Poisson` — `simple_poisson.v1`
3. `Current Champion` — a reference to an existing formal frozen prediction

The benchmark contract is `benchmark_comparison.v1`. It does not change the
Champion, the public pages, betting state, calibration, selectors, confidence,
or any model parameter.

## Snapshot identity

Every predictor output and every settlement carries these exact fields from the
same frozen snapshot:

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

Any Champion identity mismatch produces `invalid_snapshot_mismatch` and is not
compared. A missing formal frozen Champion produces `incomplete`; no Champion
output is reconstructed for convenience.

## Market Reference v1

Only real 1X2 quotes in the snapshot are read. Each bookmaker is independently
de-vigged with reciprocal odds, and at least two bookmakers must have all three
odds strictly greater than `1`. The de-vigged home/draw/away probabilities are
median-aggregated by direction and normalized again. The file keeps each
bookmaker's de-vigged probabilities, min/max values, direction-level
dispersion, and the scalar maximum dispersion.

Market Reference reports 1X2 fair probabilities, bookmaker count, dispersion,
and the common 1X2 Brier, Log Loss, and Top-1 metrics after settlement. It only
records Asian Handicap and O/U lines and their real quotes. It does not infer a
market lambda, expected goals, BTTS probability, or score matrix.

## Simple Poisson v1

The baseline reads only recent actual goals from the frozen snapshot. It uses
the venue rows first:

```text
home_attack  = home_home goals_for / matches
away_defence = away_away goals_against / matches
away_attack  = away_away goals_for / matches
home_defence = home_home goals_against / matches

lambda_home = mean(home_attack, away_defence)
lambda_away = mean(away_attack, home_defence)
```

An unusable venue row falls back to its corresponding overall row. The fixed
numeric safety range is `0.15 <= lambda <= 4.0`. The score matrix is an
independent Poisson matrix with `rho = 0`; the baseline also emits expected
goals, 1X2, BTTS, total-goal distribution, and Top-1/3/5 scores. It does not
read any market, Champion, LLM, news, calibration, or checkpoint timeline
field.

## Prospective cohorts

`T-30M` is the pre-registered primary checkpoint. A snapshot is primary-eligible
only when the exact `T-30M` stage and trusted source/market timestamps both
exist. `T-8H`, `T-2H`, and the other registered stages are secondary diagnostics
and never replace a missing primary snapshot. Multiple checkpoints for one
match are deduplicated to one independent match sample in aggregate summaries.

Phase 1 records use `benchmark_scope=prospective`. Historical reports are not
recomputed or backfilled; any later historical analysis must be explicitly
tagged `historical_exploratory` and excluded from the formal prospective cohort.

## Immutable files and settlement

The default file layout is:

```text
data/model_benchmarks/
  predictions/<comparison_id>.json
  settlements/<comparison_id>.json
  summaries/
```

Prediction and settlement writes are create-only. Reusing an ID with identical
content is idempotent; reusing it with different content raises
`BenchmarkConflictError`. Settlement stores the 90-minute result and metrics
separately, so post-match data cannot alter a frozen prediction.

All three predictors share 1X2 Brier, Log Loss, and Top-1 accuracy. Simple
Poisson and Champion additionally share BTTS, total-goal error, expected-goal
error, exact-score Top-1/3/5, actual-score rank, and actual-score assigned
probability. Market Reference has `null` for metrics it cannot produce. ROI
and CLV remain `null` without a confirmed real transaction price.

## Synthetic smoke

`python scripts/run_baseline_synthetic_smoke.py` executes the complete flow with
`Test Home vs Test Away`: snapshot → frozen Champion fixture → both baselines →
immutable comparison → synthetic 90-minute result → separate settlement →
metrics. Every synthetic artifact has `synthetic=true` and
`excluded_from_formal_metrics=true`.

## Observation gates

The implementation contains no parameter-update path. The operating gates are
observation-only: 10 matches for a system check, 25 for data quality, 50
independent primary matches for the first statistical diagnosis, 100 for an
initial stability observation, 300 before discussing structural changes, and
500+ for league/odds/match-type slices. Results do not authorize single-match
Champion corrections or tuning.

## Verification

```bash
python -m pytest tests/test_model_baselines.py -q
python -m pytest tests/test_baseline_shadow_runner.py -q
python -m pytest tests/test_baseline_settlement.py -q
python -m pytest tests/test_baseline_synthetic_smoke.py -q
```

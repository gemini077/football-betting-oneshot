# Model benchmark storage

This directory is reserved for internal Phase 1 benchmark artifacts. It is not
read by the user-facing pages.

```text
predictions/<comparison_id>.json  # immutable pre-match comparison
settlements/<comparison_id>.json # separate post-match result and metrics
summaries/                        # aggregate diagnostics
```

The contracts are `market_reference.v1`, `simple_poisson.v1`, and
`benchmark_comparison.v1`. See
[`docs/model-governance/PHASE1_BASELINE_BENCHMARK.md`](../../docs/model-governance/PHASE1_BASELINE_BENCHMARK.md)
for the snapshot, cohort, and metric rules.

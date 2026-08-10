# Model benchmark storage

This directory is reserved for internal Phase 1 benchmark artifacts. It is not
read by the user-facing pages.

```text
predictions/<comparison_id>.json  # immutable pre-match comparison
settlements/<comparison_id>.json # separate post-match result and metrics
summaries/                        # aggregate diagnostics
production_state.json             # Phase 1 production merge boundary
health.json                       # derived internal health summary
```

The contracts are `market_reference.v1`, `simple_poisson.v1`, and
`benchmark_comparison.v1`. See
[`docs/model-governance/PHASE1_BASELINE_BENCHMARK.md`](../../docs/model-governance/PHASE1_BASELINE_BENCHMARK.md)
for the snapshot, cohort, and metric rules.

Run the read-only ledger health check with:

```bash
python scripts/benchmark_health.py
```

It reads only the benchmark prediction and settlement ledgers, writes the
derived `health.json`, and never creates predictions, settlements, or formal
samples. Formal counts require `prospective_origin=production_new_freeze`;
historical and synthetic records remain excluded.

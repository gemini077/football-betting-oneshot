# Football State Memory v1

## Current production/evidence trace

The current BASE path is:

```text
prediction_universe -> base_prediction_runner._assemble_context
  -> _nowscore_source -> nowscore_markets.fetch_match_markets
     -> parse_three_in_one / parse_analysis_data / fetch_context_bundle
  -> context.source_snapshots
  -> model_governance.build_deterministic_model_input_snapshot
  -> freeze_prediction
  -> capture_football_evidence -> data/prospective/football_evidence/{prediction_id}.json
```

The frozen Champion input remains the existing deterministic projection.  The
State Memory object is captured beside the frozen record and is not passed to
the model.  Before this change, `parse_analysis_data` retained only the eight
legacy recent-match fields; the source fixture/competition positions were
dropped.  The governance projection retains `recent_form` and the existing
`panlu` context, but intentionally drops raw recent-match rows, Nowscore page
identity, and `shuju.team_ids`.  The legacy sidecar therefore has no
historical fixture ID, competition label, kickoff, or subject perspective.

The existing 500.com fallback (`fetch_and_parse.parse_shuju`) supplies
aggregate recent-form summaries only.  It does not expose per-fixture rows,
stable fixture IDs, or per-row competition labels.  That is an explicit
readiness gap, not a reason to add a provider or infer fields.

## Contract

`schemas/football_state_memory.schema.json` defines the additive
`football_state_memory.v1` object.  Each row carries source fixture identity
when published, both source team IDs and display names, source date and
kickoff when published, non-target `home_goals_90m` / `away_goals_90m`, raw
competition label, deterministic normalized class, explicit
`is_club_friendly`, subject/opponent IDs and venue when deterministically
resolvable, and source/capture/cutoff references.  Unknown values are `null`
with an explicit status; names and scores never resolve identity or target
outcome.

The row-level provenance aliases `captured_at` and `source_record_ref` follow
the repository's existing data contracts; the explicit `source_captured_at`
and `source_reference` names remain alongside them for source clarity.

Competition normalization uses an exact versioned alias table for club and
international friendlies.  A non-empty direct source label not in that table
is a formal-competition bucket; missing or ambiguous labels remain `UNKNOWN`.

The legacy `prospective_football_evidence.v1` fields remain unchanged and are
never rewritten.  New captures add `state_memory_contract_version` and the
nested `state_memory` object.  Capture occurs only on the existing new frozen
prediction path; unchanged frozen jobs do not create a second sidecar.

## Offline current-source audit

The bounded audit reads current tracked sidecars, frozen records, and embedded
input snapshots only.  It performs exact source-ID/team-ID/date joins to the
existing Nowscore `panlu` rows, makes no network calls, and writes only the
caller-selected output path:

```powershell
python scripts/football_state_memory_readiness_audit.py --limit 200 --output state-memory-readiness.json
```

The decision is exactly one of `PROSPECTIVE_STATE_MEMORY_READY`,
`PROSPECTIVE_STATE_MEMORY_PARTIAL`, or `FAIL_CLOSED`.  The current fallback
gap keeps this milestone at `PROSPECTIVE_STATE_MEMORY_PARTIAL` until the
existing 500.com path can supply the same per-fixture contract.  Existing
historical/frozen artifacts are audit inputs only.

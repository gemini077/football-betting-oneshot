# PRED-AVAIL-2 - Provider-Independent Recent Form Backbone

Status: `READY_FOR_ACCEPTANCE`

Live validation status: `LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL`

Frozen cohort: 25 fixtures; SHA-256 `0cf4f106c34f183c3d61a81952f70e9c7f2525c0376a1e6eff74bb087e15cb8d`.

## Same frozen cohort

| Metric | BASELINE (PRED-AVAIL-1 AFTER) | AFTER |
|---|---:|---:|
| FULL prediction | 2 | 2 |
| DEGRADED | 0 | 0 |
| INSUFFICIENT_DATA | 23 | 23 |
| MISSING_RECENT_FORM | 23 | 23 |
| final prediction eligible | 2 | 2 |
| CALL_COUNT | - | 0 |
| CACHE_HIT_COUNT | - | 0 |

The BASELINE is PRED-AVAIL-1 AFTER: `FULL = 2`, `MISSING_RECENT_FORM = 23`.
With no provider credential, the adapter performed zero live requests and did not claim a coverage improvement.

## Provider route

The route uses exact UTC kickoff and a unique football-data.org fixture within the exact provider competition. It then uses only the provider fixture's stable team IDs to request FINISHED matches before the target kickoff and converts them to `home_overall`, `home_home`, `away_overall`, and `away_away`.

Provider IDs remain provider-scoped. They are not written into `canonical_team_id` and no canonical team alias is added.

## Boundaries

- No Champion math, weights, calibration, score selector, or evidence gate changed.
- No market-only production fallback, synthetic evidence, fuzzy/LLM identity, frozen rewrite, prospective mutation, or league-specific adapter.
- FotMob and SofaScore remain research-only candidates; no provider hopping was performed.
- Protected production state unchanged: `True`.

## Final verdict

`D. LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL`

PRED-AVAIL continuous development is closed after this milestone. The product remains blocked at 23/25 unavailable; the next decision is Data Supply Architecture Decision, not PRED-AVAIL-3 or another provider patch.

## Evidence

- `source_preflight_2026-08-30.json`
- `fixture_bridge_audit_2026-08-30.json`
- `provider_identity_cache_contract_2026-08-30.json`
- `availability_before_after_2026-08-30.json`
- `request_cache_accounting_2026-08-30.json`
- `no_leakage_verification_2026-08-30.json`
- `protected_state_verification_2026-08-30.json`

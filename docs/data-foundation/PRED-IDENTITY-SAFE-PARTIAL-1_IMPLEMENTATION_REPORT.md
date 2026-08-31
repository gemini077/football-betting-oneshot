# PRED-IDENTITY-SAFE-PARTIAL-1 Implementation Report

Date: 2026-08-31
PR: #139
Base: `44815a52ca35903a25cd05f30d4a8256c9d93f32`
Delivery branch: `codex/pred-identity-evidence-1`
Status: `READY_FOR_ACCEPTANCE`

## Result

Candidate B is implemented as a fail-closed fallback after the existing strict
Nowscore resolver misses. The existing stored verified binding lookup remains
first and blocks fallback when a stored binding is present. The fallback uses
only the existing deterministic identity registry and reviewed competition
identity; it does not add aliases, provider data, match-ID constants, fuzzy
threshold changes, LLM matching, or a provider change.

The fallback contract is:

1. exact kickoff equality;
2. same home/away orientation;
3. at least one confirmed deterministic fixture-side identity;
4. provider-side identity filtering through the existing registry; and
5. exactly one provider match ID after filtering.

Missing competition context, no confirmed side, opposite-orientation identity,
identity ambiguity, and multiple provider IDs all fail closed without returning
an Nowscore ID.

## Replay cohort and coverage

The replay used:

- 377 parsed rows from the current Nowscore `bf1.js` schedule;
- all 12 fixtures in `data/prediction_universe/2026-08-31.json`;
- 70 accepted historical Nowscore fetch observations;
- 15 unique historical provider match IDs.

| Measure | Result |
|---|---:|
| Strict baseline exact coverage | 8/12 |
| Candidate B newly resolved | 3/4 strict misses |
| Candidate total exact coverage | 11/12 |
| Historical wrong binding | 0 |
| Ambiguous collision | 0 |
| Orientation conflict | 0 |
| Accepted binding regression | 0 |
| Existing eight ID regression | 0/8 |
| Exact-kickoff multiple candidates silently selected | 0 |
| Durable production files changed by replay | 0 |

Current 12-fixture results:

| Fixture | Result |
|---|---|
| `500-1414254` | existing `2993771` unchanged |
| `500-1362759` | existing `2912258` unchanged |
| `500-1414155` | existing `2993766` unchanged |
| `500-1416881` | existing `2997701` unchanged |
| `500-1420346` | existing `3003860` unchanged |
| `500-1438077` | existing `3023461` unchanged |
| `500-1438078` | existing `3023462` unchanged |
| `500-1427965` | existing `3013665` unchanged |
| `500-1363834` | new deterministic fallback `2913703` |
| `500-1363823` | new deterministic fallback `2913701` |
| `500-1362753` | new deterministic fallback `2912252` |
| `500-1427969` | unresolved; no Nowscore ID returned |

The unresolved Osasuna/Getafe fixture has no reviewed competition context and
no confirmed deterministic side available through the existing identity
registry in this replay. It therefore remains unresolved; no team-ID 94/98
special case or match-specific rule was added.

The 70-observation historical replay found zero wrong bindings. Two duplicate
`2912204` observations retain a one-minute resolution-metadata kickoff drift;
page identity, provider ID, and binding invariants remain valid, so this is
reported as an evidence note and is not counted as a wrong binding.

## Verification

- `python -m pytest -q tests/test_nowscore_identity_fallback.py` ? 6 passed.
- `python -m pytest -q tests/test_nowscore_markets.py tests/test_daily_schedule_workspace.py tests/test_provider_identity_and_core_selector.py tests/test_id_auto_1_identity_registry.py` ? 35 passed.
- `python -m py_compile scripts/nowscore_markets.py scripts/daily_schedule_workspace.py` ? PASS.
- `git diff --check` ? PASS.
- Current 12-fixture intake replay ? `OK`, 11 bound, 0 ambiguous, 1 missing;
  the three new bindings and unresolved fourth target match the table above.
- Replay writes were intercepted and durable-file hashes were unchanged.

## Scope and stop state

The implementation changes only the strict resolver fallback path, its intake
call-site context, focused tests, and milestone/status evidence. Existing
production, frozen, prospective, and provider crosswalk data were not rewritten.

Status documents record PR #138 / NEXT-UNIVERSE-TRUTH-1 as
`DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`, and this milestone / PR #139
as `READY_FOR_ACCEPTANCE`. No merge is performed and no next milestone starts.

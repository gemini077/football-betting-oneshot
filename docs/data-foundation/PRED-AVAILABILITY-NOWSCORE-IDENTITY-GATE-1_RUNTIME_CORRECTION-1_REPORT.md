# PRED-AVAILABILITY-NOWSCORE-IDENTITY-GATE-1 Runtime Correction 1

Date: 2026-09-01 (Asia/Shanghai)
Status: READY_FOR_INDEPENDENT_ACCEPTANCE
Delivery branch: `codex/pred-availability-nowscore-identity-gate-1-runtime-correction-1`
PR #143 head: `a52b03550e746ec72f940be7d1e24966a376bdf3`
PR #143 merge: `fdad6502e3f38c2ffbe816bc3b0a45c64c653720`
PR #143 production run: `33496472362`
PR #143 durable main write-back: `42acad7c8c095f9f4c5cfeebdc3f619fb38e3128`

## 1. Runtime fact and bounded scope

The post-#143 production result remained 12/17 FROZEN across the two supplied
dates. PR #143 repaired `3008194`, `3008190`, `3008192`, and `3008739`, while
the post-merge unavailable cohort included `3008191`, `3008193`, `3000437`,
`3000436`, and `2995152`.

| Date | Before #143 | After #143 |
|---|---|---|
| 2026-09-01 | 6/10 FROZEN; unavailable `3008194`, `3008190`, `3008191`, `3008192` | 8/10 FROZEN; unavailable `3008191`, `3008193` |
| 2026-09-02 | 6/7 FROZEN; unavailable `3008739` | 4/7 FROZEN; unavailable `3000437`, `3000436`, `2995152` |

This correction changes only Nowscore identity-gate semantics and BASE
rejection observability. It does not research or replace a provider, add team
aliases, lower a fuzzy threshold, expand kickoff tolerance, change the 500
fetcher, change the Champion or Challenger C, change model parameters or score
selection, or rewrite frozen/prospective history.

## 2. Root-cause evidence

The high-confidence hypothesis is supported by the versioned code path:

1. The pre-#143 `scripts/nowscore_markets.py::_verified()` checked only page
   team identity/name and compatible kickoff.
2. PR #143 added `expected_provider_id=match_id` to every ordinary
   `fetch_match_markets()` verification call and rejected any parsed value that
   was not equal to the requested ID.
3. The page ID was parsed only from the optional `hide_scheduleId` HTML field;
   a missing field, parser miss, zero value, or non-integer value was reduced
   to `0`/missing and therefore became `PROVIDER_ID_MISMATCH`.
4. The new regression tests reproduce the observed failure class: valid
   ordinary names and kickoff plus an unavailable page ID return the pre-#143
   accepted result after this correction, while name, kickoff, orientation,
   provenance, and positive trusted-ID conflicts remain fail closed.

No raw current Nowscore pages for the nine supplied fixture IDs are present in
the local cache. The report therefore treats the current-fixture replay below
as deterministic/synthetic adapter replay, not live production proof. The
production run and availability counts are recorded facts supplied by the
runtime evidence; no per-ID live page content is inferred.

## 3. Correction contract

### Ordinary explicit ID

`_verified()` is restored to the pre-#143 contract: team identity/name,
kickoff, and the existing binding behavior. Page-provider ID state is recorded
but is not an ordinary hard gate. Missing, zero, and unparsable values are
classified as:

`PAGE_PROVIDER_ID_UNAVAILABLE`

### Trusted JC explicit ID

The bypass remains available only for the existing strict
`nowscore_public_jc_sales` fixture contract: verified membership, exact match
and confidence, requested/fixture/JC-evidence ID equality, complete sales/date
provenance, compatible kickoff, and orientation/ambiguity safety.

| Page provider-ID observation | Trusted-path result |
|---|---|
| Positive ID equals requested ID | Corroborating; continue if all other facts pass |
| Positive ID differs from requested ID | Fail closed: `PROVIDER_ID_MISMATCH` |
| Missing, zero, or unparsable | Record `PAGE_PROVIDER_ID_UNAVAILABLE`; do not reject on this item alone |

## 4. BASE diagnostic contract

For `IDENTITY_MISMATCH`, `BASE` persists all of the following in
`input_provenance_diagnostic`:

- Nowscore `status` and `resolution`;
- `identity_errors`;
- `identity_verification` plus flattened status/reasons;
- `trusted_jc_provenance` plus flattened reasons;
- `page_identity`;
- parsed page provider ID and `page_provider_id_availability_state`;
- `PAGE_PROVIDER_ID_UNAVAILABLE` detail when the page ID is unavailable.

This keeps exact rejection causes such as `PROVIDER_ID_MISMATCH`,
`ORIENTATION_CONFLICT`, `KICKOFF_MISMATCH`, and JC provenance failures in the
durable BASE job record rather than reducing them to a generic resolution
object.

## 5. Deterministic/synthetic current-fixture replay

The focused test uses the current Prediction Universe fixture rows from the
two local date files, a synthetic market-page identity, and a temporary cache.
It intercepts writes; no repository durable data is modified.

| Cohort | Fixture IDs | Synthetic identity | Result |
|---|---|---|---|
| 2026-09-01 current failures | `3008191`, `3008193` | translated names, page ID `0`, valid trusted JC facts | `2/2 OK` |
| 2026-09-02 current failures | `3000437`, `3000436`, `2995152` | translated names, page ID `0`, valid trusted JC facts | `3/3 OK` |
| PR #143 repaired IDs | `3008194`, `3008190`, `3008192`, `3008739` | translated names, page ID `0`, valid trusted JC facts | `4/4 OK` |
| 3008193-like ordinary regression guard | no trusted JC fixture | valid names/kickoff, page ID missing | `OK` |

The replay is a compatibility/regression proof for the gate logic only. It is
not a claim that the current raw pages were refetched.

## 6. Verification and stop state

- Focused Nowscore market, BASE provenance, trusted/untrusted-path, regression,
  and Prediction-Universe tests: `97 passed`.
- `python -m py_compile scripts/nowscore_markets.py scripts/base_prediction_runner.py scripts/prediction_universe.py`: required and passed.
- `git diff --check`: passed.
- Scope review: no Champion, Challenger C, 500 fetcher, provider, model,
  frozen-history, or prospective-history change.
- Full-suite collection remains outside this bounded scope if the existing
  unrelated `tests/test_live_ev_profile.py` import error is present.

STOP at `READY_FOR_INDEPENDENT_ACCEPTANCE`. Do not merge or start the next
blocker.

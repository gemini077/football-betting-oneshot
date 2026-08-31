# NEXT-UNIVERSE-TRUTH-1 — Sporttery / 500 Next Business-Date Universe Root-Cause Closure

Status: `ACCEPTANCE PASS / MERGE AUTHORIZED`

Decision: `NEXT-UNIVERSE-TRUTH-1 = ACCEPTANCE PASS / MERGE AUTHORIZED`

## 1. Scope and baseline

- Baseline: `origin/main=68f85b9a5b54170c222e9a88e82e16535e521b03`
- Probe branch: `codex/next-universe-truth-1`
- Production run: `33369186141`
- Target business date: `2026-09-01`
- Business timezone: `Asia/Shanghai`
- Probe policy: one direct request to each source; no retry, cache, or provider addition.

No Nowscore intake, identity mapping, Champion, lambda, selector, Challenger,
frozen history, frontend, or production prediction was changed.

## 2. Production evidence

Run `33369186141` checked out merge SHA
`2020c784d44144d3318e23f1489dc8746166e322` and ran from
`2026-08-31T15:38:07.179820+08:00` to
`2026-08-31T15:41:55.277033+08:00`.

The production cycle recorded:

| Step | Result |
|---|---|
| `next_universe` | `DEGRADED`, return code `1`, `match_count=0`, `failed_kept_previous_workspace` |
| `next_base_jobs` | `DEGRADED`, `BLOCKED_UNIVERSE`, `fixture_count=0`, `job_count=0` |
| `next_base_prediction` | `DEGRADED`, `BLOCKED_UNIVERSE` |
| cycle | `DEGRADED`, failed steps are the three rows above |

The persisted target snapshot was fetched at
`2026-08-31T07:41:13.577428+00:00` and contains `source=sporttery.cn`,
`status=FETCH_FAILED`, `fixture_count=0`, and
`last_fetch.error=FULL_SCHEDULE_FETCH_FAILED`.
The persisted target schedule payload has `status=API_FAILED`, zero matches,
and no 500 fallback provenance. It therefore records the primary failure and
the final empty outcome, but not the fallback's exact status or exception.

## 3. Bounded live probe

The live probe ran at `2026-08-31 16:03:38` Asia/Shanghai from the clean branch.
Captured response hashes are retained in the local probe capture directory
`%TEMP%\next-universe-truth-1`; the hashes below make the observations
reproducible without treating the current source response as historical
production evidence.

### A. Sporttery

URL: `https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=tycp`

| Observation | Value |
|---|---|
| HTTP status | `200` |
| Exception | none |
| HTTP 567 | `false` |
| response `success` | `true` |
| `value.matchInfoList` | present, list |
| `businessDate` set | `{2026-08-31}` |
| rows under `2026-08-31` | `12` |
| contains `2026-09-01` business date | `false` |
| target fixture count | `0` |
| response SHA-256 | `875cb3a73d258122a9cb3ce3fe2e81aaa2eae8899e3f173b2961c6e61d99e0c1` |

The 12 current API rows have `matchDate=2026-09-01` but
`businessDate=2026-08-31`. This is the existing cross-midnight sales-cycle
shape, not a target-business-date response.

### B. trade.500.com

URL: `https://trade.500.com/jczq/?playid=312&g=2`

| Observation | Value |
|---|---|
| fetch | succeeded, HTTP `200` |
| raw HTML bytes | `190373` |
| raw HTML SHA-256 | `1497b15ed679c6c90adac21fde2ee8c7f3b6d03a1fb3ac2abd66326c1e01f8bb` |
| raw `<tr>` count | `95` |
| raw match rows (`data-matchnum`) | `12` |
| rows with `data-matchdate=2026-09-01` | `12` |
| rows with `data-processdate=2026-09-01` | `0` |
| rows with `data-processdate=2026-08-31` | `12` |
| target business-date header/block | absent |
| target Tuesday business-date matches | absent |
| current parser result for target business date | `0` |

The 12 raw rows are labeled `周一001` through `周一012` and have
`data-processdate=2026-08-31`; their kickoff date is `2026-09-01`. The raw
HTML therefore contains next-natural-date kickoffs, but it does not contain a
`2026-09-01` 500 business-date section. The parser's `0` result is consistent
with the project contract that a cross-midnight kickoff remains in the prior
竞彩 business date.

### C. Raw versus parser conclusion

This is not a `500_DATE_PARSE_GAP`: raw target kickoff rows are present, but
they are correctly assigned to business date `2026-08-31`. There is no direct
parser omission of a `2026-09-01` business-date row.

## 4. Classification

```text
UNKNOWN_NOT_PROVEN
```

Evidence levels:

- **A — direct current-source evidence:** both current source observations,
  response status, date sets, raw row counts, and parser output were captured
  directly at the probe time.
- **A — direct production evidence:** run `33369186141`, its step summaries,
  and the committed `2026-09-01` snapshot establish the production outcome.
- **C — historical upstream cause:** the 15:41 source response body/status and
  the exact 500 fallback status/error were not persisted by that run. A current
  16:03 response does not backdate source publication or runner behavior to
  15:41.

The evidence proves the production symptom chain and rules out a current 500
fetch block and a current parser loss of target-business-date rows. It does
not select `SOURCE_NOT_RELEASED_AT_PROD_TIME` over a time-specific
`SPORTTERY_RUNNER_BLOCK` with the required historical certainty. The other
allowed classifications are likewise not directly established.

## 5. Deterministic engineering bug and minimal fix

The probe and production payload comparison directly confirm a separate,
low-risk provenance bug: when Sporttery fails and the 500 fallback also
returns no usable target rows, `daily_schedule_workspace.py` keeps the primary
payload and drops the fallback result's status/error. This makes a future
`NO_MATCHES_FOR_DATE`, `FETCH_FAILED`, or other fallback outcome
indistinguishable in persisted evidence.

The minimal fix adds `fallback_provenance` containing source, URL, fetch time,
requested date, success, status, parsed match count, and error. It is attached
both to a successful fallback payload and to the retained primary payload when
the fallback fails; the Prediction Universe persistence boundary now carries
the same object into `last_fetch`. Fixture selection, business-date semantics,
provider order, and failure-closed behavior are unchanged.

## 6. Verification

- Focused RED test before implementation: confirmed the missing provenance
  field in both the schedule payload and the Prediction Universe persistence
  boundary.
- Focused GREEN tests: `python -m pytest -q tests/test_daily_schedule_workspace.py`
  → `2 passed`.
- Persistence test with the repository import path: `python -m pytest -q tests/test_prediction_universe.py::PredictionUniverseTests::test_failed_refresh_persists_fallback_provenance`
  → `1 passed`.
- Related tests:
  `python -m pytest -q tests/test_daily_schedule_workspace.py tests/test_base_prediction_jobs.py tests/test_prediction_universe.py tests/test_nowscore_markets.py tests/test_automation_cycle.py`
  → `54 passed`.
- Syntax check: `python -m py_compile scripts/daily_schedule_workspace.py tests/test_daily_schedule_workspace.py`
  → passed.
- Formatting check: `git diff --check` → passed.

No production snapshot was regenerated or rewritten by the probe or fix.

## 7. STOP state

This milestone stops at `ACCEPTANCE PASS / MERGE AUTHORIZED` pending merge and the first post-merge production verification. The current product impact
remains: the historical next-business-date universe is empty, so the next
BASE jobs and next BASE prediction remain `BLOCKED_UNIVERSE`, and the recorded
cycle remains `CYCLE_DEGRADED`. The fix improves the next occurrence's
diagnostic evidence; it does not fabricate fixtures or retroactively change
the 15:41 production result.

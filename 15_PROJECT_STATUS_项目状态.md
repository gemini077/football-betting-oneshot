# 15_PROJECT_STATUS_项目状态.md

最后更新：2026-09-01
角色：项目当前唯一人类可读状态真相。只记录当前事实，不承担完整历史档案职责。

# NOWSCORE-JC-SALES-PAGE-1 - Direct JC sales-page current-universe source

Status: DEPLOYED / SEALED / PRODUCTION ACCEPTANCE READY

Decision: NOWSCORE-JC-SALES-PAGE-1 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE READY

The direct Nowscore JC sales page is now the current-universe membership and
China JC business-date authority. Its deterministic contract is selected
SelDate plus the matching niDate header date/group, the explicit
11:00--next-day-11:00 sales window, the 周XNNN match number, one Nowscore match
ID, kickoff, home/away, league, cansale, and the sales-row ID.

The paired GitHub replay for 2026-08-31 and 2026-09-01 passed with 12 and 10
rows respectively. All 22 rows are retained under their selected business
dates even though all kickoffs are on the following calendar date. Direct
business-date ID overlap, accepted-ID overlap, duplicate, and ambiguous counts
are all zero. SetLevel(3) / A[j][32] == 1 is optional corroboration only; the
2026-09-01 ten-row direct set remains accepted when live scN has none of its
IDs.

The current chain is Nowscore JC sales page -> canonical schedule / identity
-> existing Nowscore market and analysis evidence -> BASE. Sporttery and 500
no longer block current-universe creation; their independent optional evidence
roles remain. No Champion, model, identity threshold, frozen history,
prospective ledger, or settlement semantics changed.

Production closure is proven by merge SHA
30df0fb3c047e1126ed81766b5371073d61ed024, PR #141 final head
3eff9c4ea6294a1100c96209e47413dbb7a7ba41, merged at 2026-09-01T05:58:50Z,
and the first production run containing that merge SHA: runner 33475679629.
The durable write completed as main commit
7a3d431a856fb2c28e360b8e2a333c87c8277151, whose parent is the merge SHA.
The durable 2026-09-01 current source primary is
nowscore_public_jc_sales: exactly 10 fixtures, 周二001--周二010,
businessDate 2026-09-01, all kickoff calendar dates 2026-09-02, and no
previous 2026-08-31 fixture ID overlap. Prediction Universe is READY and BASE
jobs are READY with fixture_count/job_count 10/10; the four
INSUFFICIENT_DATA jobs are evidence-source outcomes, not a universe failure.
Nowscore IDs and direct business-date provenance are persisted, and the
production health state is HEALTHY.

Exact evidence and integration replay are recorded in
docs/data-foundation/NOWSCORE-JC-SALES-PAGE-1_PROBE_REPORT.md, the paired
JSON artifacts, and the production closure artifact
docs/data-foundation/NOWSCORE-JC-SALES-PAGE-1_PROD_CLOSURE_RUN_33475679629.json.
STOP at DEPLOYED / SEALED / PRODUCTION ACCEPTANCE READY; do not start
Challenger Promotion Review.

# Historical NOWSCORE-JC-BUSINESS-DATE-1 - China JC business-date anchor

Status: READY_FOR_ACCEPTANCE / NO_CODE

Decision: NO_CODE

The Nowscore public JC sales page provides a deterministic, credential-free
business-day anchor: selected SelDate plus the matching niDate header date,
with the explicit 11:00--??11:00 sales window. Match numbers are the
niDate group name plus the row number cell. This fixes the date semantics in
evidence, but does not authorize production code in this milestone.

The paired GitHub replay for 2026-08-31 and 2026-09-01 passed page/data
access and preserved the existing SetLevel(3) / A[j][32] == 1 membership
contract. It accepted 12 explicit rows for 2026-08-31, all with
2026-09-01 kickoff dates. The 2026-09-01 public page had 10 rows, all with
2026-09-02 kickoff dates, but the corresponding live sc1 replay had zero
of those ten IDs, so explicit accepted rows were zero. The full gate therefore
failed the requirement that a nonempty public current JC page have nonzero
explicit current rows.

Exact evidence is docs/data-foundation/NOWSCORE-JC-BUSINESS-DATE-1_PROBE_RUN_33470293458.json with SHA-256
186361AFCD01D884DD1B50BF901CAC54C1DC967F0D04FA3860D6B281FC6665B9; the
runner is [33470293458](https://github.com/gemini077/football-betting-oneshot/actions/runs/33470293458).
The detailed report is docs/data-foundation/NOWSCORE-JC-BUSINESS-DATE-1_PROBE_REPORT.md.

No kickoff cutoff, weekday/league/team rule, fixture-ID exception, membership
guess, Sporttery/500 change, Champion/model change, identity-threshold change,
frozen-history rewrite, prospective-ledger rewrite, or settlement change was
made. STOP at READY_FOR_ACCEPTANCE; do not merge and do not start Challenger
Promotion Review.

# Historical milestone: NOWSCORE-JC-UNIVERSE-1 - Current JC universe restoration

Status: READY_FOR_ACCEPTANCE

Decision: PASS / Nowscore public JC

The public Nowscore football schedule page and its backing `ft1.js` data
surface provide a deterministic, credential-free current JC contract:
`SetLevel(3)` selects rows where `A[j][32] == 1`. The GitHub-hosted runner
proved HTTP 200 page/data access for business date `2026-09-01`, accepted 12
current JC fixtures, and recorded duplicate Nowscore IDs `0` and ambiguous IDs
`0`. No JC membership was guessed from league, team, kickoff, odds, or another
flag.

Exact evidence is preserved in
`docs/data-foundation/NOWSCORE-JC-UNIVERSE-1_PROBE_RUN_33466072890.json` with
SHA-256 `7162B858F11F5C8117C78504AD10A13991D69038E0186D4987C2CAB0B1C71536`.
The runner is [33466072890](https://github.com/gemini077/football-betting-oneshot/actions/runs/33466072890),
from PR #141 head `c662d27c047dd0d6e6638b7c3c563fd6d22ff8f1`.

Current schedule intake now converges on Nowscore JC → canonical schedule and
identity → existing Nowscore market/analysis evidence → BASE. Sporttery and
500 no longer block the current fixture universe; their independent optional
market/corroboration and 500 deep evidence paths remain. The existing `bf1`
comparison returned 102 target-date rows with `intersection_ids=[]`; the
explicit JC page filter, not that comparison, is the membership authority.

No Champion, model, identity threshold, frozen prediction, prospective ledger,
or result-settlement semantics changed. The focused suite passed with
`90 passed, 6 warnings`; `py_compile` and `git diff --check` passed. STOP at
`READY_FOR_ACCEPTANCE`; do not merge and do not start Challenger Promotion
Review.

# Historical milestone: CURRENT-UNIVERSE-ROLLOVER-1 - Production current-day universe rollover gate

Historical status: READY_FOR_ACCEPTANCE / NO CODE

Historical decision: WAF_BLOCK / NO_CODE

The bounded one-shot probe ran on the GitHub-hosted production runner for business date 2026-09-01. The repository Sporttery calculator, both official getMatchListV1 routes, both official calculator contracts, and the current 500 trade page returned no target-date rows. Sporttery returned HTTP 567 HTML EdgeOne/WAF challenge responses; the 500 page returned HTTP 200 HTML but only an access-denied challenge with zero raw match rows.

Exact evidence is preserved in docs/data-foundation/CURRENT-UNIVERSE-ROLLOVER-1_PROBE_RUN_33455183881.json, with SHA-256 C7CE80D034630105B9DDB21083013CB48F2BF61BDF6BEC38E9226AC14FC34B03. The resulting classification is WAF_BLOCK and the decision gate is NO_CODE. No production source, request, parser, provider, model, identity, frozen prediction, or prospective ledger was changed.

The production runs 33431411824 and 33450251359 remain explained only at the upstream generation boundary: current universe count zero, BLOCKED_UNIVERSE downstream, and UPSTREAM_GENERATION_NOT_COMPLETE durability. The evidence does not prove stale endpoint contract, wrong channel or pool contract, source rollover lag, or a deterministic business-date parser bug.

# Historical milestone: PRED-INPUT-PROVENANCE-1 — Deterministic Prematch Input Provenance

Historical status: `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Historical decision: `PRED-INPUT-PROVENANCE-1 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

`HISTORICAL = PRED-INPUT-PROVENANCE-1`.

The audit against main `c0a30839867eefd83d822643e54eecc15cafec7f` and
production run `33399507542` proves a general boolean-to-umbrella
classification bug: source fetch failures could be reported as
`INPUT_TIMESTAMP_UNVERIFIED` when recent form was absent. Current durable
evidence contains two umbrella jobs (`500-1363834`, `500-1363823`) and does not
preserve enough per-fixture source state to backfill their exact historical
cause. The same run does preserve 18 500 deep page fetch failures across three
fallback attempts, but not the fixture mapping.

The implementation persists deterministic stage diagnostics for source fetch,
capture timestamp, cache/form provenance, official market timing, snapshot
construction, source cutoff, market cutoff, and other adapter failures. It
keeps prematch timing fail-closed, leaves valid frozen Champion cases
unchanged, and does not fabricate or rewrite historical timestamps.

Evidence: `docs/data-foundation/PRED-INPUT-PROVENANCE-1_IMPLEMENTATION_REPORT.md`.
Production acceptance is PASS and the milestone is DEPLOYED / SEALED. The
post-merge production verification is recorded; no next milestone starts.

# PRED-IDENTITY-SAFE-PARTIAL-1 Previous Milestone

Status: `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Decision: `PRED-IDENTITY-SAFE-PARTIAL-1 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

PR #139 = `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Closed historical milestone; current pointer is `NOWSCORE-JC-SALES-PAGE-1`.

PR #139 continues the existing identity branch and implements Candidate B as a
fail-closed fallback after the strict Nowscore resolver misses. The current
12-fixture replay preserves all eight existing IDs, adds `2913703`, `2913701`,
and `2912252`, and leaves `500-1427969` unresolved. Historical wrong binding,
ambiguous collision, orientation conflict, accepted-binding regression, and
existing-eight regression counts are all zero. Replay writes were intercepted
and durable production data was unchanged.

Evidence: `docs/data-foundation/PRED-IDENTITY-SAFE-PARTIAL-1_IMPLEMENTATION_REPORT.md`.
PR #139 merged at `ac96358b161abe35e931d873357f6fb69635c0b4`. Production Run
`33399507542` completed with durable write
`c0a30839867eefd83d822643e54eecc15cafec7f`; Nowscore binding was `11/12`.
Focused tests, `py_compile`, and `git diff --check` pass. This milestone is
deployed, sealed, and production-accepted.

# NEXT-UNIVERSE-TRUTH-1 / PR #138 Previous Milestone

Status: `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Decision: `NEXT-UNIVERSE-TRUTH-1 / PR #138 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

PR #138 merged at `db4b79793bb79c8637dbd69c0444aa4b5d8bbca6`. Its acceptance
state is retained as a closed historical milestone; the current pointer is
`PRED-IDENTITY-SAFE-PARTIAL-1`.

The bounded live probe at `2026-08-31 16:03:38` Asia/Shanghai found
Sporttery HTTP 200 with `success=true`, `matchInfoList` present, only
`businessDate=2026-08-31`, and 12 rows; `2026-09-01` was absent. The single
500.com fetch also succeeded. Its raw page had 12 rows with
`data-matchdate=2026-09-01`, but all 12 had `data-processdate=2026-08-31`
and the current business-date parser returned 0 for `2026-09-01`.

The historical upstream cause for production run `33369186141` at 15:41 is
`UNKNOWN_NOT_PROVEN`: the run persisted the primary failure but not the exact
500 fallback status/error, and a later live response does not backdate source
publication. A deterministic provenance fix adds `fallback_provenance` to the
retained schedule payload without changing fixture selection or business-date
semantics.

Evidence: `docs/data-foundation/NEXT-UNIVERSE-TRUTH-1_FINAL_REPORT.md`.
Production impact remains `next_universe=0`, `BLOCKED_UNIVERSE` for the next
BASE jobs/prediction, and `CYCLE_DEGRADED`; no fixture was fabricated and no
historical prediction was rewritten. The current pointer is
`NOWSCORE-JC-SALES-PAGE-1`.

# PRED-IDENTITY-EVIDENCE-1 Previous Bounded Gate Result

Status: `SAFETY GATE FAIL / NO CODE / STOP`

Decision: `PRED-IDENTITY-EVIDENCE-1 = SAFETY GATE FAIL / NO CODE`

A read-only replay against `origin/main` used 70 accepted Nowscore fetch
observations (15 unique provider match IDs) plus the current 12-fixture matrix.
The deterministic candidate rule resolves `500-1363834` to `2913703` and
`500-1363823` to `2913701`, while `500-1427969` has no confirmed deterministic
side. Historical wrong binding, ambiguity, orientation conflict, accepted
binding regression, and the existing eight strict-ID regression counts are all
zero; the all-three-target gate is not satisfied.

Evidence: `docs/data-foundation/PRED-IDENTITY-EVIDENCE-1_REPLAY_REPORT.md`.
No resolver, provider, alias, frozen prediction, prospective ledger, or
production data changed. The earlier gate-only task remains historical evidence; the current pointer is
`PRED-IDENTITY-SAFE-PARTIAL-1`. No next milestone is started.

# NOWSCORE-FUTURE-FIXTURE-INTAKE-1 Previous Milestone

Status: `PRODUCTION PATH PASS / MORNING TIMING NATURAL-CYCLE VERIFY PENDING`

Decision: `NOWSCORE-FUTURE-FIXTURE-INTAKE-1 = PRODUCTION PATH PASS / MORNING TIMING NATURAL-CYCLE VERIFY PENDING`

This bounded implementation keeps `bf1.js` as the live Nowscore schedule and
adds only the future `sc{offset}.js` surfaces required by the real竞彩
`matchDate` values. Offset calculation uses `Asia/Shanghai`; only offsets 1–7
are eligible. `MM-DD` rows require an explicit expected calendar date, and
source-date mismatches are rejected without guessing a year. The bf1/future
union is deduplicated by `nowscore_id` before the existing team, kickoff,
confidence, and registry path runs.

The current bounded replay used the 2026-08-31 12-fixture cohort: 438 unique
union rows, 0 duplicate IDs, 8 exact-compatible rows, and 8/8 identical known
Nowscore IDs with 0 kickoff difference and 0 wrong binding. The current sc1
response has already rolled past the cohort's early rows, so the temporal
morning claim is backed by the future-only unit path plus the current union
replay; no production registry write was made. Future fetch failures preserve
bf1 and return explicit degraded/error provenance.

Evidence: `docs/data-foundation/NOWSCORE-FUTURE-FIXTURE-INTAKE-1_FINAL_REPORT.md`.
No 500 canonical schedule, identity alias, Champion, frozen history,
prospective ledger, or the three specified identity gaps changed.

# PRED-NOWSCORE-BIND-1 Previous Milestone

Status: `SEALED / ACCEPTANCE PASS`

Decision: `PRED-NOWSCORE-BIND-1 = SEALED / ACCEPTANCE PASS`

This delivery freezes the previously completed read-only Nowscore binding
audit for business date `2026-08-31`. Current evidence is: `bf1.js`
source-present `12/12`, current resolver replay exact `8/12`, current
name-normalization gap `4/12`, current market page `12/12`, current analysis
page `12/12`, and kickoff difference `0` for all twelve rows. A deterministic
Nowscore match-ID route exists; direct `500 shujuId → Nowscore ID` mapping was
not found. Historical intake source presence is explicitly
`UNKNOWN_NOT_PROVEN` because the 753-row raw was not persisted.

Root-cause status:

```text
NOWSCORE_SCHEDULE_HORIZON_GAP = EVIDENCE-SUPPORTED PRIMARY BLOCKER CANDIDATE
```

This is not declared a `VALIDATED HISTORICAL ROOT CAUSE`. The overall audit
classification remains `MULTI_CAUSE`, with `NOWSCORE_NAME_NORMALIZATION_GAP`
as the current-feed secondary finding. The sole next remedy category is
`NOWSCORE_SCHEDULE_HORIZON_GAP`. Nowscore remains secondary market/analysis
enrichment after ID acquisition; 500 remains the provisional canonical
schedule anchor and deep fallback. No production, provider, source-order,
Champion, resolver, endpoint, alias, parser, or frozen-history state changed.

Evidence:

- `docs/data-foundation/PRED-NOWSCORE-BIND-1_ROOT_CAUSE_AUDIT.md`
- `data/football_data/pred_nowscore_bind_1/root_cause_matrix_2026-08-31.json`

# PROD-WRITE-1 Previous Milestone

Status: `SEALED / ACCEPTANCE PASS`

Decision: `PROD-WRITE-1 = SEALED / ACCEPTANCE PASS`

The validated operational risk was concurrent durable-main writing: the full
production writer and the high-frequency prematch writer used different
concurrency groups while both could modify overlapping durable paths,
including `data/fetch_runs`, `data/market_history`, `data/analysis_inputs`,
`data/analysis_reports`, and `data/match_workspace`. The full writer committed
and pushed directly; the prematch writer's pull/rebase still left a race with
another push.

The bounded protocol uses the selected B design: after generation and commit,
`scripts/durable_main_write.py` fetches `origin/main`, rebases the existing
commit, and retries only synchronization/push a bounded number of times. It
does not regenerate data or force-push. A fetch/push race may retry; a genuine
rebase conflict aborts the rebase and fails closed. The prematch Pages artifact
is rebuilt after the durable write so deployment uses the merged working tree.
Separate concurrency groups remain in place to preserve checkpoint event
semantics rather than replacing them with a pending-event queue.

Controlled scenarios cover both writer directions, non-conflicting durable
state preservation, and conflicting immutable files. Production acceptance is
separate; no Champion, Challenger, prediction, health classifier, provider,
identity, coverage, frontend, or exact-score threshold change is included.

# PROD-HEALTH-1 Previous Milestone

Status: `SEALED / ACCEPTANCE PASS`

Decision: `PROD-HEALTH-1 = SEALED / ACCEPTANCE PASS`

The bounded health fix reuses the PRED-TRUST-1 legal pre-kickoff version
selector from `scripts/prematch_versioning.py`. Health now evaluates canonical
match identity, legal immutable prematch versions, and the uniquely selected
final version instead of treating every frozen file for one job as a duplicate.
The root cause was the previous `job_id` group-length check: each later
pre-kickoff source/market refresh intentionally created another immutable
version, so legitimate version history produced `DUPLICATE_FROZEN_PREDICTION`.

The accepted production replay used `595` raw frozen rows, `219` selected
unique matches, and `590` legal prematch rows. It classified `74` legitimate
version-history groups, `0` actual duplicate-final groups, `0`
identity-collision groups, and `0` health-only groups. Production run
`33311174275` completed SUCCESS and the durable health write-back is
`00db8ef90d7dade591268ef8810bb4f8da3a9045`; health is `HEALTHY` with no
active reason. No frozen artifact, prospective ledger, Champion, model, or
exact-score threshold was changed. The `87.5%` exact-score threshold remains
an explicit debt outside this milestone.

Focused tests cover legitimate v1/v2/v3 history, ambiguous final versions,
identity collision, one legal prediction, frozen integrity, and preservation
of unrelated health reasons. Production acceptance is verified separately by
the merged `Refresh data and deploy Pages` workflow; any other real health
reason must remain `ALERT`.

Evidence: `scripts/production_health_watch.py`,
`tests/test_production_health_watch.py`, and the production workflow result.

# MARKET-SIDE-SHADOW-1 Previous Milestone

Status: `DEPLOYED / SEALED / ACCEPTANCE PASS`

Decision: `MARKET-SIDE-SHADOW-1 = DEPLOYED / SEALED / ACCEPTANCE PASS`

The accepted PRED-TRUST-3 Challenger C is wired as a background-only paired
shadow. The runner captures Champion and C from the same frozen fixture,
source cutoff, freeze-eligibility contract, and frozen input digest. A paired
capture is `PAIRED`; a C failure is `CHALLENGER_ABSTAIN` and preserves the
Champion. The independent challenger namespace is
`market_side_shadow_1/market_side_only_hybrid`.

The C output contains both lambdas, 1X2 probabilities, a complete 13x13 score
distribution, Top1/Top3, BTTS, O/U 2.5, and total-goal tails `>=4`, `>=5`, and
`>=6`. The evaluation contract is separate from capture, includes BTTS ECE,
Brier, LogLoss, and five-bin reliability rows, and has automatic 50-match
`CHECKPOINT` and 100-match `PROMOTION_REVIEW_READY` states. Neither state
promotes C. The first 30 verified pairs expose early-stop integrity/proper
metric sentinels.

Smoke evidence used one existing PRED-TRUST-2 pinned record only: pair status
`PAIRED`, C score matrix `169` rows, verified paired sample `0`, checkpoint
`NOT_REACHED`. It is recorded in
`data/prediction_quality/market_side_shadow_1/smoke_2026-08-30.json` and the
immutable pair directory. Champion, formal prospective evaluation, and
production output remain unchanged; no future sample waiting occurred.

The bounded closure now also refreshes evaluation automatically from the
existing verified 90-minute artifacts under
`data/postmatch_automation/results/*.json`. The closure smoke matched the
existing pair to one verified result and atomically persisted
`data/prediction_quality/market_side_shadow_1/latest.json`. The pair is an
engineering smoke pair with `promotion_eligible=false`: total pairs `1`, paired
`1`, promotion-eligible pairs `0`, excluded non-promotion pairs `1`, verified
promotion sample `0`, checkpoint `NOT_REACHED`, and `auto_promote=false`.
The production runner passes explicit automatic-capture context; only a
pre-kickoff pair that also passes the formal eligibility and identity/freeze
checks may enter the promotion cohort. The refresh is an optional cycle step
and records `DEGRADED` plus an error if the research step fails.

Evidence: `scripts/market_side_shadow.py`,
`tests/test_market_side_shadow.py`,
`docs/prediction-quality/MARKET-SIDE-SHADOW-1_FINAL_REPORT.md`.

# PRED-TRUST-3 Current State

Status: `SEALED / ACCEPTANCE PASS`

Decision: `MARKET_SIDE_FUSION_PROMISING_FOR_SHADOW`

The original one-shot replay artifact remains unchanged and retains its
original machine conclusion `MARKET_SIDE_ONLY_NOT_SUFFICIENT`. Independent
acceptance recorded `PRED-TRUST-3 = ACCEPTANCE PASS` and overrode the strict
offline product veto because BTTS accuracy was maintained and BTTS Brier
improved; the five-bin BTTS ECE increase remains a `SHADOW_WATCH_RISK`, not a
standalone rejection of bounded shadow.

The replay used the accepted pins: production run `33294381128`, accepted
write-back commit `73994d32fc148da49295a5bfef2e1e42e042a22e`, `217` unique
final legal prematch matches, and `181` verified 90-minute results. Challenger
C kept the Champion total, replaced only the frozen market side-share, retained
the 1X2 improvement, restored the Champion BTTS/O-U/right-tail behavior, and
reduced 1-1 Top1 to `54.84%`. No replay artifact was rewritten.

PR #127 was independently closed at merge commit
`c4a128826e4380ead2bea4ac10453b03cd849a28`. The next sole milestone is the
background-only `MARKET-SIDE-SHADOW-1`; no Champion or production promotion is
implied.

Evidence: `data/prediction_quality/pred_trust_3/replay_2026-08-30.json`,
`docs/prediction-quality/PRED-TRUST-3_FINAL_REPORT.md`, and the PR #127
governance closeout.

# PRED-TRUST-2 Current State

Status: `SEALED / ACCEPTANCE PASS`

Decision: `NO_CHALLENGER_BEATS_CHAMPION`

The single bounded offline replay used the PRED-TRUST-1 pinned evidence only:
accepted production run `33294381128`, accepted write-back commit
`73994d32fc148da49295a5bfef2e1e42e042a22e`, `217` unique final legal
prematch matches, and `181` verified 90-minute results. The current raw tree
contains the pinned records by ID and content hash; automatic generated-data
refreshes did not change the replay cohort.

The comparison was exactly Champion plus two pre-registered deterministic
challengers. Challenger A (recent-form strength separation) worsened 1X2 and
exact-score metrics and did not separate lambda gaps. Challenger B
(market-to-goal separation) improved 1X2 and concentration, but worsened BTTS,
O/U 2.5, and right-tail probability error; its exact Top1 also fell from
`11.60%` to `10.50%`. Neither challenger satisfies the pre-registered
multi-signal gate. The strongest concentration result was Challenger B:
1-1 Top1 `49.31%` vs Champion `76.50%`, with lambda gap `<0.5`
`49.31%` vs `66.36%`; its mean `P(total>=4)` was `29.20%` vs the actual
verified `41.44%`.

No Champion, production, shadow, frozen prediction, prospective ledger,
health monitor, health gate, provider, or frontend change was made. PRED-TRUST-2
was independently accepted and sealed after PR #126 was merged at
`81d70ad263d58d067237b88b0c332c284345518d`. PRED-TRUST-3 is recorded above as
the current bounded research milestone.

Evidence: `data/prediction_quality/pred_trust_2/pinned_cohort_manifest.json`,
`data/prediction_quality/pred_trust_2/replay_2026-08-30.json`, and
`docs/prediction-quality/PRED-TRUST-2_FINAL_REPORT.md`.

# DATA-PLANE-2 Current State

Status: `SEALED / DEPLOYED / ACCEPTANCE PASS`

PR #123 was merged into `main` at
`8e432d84f5c4d68bd25fb32fb31c3d55a7b6e651` after PR #122 had been safely
merged. PR #120 remains OPEN and unmerged. The latest automatic prediction,
market, prospective, frozen, dashboard, and runtime state was retained.

Production workflow run `33294381128` completed SUCCESS on the GitHub-hosted
Ubuntu runner. Bootstrap was READY with runtime snapshot
`snapshot-20260830T044503Z-48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`,
record count `1778`, and dataset SHA-256
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`.
The verified artifact SHA-256 is
`dcec59f3e4af9217b5b82858d662b0ae59b150d358d102905e238541b5f07232`.
Evidence: `https://github.com/gemini077/football-betting-oneshot/actions/runs/33294381128`.
The current `origin/main` write-back commit is
`73994d32fc148da49295a5bfef2e1e42e042a22e`.

Production workflow steps passed: Run production cycle, durability gate,
cross-market consistency, public-data write-back, and Pages deployment. The
production health evaluation returned `ALERT` with the explicit product
warning `DUPLICATE_FROZEN_PREDICTION`; its `runtime_data_snapshot` remained
`READY` with the same count/digest. This is a product warning, not a
data-plane parity failure.

Dashboard availability changed from BEFORE `25 fixtures / 1 FROZEN / 24
INSUFFICIENT_DATA` to AFTER `25 fixtures / 22 FROZEN / 3 INSUFFICIENT_DATA`,
with `prediction_failed=0`. AFTER reasons are
`MISSING_RECENT_FORM=1`, `INPUT_TIMESTAMP_UNVERIFIED=2`,
`IDENTITY_UNAVAILABLE=0`, and `SOURCE_UNAVAILABLE=0`.
Current daily prediction availability is `PARTIAL` (22/25 usable, not
`SEVERELY_BLOCKED`).

Twenty-one fixtures moved from insufficient data to FROZEN:
`500-1358632`, `500-1362439`, `500-1362752`, `500-1364199`, `500-1373246`,
`500-1414156`, `500-1414196`, `500-1414245`, `500-1415091`, `500-1415092`,
`500-1415895`, `500-1415897`, `500-1415901`, `500-1420362`, `500-1420368`,
`500-1420369`, `500-1427964`, `500-1427973`, `500-1428454`, `500-1430629`,
`500-1438080`. Production model input snapshots report `form_source=nowscore`
for all 21, so the current evidence attributes `0` fixtures solely to the
1778-row snapshot. The separate clean-runner probe `500-1364199` verified
`authoritative_historical_results` directly.

The provider-neutral contract remains recorded in
`docs/data-foundation/DATA-PLANE-2_PRIVATE_SNAPSHOT_BOOTSTRAP_CONTRACT.md`.
Publisher live validation remains `DEFERRED / NON_BLOCKING`; initial
provisioning was `MANUAL_PRIVATE_UPLOAD`.
Licensing review remains `LICENSING_REVIEW_REQUIRED`.

Log-hygiene follow-up: `NON_SECRET_LOG_HYGIENE_DEBT`. The production run's Bootstrap step environment
metadata exposed the configured endpoint/bucket/region values in the GitHub
log. No such values are repeated here; the runtime access key and secret were
masked. This does not change the verified data-plane parity, but it remains an
open security-acceptance item before the log-hygiene requirement is closed.

# PRED-TRUST-1 Current State

Status: `SEALED / ACCEPTANCE PASS`

The read-only audit is pinned to accepted production write-back commit
`73994d32fc148da49295a5bfef2e1e42e042a22e` and run `33294381128`. It selects
one final legal prematch version per unique match without deleting frozen
files or rewriting the prospective ledger. The current 2026-08-30 cohort is
`22` unique frozen matches; the historical/prospective legal cohort is `217`
unique matches.

The health duplicate warning contains `51` groups affecting `51` matches:
`A=51` legitimate immutable version histories, `B=0` actual duplicate finals,
`C=0` identity collisions, and `D=0` health-only groups without a second legal
prematch candidate. There is no real immutable/frozen integrity violation;
the existing duplicate warning is a bounded health false positive under the
canonical evaluation view. The monitor is not changed in this milestone.

On the unique cohort, exact-score Top1 `1-1` is `16/22 = 72.73%` today and
`166/217 = 76.50%` historically. `abs(lambda_home-lambda_away) < 0.5` is
`14/22 = 63.64%` today and `144/217 = 66.36%` historically. The stored Top1
equals the independent Poisson joint MAP for `217/217` comparable matches.
Verified 90-minute prospective evaluation has sample size `181`: 1X2
accuracy `51.93%`, exact-score Top1 hit `11.60%`, Top3 hit `28.73%`, BTTS
accuracy `60.22%`, and O/U 2.5 accuracy `62.43%`.

The product conclusion is `MIXED`: P0 lambda generation, P1 product
presentation, and P2 market-fusion evidence. The legacy `87.5%` exact-score
gate is unchanged; the audit recommendation is `REPLACE_WITH_MULTI_SIGNAL`.
PRED-TRUST-1 was independently accepted and sealed after PR #125 was merged
at `1ec57af0b4bae7ca15cd41e2cdf4e578a21f7d89`. PRED-TRUST-2 is recorded above
as the current bounded research milestone. No model, Champion, frozen
prediction, provider, identity, or presentation implementation starts from
the accepted audit.

# DATA-PLANE-1 Current State

Status: `SEALED / ACCEPTANCE PASS`

`DATA-PLANE-1 — Cloud Production Football Data Architecture Decision` selects
`B. PRIVATE_SNAPSHOT_STORE`. The decision is vendor-neutral and does not
provision R2/S3, Supabase, another database, or a repository runtime dataset.
The implementation milestone is intentionally separate and has not started.

The clean-runner classification is `PARTIALLY_REPRODUCIBLE`: the latest checked
`origin/main` (`9d792b35275045d7e62a02d2edd949b2b253686e`) deterministically
rebuilds only 206 historical rows with digest
`0a1183aa11ae3c27c8b2081cae2f8776dfc50fbb35371ef48374e6f798d01a74`, not the
authoritative local 1778 rows with digest
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`.
Tracked manifests are provenance and rebuild instructions; they do not carry
the missing raw third-party captures.

A clean temporary source-rebuild proof used the approved Norway capture and
the tracked exact identity registry to produce a versioned temporary DuckDB;
`500-1364199` returned `authoritative_historical_results` recent form with 10
records before kickoff. This proves the candidate path, not full 1778-row
reproducibility or deployment.

The production bootstrap contract is recorded in
`docs/data-foundation/DATA-PLANE-1_CLOUD_PRODUCTION_DATA_ARCHITECTURE.md`:
download the exact private snapshot, verify artifact/logical digest and count,
atomically install it under `FOOTBALL_DATA_HOME`, and read it read-only. Source
refresh remains off the prediction critical path. No Champion, frozen,
prospective, dashboard, runtime, provider or model state changed.

Independent acceptance recorded the authoritative dataset as 1,778 rows with
dataset SHA-256
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`, and the
clean-runner classification as `PARTIALLY_REPRODUCIBLE`. The clean Norway proof
made `500-1364199` Bodo/Glimt - Rosenborg pass
`authoritative_historical_results` with 10 recent-form records before kickoff.
PR #121 was safely merged to `main` at
`963f36e7d00e16560fbdcd571dc20415437afa2b`; PR #120 remains OPEN and
unmerged. The architecture decision remains `B. PRIVATE_SNAPSHOT_STORE`.

# PRED-AVAIL-1 Current State

Status: `READY_FOR_ACCEPTANCE`

The exact 2026-08-30 cohort is frozen at 25 fixtures with cohort SHA-256
`0cf4f106c34f183c3d61a81952f70e9c7f2525c0376a1e6eff74bb087e15cb8d`.
BEFORE: 1 FULL/frozen, 24 `MISSING_RECENT_FORM`, 0 prediction failures, and 0
blocked Champion jobs. The isolated same-cohort AFTER replay is 2 FULL, 0
DEGRADED, 23 `INSUFFICIENT_DATA` / `MISSING_RECENT_FORM`, 0 prediction failures,
and 0 blocked Champion jobs. Identity-blocked remains 23, source-blocked moves
24 -> 23, and history-blocked remains 23.

The generic fix routes exact, eligible pre-kickoff rows from the existing
read-only authoritative historical-result store into the existing four-block
recent-form contract. It releases only `500-1364199` Bodo/Glimt - Rosenborg in
bounded replay. The existing frozen Celta Vigo - Athletic Club artifact was not
rerun. Production automatic prediction, market, prospective, dashboard and
runtime files are unchanged; AFTER is not a live deployment claim.

Root cause evidence is retained in
`data/football_data/pred_avail_1/root_cause_audit_2026-08-30.json`. The common
system cause is that BASE previously did not route the authoritative store;
current runtime 500 deep fetches are unavailable and the Nowscore schedule has
no exact mapping for this 500 fixture cohort. The 23 remaining rows are
identity-blocked under the exact-only policy. No synthetic evidence, fuzzy or
LLM identity, league-specific patch, new provider, market-only fallback, or
Champion math change was introduced.

`HC-AUTO-1 = SEALED / ACCEPTANCE PASS` and `ID-AUTO-1 = SEALED / ACCEPTANCE PASS`
are recorded after independent acceptance. PR #118 was safely merged to
`main` at `04a548416513865e4af4771603fb4369074ecd57`, with the latest automatic
state preserved. `IDENTITY_BACKLOG = NON_BLOCKING / ON_DEMAND`; ID-AUTO-2 is not
started.

The next pointer after independent acceptance is Multi-Market Prediction
Quality. No model-tuning task is started in PRED-AVAIL-1.

# ID-AUTO-1 Acceptance Record (historical)

Status: `SEALED / ACCEPTANCE PASS`

HC-AUTO-1 is now `SEALED / ACCEPTANCE PASS` after independent acceptance. PR
#117 was merged to `main` at
`7680c57475c907ba87cf40c9c1a3d1d48543edb1` without reverting the latest
automatic prediction-universe, BASE-ledger, market/fetch, prospective, frozen,
dashboard, or runtime state.

ID-AUTO-1 adds a league-agnostic deterministic team identity registry and
resolver. The registry consolidates existing provider IDs, reviewed
crosswalks, canonical historical IDs, source names, and reviewed aliases. It
uses the five-level exact ladder and keeps ambiguous/unresolved identity
fail-closed for the historical challenger. No league-specific resolver,
fuzzy match, new provider, Champion change, frozen mutation, or history-store
mutation was introduced.

The real 2026-08-29 through 2026-08-31 Prediction Universe audit covers 66
fixtures in one batch. BEFORE ID-AUTO-1: 1 `SUPPORTED`, 65 `UNSUPPORTED`, and
0 blocked Champion jobs. AFTER: 2 `SUPPORTED`, 0 `DEGRADED`, 64 `UNSUPPORTED`,
11 resolved sides across 2 fully resolved and 7 partial fixtures, and 0 blocked
Champion jobs. The remaining 57 fully unresolved fixtures and 7 partial rows
are recorded in the deterministic backlog.

`FE-SE-HIST-1` is `SEALED / ACCEPTANCE PASS` after PR #115 was merged to main. Its authoritative Sweden closure remains 2025=240, 2026=119, Sweden=359, global historical=1778, unresolved=0, duplicate/conflict=0, and connected 2025 network=true.

`FE-SE-DC-CLOSE` replays the exact FE-DC-1 103 target IDs with the frozen configuration against old 1554-row history and new 1778-row history. Target reconciliation is exact for 103/103. Complete-history replay has 7 model-specific fixed-optimizer fit failures, leaving 96 targets with both models; no tuning or fallback was applied. Final research verdict: `INCONCLUSIVE` because this is an explicit evaluation-integrity blocker, not a reason to change parameters.

`SWEDEN_SPECIFIC_FURTHER_TUNING` is `CLOSED`. PR #114 remains OPEN and unmerged. Champion `recent_form_market_calibrated_poisson_v2`, production prediction, frozen prediction, and user prediction surface are unchanged.

`FE-SE-DC-CLOSE` is `ACCEPTANCE PASS / CLOSED`; its model verdict remains
`INCONCLUSIVE` solely because 7 of the original 103 fixed-config targets had
optimizer fit failures. `SWEDEN_SPECIFIC_FURTHER_TUNING` is `CLOSED`, PR #114
remains OPEN and unmerged, and no Sweden/DC computation was run in HC-AUTO-1.

ID-AUTO-1 is an accepted historical milestone: `SEALED / ACCEPTANCE PASS`.
Do not start ID-AUTO-2 automatically; the identity backlog is
`NON_BLOCKING / ON_DEMAND`.

# FE-SE-HIST-1 Acceptance Record

`FE-SE-HIST-1` = `SEALED / ACCEPTANCE PASS`

PR #115 was merged without reverting the intervening automatic market/data refresh commits. The closure audit, manifest, normalized sample, deterministic identity evidence, focused tests, and authoritative digest are retained in main. FE-SE-HIST-1 is now historical governance evidence, not the active Sweden execution pointer.
# 1. 当前生产状态

- 本地项目：`D:\MyProject\football-betting-oneshot-main`
- GitHub：`gemini077/football-betting-oneshot`
- 生产自动化：已运行
- GitHub Pages：已运行
- 足球业务时区：Asia/Shanghai
- 当前正式 Champion：`recent_form_market_calibrated_poisson_v2`
- CA-1 高级当前分析层：PAUSED

# 2. 已完成 / 已封版

## Production Foundation

- Prediction Universe：SEALED
- BASE Job / eligibility / freeze：SEALED
- Verified 90m result settlement：SEALED
- Prospective ledger：SEALED
- Production automation：SEALED
- Production health：SEALED
- P0 Workspace Auto-Update Recovery：SEALED / DEPLOYED

P0 已验证：

- New Dashboard 自动更新；
- Match Workspace 自动更新；
- Core 读取当天 workspace；
- freshness health guard；
- static page version polling / reload；
- GitHub durable state 与 Pages 实际日期一致。

## Frontend

- Slice 1A Homepage：SEALED
- Slice 1B Match Detail Infrastructure：DONE
- R2.1 terminology/timezone cleanup：DONE
- Legacy Mapper：DONE / HISTORICAL COMPATIBILITY ONLY

## Prediction Integrity

- PA-1 Prediction Sanity & Score Collapse Audit：SEALED
- PA-1-R1 Scenario Replay & Metric Integrity：SEALED
- PA-2 Opponent-Adjusted Strength Challenger：HISTORICAL RESEARCH VALID / OVERALL INCOMPLETE

# 3. 当前最重要问题

## 3.1 Exact-score collapse

2026-08-15 production snapshot：

- FROZEN：23
- unique_score = 1-1：21/23 = 91.30%
- 1X2 leader：HOME 12 / AWAY 11 / DRAW 0
- 两边 lambda 同时落在 1–2：21/23
- `abs(lambda_home-lambda_away) < 0.5`：16/23

结论：

`CURRENT_SELECTOR = FAIL`

问题不是随机填值，而是：

`Selector Collapse + Underlying Lambda Compression`

## 3.2 现有 selector 替代方案未通过

Formal prospective 14 场：

| 方法 | Exact Top1 | 比分派生1X2 | Selected Total Goals MAE |
|---|---:|---:|---:|
| Current Matrix MAP | 14.29% | 42.86% | 1.714 |
| Outcome-conditioned | 0% | 28.57% | 1.643 |
| Existing Scenario Challenger | 0% | 28.57% | 1.357 |

因此：

- 不直接切 Outcome-conditioned；
- 不直接切 Scenario Challenger；
- 不用“减少1-1”作为成功目标。

## 3.3 当前 production calibration 状态

当前已审计 calibration artifact：

- `status = shadow_only`
- `active = false`
- direction approved = false
- total goals approved = false
- dispersion approved = false

当前 production Dixon-Coles 调用中 `rho = 0.0`。

因此当前模型名中的 `calibrated` 不能被产品端理解成“已成熟校准”。

# 4. PA-2 Historical Challenger 状态

Research model：

`opponent_adjusted_strength_poisson_v1`

已审计历史结果：

- 1,778 场（FE-SE-HIST-1 closure 后）；
- 时间范围：2025-02-22 → 2026-08-03；
- 主要覆盖：葡超、挪超、巴甲、芬超、美职联、瑞典超级/次级等有限赛事体系。

Historical holdout：

- total ≈ 314；
- challenger available ≈ 308；
- Football-only Brier ≈ 0.641651；
- Football-only LogLoss ≈ 1.068304；
- Uniform Brier ≈ 0.666667；
- Uniform LogLoss ≈ 1.098612。

说明 opponent-adjusted strength 路线值得继续研究。

但：

- historical predicted Top1 1-1 ≈ 42.21%；
- historical actual 1-1 ≈ 13.31%。

因此 Challenger 仍未解决比分集中问题。

# 5. PA-2-R1 当前 blocker 与 ID2 状态

PA-2-R1 的 DATA / ID / COV-SRC / ID2 证据已真实生成并完成核验。ID2 evidence package/status 为 `READY_FOR_ACCEPTANCE / INDEPENDENT ACCEPTANCE PENDING`；PA-2-R1 model program overall 仍为 `OVERALL INCOMPLETE / TOO_SMALL_FOR_DECISION`，原因是 formal paired sample 只有 1。

ID2 的正式 cohort 语义为 `formal eligible = 9`，另有 `excluded pilot = 5`。历史文档中的 `Formal 14` 只保留为旧 cohort label，不能继续作为当前执行分母。

正式 eligible=9 的 deterministic bridge 结果：

- `AVAILABLE = 1`；
- `COMPETITION_UNSUPPORTED = 6`；
- `HISTORY_UNAVAILABLE = 1`；
- `IDENTITY_UNAVAILABLE = 1`；
- `paired = 1`，且所有 paired methods 使用同一 match ID。

Hearts–Benfica 两队 identity 已由官方 fixture/球队证据 deterministic solved，但 Europa history 仅满足 2/5 的目标 prior 门槛；Elfsborg 仍为 `IDENTITY_UNAVAILABLE`。这两项不能被写成已 paired。

FE-SE-HIST-1 and FE-SE-DC-CLOSE are historical closure records; HC-AUTO-1 is the active execution pointer.

必须区分：

1. Identity Coverage：能否确定 production 球队对应哪个 canonical team；
2. Historical Strength Coverage：即使知道是谁，历史数据库是否有足够 prior matches。

历史库赛事覆盖有限，因此“补 ID”并不等于当前全部比赛都能进入 challenger。

# 6. 上一研究阶段

`Phase PA-2-R1 — Canonical Identity & Paired Challenger Evaluation`

状态：`HISTORICAL RESEARCH / OVERALL INCOMPLETE / TOO_SMALL_FOR_DECISION`

ID2 evidence package/status：`READY_FOR_ACCEPTANCE / INDEPENDENT ACCEPTANCE PENDING`

FE-SE-HIST-1 是当前已完成、等待独立验收的 bounded closure；PA-2-R1 ID2/PR #114 证据保留为历史研究记录。

目标：

把能安全 deterministic mapping 的 production / formal fixtures 接到 historical strength challenger，在完全相同比赛子集上公平比较 Current、Challenger、Market-only、Uniform。

Champion 保持不变：`recent_form_market_calibrated_poisson_v2`。Challenger 仍为 shadow-only；CA-1 保持 paused；PA-3 尚未开始。

# 7. 当前暂停

`CA-1 — Current Constrained Analysis Layer`

状态：

`BLOCKED / PAUSED`

暂停原因：

当前 prediction baseline 尚未达到值得建设高级解释层的质量。禁止用高级文本分析包装已知存在结构性问题的比分 headline。

# 8. 当前禁止事项

- 不修改 production Champion；
- 不重写 frozen predictions；
- 不回填赛后数据到赛前模型；
- 不启用 Scenario Challenger；
- 不强制比分服从 1X2；
- 不人工减少 1-1；
- 不重新扩 Legacy Mapper；
- 不开始 CA-1；
- 不在 PA-2-R1 中一口气扩全世界历史联赛；
- 不使用 fuzzy / LLM / 人工猜测 identity mapping；
- 不使用旧 `Formal 14` label 调 Challenger 参数；当前 formal 分母使用 `formal eligible=9`，且仍不得用于参数选择；
- 不把 workflow success 当作部署完成证据。

# 9. Prospective / Promotion 治理

当前约束：

- 新 Challenger 先 shadow；
- 约 40–50 新 prospective 样本后，才进入严肃 challenger review；
- 约 100 或更多成熟样本后，才考虑 Champion promotion；
- promotion 必须综合历史 holdout、prospective、Market-only 和当前 Champion；
- 不因短期连胜或单场表现直接换 Champion。

# 10. 交付治理

正式验收文件统一：

`D:\MyProject\_deliveries\football-betting-oneshot\`

仓库内不新增新的 handoff / delivery / evidence ZIP。

历史 `artifacts/*handoff.zip` 是遗留治理债，暂不在当前阶段删除。

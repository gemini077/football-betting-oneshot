# 17_NEXT_WORK_后续工作.md

最后更新：2026-09-01

# Current Sole Pointer

# CURRENT-UNIVERSE-ROLLOVER-1 - Sole current execution pointer

Status: READY_FOR_ACCEPTANCE / NO CODE

Decision: WAF_BLOCK / NO_CODE

Scope closed in this milestone: bounded GitHub-runner probes for the repository Sporttery endpoint, official getMatchListV1 routes, official calculator channel/pool contracts, and the current 500 trade page for 2026-09-01. All observed production surfaces were blocked or challenged and returned zero target rows. Preserve the exact artifact, do not inject fixtures, do not add a third-party provider, and do not modify the production Champion or downstream model work.

Next required action is independent acceptance of the evidence gate. If a later run obtains a valid same-provider response, open a new bounded source/request/parser investigation rather than silently changing this result.

# Historical pointer: PRED-INPUT-PROVENANCE-1 — Deterministic Prematch Input Provenance

Historical status: `ACCEPTANCE PASS / MERGE AUTHORIZED`

Historical decision: `PRED-INPUT-PROVENANCE-1 = ACCEPTANCE PASS / MERGE AUTHORIZED`

`HISTORICAL = PRED-INPUT-PROVENANCE-1`.

The bounded audit found a general source-fetch-to-timestamp umbrella bug in
the BASE runner. The current two target jobs remain historically
`UNPROVEN_FROM_DURABLE_EVIDENCE`: their stored records have no per-fixture
Nowscore result or source-stage trace. Production run `33399507542` proves 18
500 deep page fetch failures across three fallback attempts, but its log does
not map those attempts to fixture IDs.

The rule-based implementation writes `input_provenance_diagnostic` and
`input_provenance_failure_stages`, distinguishes source fetch failure from
timestamp failure, and remains fail-closed for every unproven prematch input.
No current two-fixture eligibility change, timestamp fabrication, frozen
prediction rewrite, or Champion change is part of this milestone.

Evidence: `docs/data-foundation/PRED-INPUT-PROVENANCE-1_IMPLEMENTATION_REPORT.md`.
Engineering acceptance is PASS and merge is authorized. Real production
verification follows merge; do not start a next milestone.

# Previous milestone: PRED-IDENTITY-SAFE-PARTIAL-1 - Deterministic Nowscore Fallback

Status: `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Decision: `PRED-IDENTITY-SAFE-PARTIAL-1 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

PR #139 = `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Closed historical milestone; current pointer is `PRED-INPUT-PROVENANCE-1`.

PR #139 is the current bounded implementation milestone. Candidate B runs
only after a strict resolver miss and binds only after exact kickoff, same
orientation, one confirmed deterministic side, and a unique provider match ID.
The current 12-fixture replay keeps the existing eight IDs unchanged, adds
`2913703`, `2913701`, and `2912252`, and keeps `500-1427969` unresolved.
Historical wrong binding, ambiguous collision, orientation conflict,
accepted-binding regression, and existing-eight regression are all zero.

Evidence: `docs/data-foundation/PRED-IDENTITY-SAFE-PARTIAL-1_IMPLEMENTATION_REPORT.md`.
PR #139 merged at `ac96358b161abe35e931d873357f6fb69635c0b4`. Production Run
`33399507542` completed with durable write
`c0a30839867eefd83d822643e54eecc15cafec7f`; Nowscore binding was `11/12`.
Focused tests, `py_compile`, and `git diff --check` pass. This milestone is
deployed, sealed, and production-accepted.

# Previous milestone: NEXT-UNIVERSE-TRUTH-1 / PR #138

Status: `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Decision: `NEXT-UNIVERSE-TRUTH-1 / PR #138 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

PR #138 merged at `db4b79793bb79c8637dbd69c0444aa4b5d8bbca6`. The previous
production-universe milestone remains closed and is not reopened.

The bounded probe found current Sporttery HTTP 200 with only
`businessDate=2026-08-31` and 12 rows. The single current 500 fetch succeeded;
its raw page contained 12 next-natural-date kickoff rows, all marked
`data-processdate=2026-08-31`, and the current parser correctly returned 0 for
target business date `2026-09-01`. The exact 15:41 upstream cause remains
`UNKNOWN_NOT_PROVEN` because the production run did not persist the fallback
status/error and current source truth is not historical proof.

The smallest deterministic fix preserves `fallback_provenance` when the
primary source fails and the 500 fallback is unsuccessful. Focused and related
tests pass. No fixture, provider, Nowscore intake, model, Champion, frozen
history, or frontend state changed.

Evidence: `docs/data-foundation/NEXT-UNIVERSE-TRUTH-1_FINAL_REPORT.md`.
STOP after independent acceptance and remote delivery; do not start another
next-universe, provider, identity, model, or frontend milestone.

# Previous milestone: PRED-IDENTITY-EVIDENCE-1 Bounded Gate Result

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
production data changed. The current pointer is `PRED-IDENTITY-SAFE-PARTIAL-1`; no next milestone is
started.

# Previous milestone: NOWSCORE-FUTURE-FIXTURE-INTAKE-1 - Future Fixture Intake

Status: `PRODUCTION PATH PASS / MORNING TIMING NATURAL-CYCLE VERIFY PENDING`

Decision: `NOWSCORE-FUTURE-FIXTURE-INTAKE-1 = PRODUCTION PATH PASS / MORNING TIMING NATURAL-CYCLE VERIFY PENDING`

The implementation keeps `bf1.js` as the live schedule and augments it only
with the required `sc1`–`sc7` future surface derived from real竞彩
`matchDate` values. It uses Shanghai-date offset arithmetic, strict
`expected_date` handling for `MM-DD`, source-date rejection, ID dedupe, and
explicit degraded/error provenance while preserving the existing exact
resolver, verification gate, registry persistence, and bf1 fallback.

The bounded 2026-08-31 replay resolved 8 exact-compatible fixtures to the same
known Nowscore IDs with no wrong binding. The three specified identity gaps
remain out of scope. Current sc1 early rows have rolled with the live feed, so
independent acceptance should verify the temporal morning behavior using the
future-only focused path and the recorded probe/replay evidence.

Evidence: `docs/data-foundation/NOWSCORE-FUTURE-FIXTURE-INTAKE-1_FINAL_REPORT.md`.
STOP after independent acceptance; do not start identity, provider, source
migration, Champion, frontend, or next-universe work from this pointer.

# Previous milestone: PRED-NOWSCORE-BIND-1 - Nowscore Source-Present / Binding-Failed Closure

Status: `SEALED / ACCEPTANCE PASS`

Decision: `PRED-NOWSCORE-BIND-1 = SEALED / ACCEPTANCE PASS`

This delivery only freezes the completed read-only binding audit. Current
evidence is `12/12` bf1 source-present, `8/12` current resolver replay exact,
`4/12` current name-normalization gaps, `12/12` market pages, `12/12`
analysis pages, and `0` kickoff difference. Historical intake source presence
is `UNKNOWN_NOT_PROVEN`. The root-cause status is
`NOWSCORE_SCHEDULE_HORIZON_GAP = EVIDENCE-SUPPORTED PRIMARY BLOCKER CANDIDATE`,
not a validated historical root cause. The sole next remedy category is
`NOWSCORE_SCHEDULE_HORIZON_GAP`. No repair or production change is made.

Evidence:

- `docs/data-foundation/PRED-NOWSCORE-BIND-1_ROOT_CAUSE_AUDIT.md`
- `data/football_data/pred_nowscore_bind_1/root_cause_matrix_2026-08-31.json`

# Previous milestone: PROD-WRITE-1 - Production Main Write Serialization

Status: `SEALED / ACCEPTANCE PASS`

Decision: `PROD-WRITE-1 = SEALED / ACCEPTANCE PASS`

The current task is a bounded production main write reliability fix. The
validated root cause is that the full production and high-frequency prematch
writers use separate concurrency groups while sharing overlapping durable
paths. The selected protocol commits generated state, fetches and rebases
`origin/main`, retries only synchronization/push within a bound, never
regenerates or force-pushes, and fails closed on a genuine rebase conflict.
Pages is rebuilt after the durable write.

`PROD-HEALTH-1 = SEALED / ACCEPTANCE PASS`.
`MARKET-SIDE-SHADOW-1 = DEPLOYED / SEALED / ACCEPTANCE PASS`.
`PARALLEL RESEARCH = GLOBAL-MARKET-0`.

Scope is limited to the workflow write protocol, its focused controlled
tests, and this current-state pointer. Acceptance requires one merged
`Refresh data and deploy Pages` verification with production cycle,
durability, durable write-back, and Pages success. Do not start model,
shadow, health-classifier, provider, identity, coverage, frontend, or
exact-score work.

# Previous milestone: MARKET-SIDE-SHADOW-1 - Bounded Prospective Shadow Validation

Status: `DEPLOYED / SEALED / ACCEPTANCE PASS`

Decision: `MARKET-SIDE-SHADOW-1 = DEPLOYED / SEALED / ACCEPTANCE PASS`

The completed milestone was the sole execution pointer at that time. The accepted PRED-TRUST-3
Challenger C is wired as a background-only sidecar. For every eligible frozen
fixture the runner captures Champion and C with the same match identity,
source cutoff, freeze-eligibility contract, and frozen input digest. The pair
is immutable, marked `PAIRED`, or marked `CHALLENGER_ABSTAIN` while preserving
Champion. C is not user-visible, formal-ledger eligible, or auto-promoted.

The sidecar stores C lambdas, 1X2, complete exact-score distribution and
Top1/Top3, BTTS, O/U 2.5, and total tails `>=4/5/6`. Its verified-result
consumer reports the paired metrics and BTTS reliability bins, with automatic
`CHECKPOINT` at 50 verified pairs and `PROMOTION_REVIEW_READY` at 100; neither
state promotes C. The first 30-pair window exposes early-stop integrity and
proper-metric sentinels.

Engineering smoke is complete using one existing PRED-TRUST-2 pinned record:
`PAIRED`, `169` C score rows, `0` verified paired results, checkpoint
`NOT_REACHED`. No new data was fetched, no frozen artifact was rewritten, and
the task does not wait for future sample growth.

The bounded closure is wired: `market_side_shadow_refresh.py` consumes only
existing verified final 90-minute result artifacts, evaluates the immutable
pair, and atomically persists `latest.json`. The closure smoke has one matched
verified result, but its engineering smoke pair is `promotion_eligible=false`:
total pairs `1`, paired `1`, promotion-eligible pairs `0`, excluded
non-promotion pairs `1`, verified promotion sample `0`, checkpoint
`NOT_REACHED`, and `auto_promote=false`. Only explicit production automatic
pre-kickoff captures that pass formal eligibility and all identity/freeze checks
enter the prospective promotion cohort. The optional `automation_cycle.py`
step records explicit `DEGRADED` research failures while continuing the
production cycle.

Evidence: `scripts/market_side_shadow.py`,
`tests/test_market_side_shadow.py`,
`data/prediction_quality/market_side_shadow_1/`, and
`docs/prediction-quality/MARKET-SIDE-SHADOW-1_FINAL_REPORT.md`. STOP after
engineering PR delivery.

# Historical acceptance record: PRED-TRUST-3 - Market-Side-Only Hybrid Knockout

Status: `SEALED / ACCEPTANCE PASS`

Independent product decision: `MARKET_SIDE_FUSION_PROMISING_FOR_SHADOW`

The original replay artifact remains unchanged and retains its machine result
`MARKET_SIDE_ONLY_NOT_SUFFICIENT`, caused by the strict BTTS ECE gate. The
independent acceptance override records maintained BTTS accuracy and improved
BTTS Brier; BTTS ECE remains a shadow-watch risk and must be reported with
Brier, LogLoss when available, and reliability bins. Its original pinned
`217`/`181` evidence and PRED-TRUST-3 report remain immutable.

PR #127 merged at
`c4a128826e4380ead2bea4ac10453b03cd849a28`. The previous pointer above was the
bounded shadow engineering milestone; it did not change Champion or
production.

# Historical execution record: PRED-TRUST-2 - Bounded Strength/Lambda Challenger Shootout

Status: `SEALED / ACCEPTANCE PASS`

Decision: `NO_CHALLENGER_BEATS_CHAMPION`

The one allowed offline replay is complete. It compared exactly the current
Champion, Challenger A (recent-form strength separation), and Challenger B
(market-to-goal separation), using only the pinned PRED-TRUST-1 evidence:
`217` unique final legal prematch matches and `181` verified 90-minute
results. The pinned production run is `33294381128` and the accepted
write-back commit is
`73994d32fc148da49295a5bfef2e1e42e042a22e`.
PR #125 was independently accepted for PRED-TRUST-1 and merged at
`1ec57af0b4bae7ca15cd41e2cdf4e578a21f7d89` before this milestone began.

Challenger A failed on concentration, lambda separation, 1X2 proper scores,
and exact Top3. Challenger B materially reduced 1-1 Top1 from `76.50%` to
`49.31%` and improved the lambda gap distribution, but failed the BTTS, O/U
2.5, and right-tail checks. Neither challenger passed the multi-signal
qualification gate. The report contains the complete metrics and machine
trade-off table.

No new data, fitting, post-match parameter input, Champion change, production
enablement, shadow run, frozen rewrite, ledger rewrite, health change,
provider change, or frontend change is allowed from this result.

Evidence: `data/prediction_quality/pred_trust_2/pinned_cohort_manifest.json`,
`data/prediction_quality/pred_trust_2/replay_2026-08-30.json`, and
`docs/prediction-quality/PRED-TRUST-2_FINAL_REPORT.md`.

PRED-TRUST-2 was independently accepted and sealed after PR #126 was merged
at `81d70ad263d58d067237b88b0c332c284345518d`. PRED-TRUST-3 is recorded above
as the current bounded research milestone.

# Historical execution record: PRED-TRUST-1 - Unique-Match Prediction Integrity & Multi-Market Quality Audit

Status: `SEALED / ACCEPTANCE PASS`

DATA-PLANE-2-PROD is closed as `SEALED / DEPLOYED / ACCEPTANCE PASS` after
independent final acceptance. PR #124 is the governance-only closeout record.
Publisher live validation remains `DEFERRED / NON_BLOCKING`; licensing review
remains `LICENSING_REVIEW_REQUIRED`; the workflow item is
`NON_SECRET_LOG_HYGIENE_DEBT`.

PR #123 merged into `main` at
`8e432d84f5c4d68bd25fb32fb31c3d55a7b6e651`; PR #120 remains OPEN and
unmerged. Production run `33294381128` completed SUCCESS, with bootstrap
READY, record count `1778`, dataset SHA-256
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`,
durability gate PASS, public-data write-back SUCCESS, and Pages deployment
SUCCESS. The current main write-back commit is
`73994d32fc148da49295a5bfef2e1e42e042a22e`.

Production health reported `ALERT / DUPLICATE_FROZEN_PREDICTION`, while
`runtime_data_snapshot.status=READY`. Dashboard availability is `PARTIAL`:
22/25 FROZEN, 3/25 INSUFFICIENT_DATA, 0 prediction failures. The remaining
failure distribution is `MISSING_RECENT_FORM=1`,
`INPUT_TIMESTAMP_UNVERIFIED=2`, `IDENTITY_UNAVAILABLE=0`, and
`SOURCE_UNAVAILABLE=0`. The 21 newly FROZEN production rows all record
`form_source=nowscore`; no row is proven to have been released solely by the
1778-row snapshot. The clean-runner probe separately remains
`authoritative_historical_results`.

Publisher live validation is `DEFERRED / NON_BLOCKING`; provisioning was
`MANUAL_PRIVATE_UPLOAD`. No PRED-AVAIL-3, ID-AUTO-2, provider addition, alias
work, or model change starts from this record.

The provider-neutral contract and one-time setup are recorded in
`docs/data-foundation/DATA-PLANE-2_PRIVATE_SNAPSHOT_BOOTSTRAP_CONTRACT.md`.
The exact canonical names are:

- `FOOTBALL_DATA_SNAPSHOT_PUBLISH_ACCESS_KEY_ID`
- `FOOTBALL_DATA_SNAPSHOT_PUBLISH_SECRET_ACCESS_KEY`
- `FOOTBALL_DATA_SNAPSHOT_RUNTIME_ACCESS_KEY_ID`
- `FOOTBALL_DATA_SNAPSHOT_RUNTIME_SECRET_ACCESS_KEY`
- `FOOTBALL_DATA_SNAPSHOT_ENDPOINT_URL`
- `FOOTBALL_DATA_SNAPSHOT_BUCKET`
- `FOOTBALL_DATA_SNAPSHOT_REGION`

Remaining log-hygiene item: the production Bootstrap step's environment
metadata exposed endpoint/bucket/region configuration values in the GitHub
log. Runtime access key and secret remained masked, and no values are copied
into this record. Data-plane verification remains valid; close this item in a
separate workflow-hygiene change before final security acceptance.

PRED-TRUST-1 was the preceding evidence audit, not a model modification task.
It used one final legal prematch prediction per unique match, classified all
production health duplicate groups, and reported current-day, historical,
lambda, cross-market, prospective, and health-gate evidence.

Audit result: `MIXED / SEALED / ACCEPTANCE PASS`. The accepted current-day source
has `22` frozen and `3` insufficient fixtures. Unique-match selection yields
`16/22` current and `166/217` historical `1-1` Top1, `14/22` and `144/217`
lambda gaps below `0.5`, and `181` verified prospective matches. Duplicate
classification is `A=51, B=0, C=0, D=0`, so `PREDICTION_INTEGRITY_BLOCKED` is
not active; the existing `DUPLICATE_FROZEN_PREDICTION` is a monitor false
positive for legitimate version history. The health gate recommendation is
`REPLACE_WITH_MULTI_SIGNAL`, with no gate change in this milestone.

Evidence: `docs/prediction-quality/PRED-TRUST-1_FINAL_REPORT.md` and
`data/prediction_quality/pred_trust_1/audit_2026-08-30.json`.

This historical pointer was followed by PRED-TRUST-2, whose bounded replay is
recorded at the current sole pointer above. The replay did not enable shadow,
promotion, or a Champion change.

STOP CONDITIONS:

- Publisher live validation remains deferred and is not part of this
  production-deployment verification record.
- Do not run another production refresh solely to increase availability.
- Do not rewrite today's frozen predictions or the historical prospective
  ledger; canonical selection is evaluation-only.
- Do not start PRED-AVAIL-3, ID-AUTO-2, a new provider, manual alias work,
  league-specific coverage, Publisher validation, B2 work, model tuning, or a
  Champion/model/selector/lambda change.
- Do not modify Champion mathematics, frozen predictions, prospective ledger,
  dashboard state, or raw source data.

# Historical execution record: DATA-PLANE-1 - Cloud Production Football Data Architecture Decision

Status: `SEALED / ACCEPTANCE PASS`

Decision: `B. PRIVATE_SNAPSHOT_STORE`.

The clean-runner audit is `PARTIALLY_REPRODUCIBLE`: tracked inputs reproduce
206 rows/digest `0a1183aa11ae3c27c8b2081cae2f8776dfc50fbb35371ef48374e6f798d01a74`,
while the authoritative local store is 1778 rows/digest
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`. The
bounded clean source proof makes `500-1364199` eligible through
`authoritative_historical_results`, but does not establish full-dataset
rebuildability or production deployment.

The decision document is
`docs/data-foundation/DATA-PLANE-1_CLOUD_PRODUCTION_DATA_ARCHITECTURE.md`.
Implementation is not started. The later implementation milestone must use a
private versioned snapshot, exact byte/logical digest verification, atomic
`FOOTBALL_DATA_HOME` bootstrap, read-only DuckDB access, immutable rollback and
last-known-good fallback. Source refresh must remain separate from prediction
runs.

STOP CONDITIONS:

- Keep `DATA-PLANE-1` at `READY_FOR_ACCEPTANCE` until independent acceptance.
- Do not provision R2/S3, Supabase or another database in this decision task.
- Do not add a full runtime dataset to the public repository.
- Do not start a workflow bootstrap, provider patch, PRED-AVAIL-3, ID-AUTO-2,
  Sweden/DC, PA-3, Champion promotion, model tuning or frontend work.
- Do not modify frozen predictions, prospective ledger, dashboard, runtime or
  Champion mathematics.
- Stop after the decision and evidence; implementation requires a new
  milestone.

Independent acceptance recorded the authoritative 1,778-row dataset with
dataset SHA-256
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`, the
`PARTIALLY_REPRODUCIBLE` clean-runner result, and the clean Norway proof for
`500-1364199` through `authoritative_historical_results` with 10 recent-form
records before kickoff. PR #121 merged to `main` at
`963f36e7d00e16560fbdcd571dc20415437afa2b`; PR #120 remains OPEN and
unmerged. The architecture decision remains `B. PRIVATE_SNAPSHOT_STORE`.

# Historical execution record: PRED-AVAIL-1

## PRED-AVAIL-1 - Daily Prediction Availability Closure

Status: `READY_FOR_ACCEPTANCE`

The same frozen 25-fixture cohort is retained at
`data/football_data/pred_avail_1/baseline_2026-08-30.json`, with cohort SHA-256
`0cf4f106c34f183c3d61a81952f70e9c7f2525c0376a1e6eff74bb087e15cb8d`.
BEFORE: 1 FULL/frozen, 24 `MISSING_RECENT_FORM`, 0 prediction failures, and 0
blocked Champion jobs. AFTER bounded replay: 2 FULL, 0 DEGRADED, 23
`INSUFFICIENT_DATA` / `MISSING_RECENT_FORM`, 0 prediction failures, and 0
blocked Champion jobs. The released fixture is `500-1364199` through the
existing authoritative historical-result store route.

The 24-row root-cause audit shows 1 `HISTORY_EXISTS_BUT_NOT_USED` and 23
`IDENTITY_BLOCKED`. All 24 retain the contributing source-not-routed,
source-unavailable, and provider-mapping-missing causes. The route is generic;
no league-specific importer, alias work, fuzzy identity, synthetic evidence,
new provider, market-only fallback, Champion math change, or production-state
rewrite was used.

`HC-AUTO-1 = SEALED / ACCEPTANCE PASS` and `ID-AUTO-1 = SEALED / ACCEPTANCE PASS`
after independent acceptance. PR #118 merged to `main` at
`04a548416513865e4af4771603fb4369074ecd57`. `IDENTITY_BACKLOG = NON_BLOCKING /
ON_DEMAND`; ID-AUTO-2 is not started. Production automatic state is preserved;
the AFTER result is a bounded local replay, not a deployment claim.

STOP CONDITIONS:

- Leave PRED-AVAIL-1 at `READY_FOR_ACCEPTANCE` until independent acceptance.
- Do not start ID-AUTO-2, Sweden/DC, PA-3, Champion promotion, or model tuning.
- Do not modify frozen prediction, prospective ledger, or automatic market,
  dashboard, and runtime artifacts.
- After independent acceptance, return to Multi-Market Prediction Quality.

# Historical execution record: ID-AUTO-1

## ID-AUTO-1 - League-Agnostic Deterministic Team Identity Resolution

Status: `SEALED / ACCEPTANCE PASS`

HC-AUTO-1 closeout is recorded as `SEALED / ACCEPTANCE PASS` after independent
acceptance. PR #117 was merged to `main` at
`7680c57475c907ba87cf40c9c1a3d1d48543edb1`; latest automatic-run state was
preserved.

Previous closeout remains recorded: `FE-SE-HIST-1 = SEALED / ACCEPTANCE PASS`,
`FE-SE-DC-CLOSE = ACCEPTANCE PASS / CLOSED`, model verdict `INCONCLUSIVE`
because 7 of the original 103 fixed-config targets had optimizer fit failures,
and `SWEDEN_SPECIFIC_FURTHER_TUNING = CLOSED`. PR #114 remains OPEN and
unmerged. No Sweden/DC calculation is part of this milestone.

ID-AUTO-1 delivers a generic team identity contract for every canonical
competition: canonical team ID/name, competition scope, country, provider and
provider team ID/name, reviewed aliases, evidence, resolution method,
confidence class and ambiguity state.

The daily route remains:

`Prediction Universe -> coverage registry/gate -> BASE job ledger -> existing Champion`

Identity resolution is exact-only and follows stable provider ID, reviewed
provider crosswalk, fixture canonical ID, competition exact normalized name,
then competition-scoped reviewed alias. Every row retains a current Champion
job; historical challenger eligibility is turned off when the coverage gate is
not `SUPPORTED`. Ambiguous and unresolved rows never block other fixtures.

ID-AUTO-1 evidence:

- `scripts/football_data/identity_registry.py`
- `scripts/football_data/run_id_auto_1.py`
- `data/football_data/id_auto_1/identity_registry.json`
- `data/football_data/id_auto_1/daily_fixture_audit.json`
- `data/football_data/id_auto_1/identity_resolution_backlog.json`
- `data/football_data/id_auto_1/provider_id_reuse_evidence.json`
- `docs/data-foundation/ID-AUTO-1_IDENTITY_RESOLUTION.md`
- focused identity, gate and audit-artifact tests

The same real 66-fixture snapshots were audited as one mixed fixture set.
BEFORE: 1 `SUPPORTED`, 65 `UNSUPPORTED`, 0 blocked Champion jobs. AFTER:
2 `SUPPORTED`, 0 `DEGRADED`, 64 `UNSUPPORTED`, 2 fully auto-resolved fixtures,
7 partial fixtures, 57 unresolved fixtures, 0 ambiguous fixtures, and 0 blocked
Champion jobs. Existing free/reproducible sources and reviewed evidence were
reused; no manual per-fixture alias work, new provider, country-specific
adapter, paid source, model change, frozen prediction change, or
historical-store rebuild was introduced.

Japan J1 and Spain La Liga are recorded as `READY_FOR_GENERIC_IMPORT` only;
their generic existing adapters were not executed in this milestone. The
remaining identity backlog is evidence for later scope, not a reason to start
a league-specific importer.

STOP CONDITIONS:

- Do not start ID-AUTO-2 automatically.
- Do not tune or calculate Sweden/Dixon-Coles, promote a Champion, or modify
  frozen/prospective records.
- Identity backlog is only recorded for a later separately scoped milestone.
- This historical execution record was independently accepted; ID-AUTO-1 is
  `SEALED / ACCEPTANCE PASS`. HC-AUTO-1 is also recorded as
  `SEALED / ACCEPTANCE PASS`.

# 历史执行记录（非当前指针）

`PA-2-R1-ID3 — Targeted Identity Persistence, Bounded History Closure & Prospective Pair Capture`

状态：HISTORICAL

本指针在本次 Governance Current-State Sync 提交后生效。ID2 evidence package/status 是 `READY_FOR_ACCEPTANCE / INDEPENDENT ACCEPTANCE PENDING`；PA-2-R1 model program overall 仍为 `OVERALL INCOMPLETE / TOO_SMALL_FOR_DECISION`，不是整体已验收。


# 1. 已完成，不再重跑

以下 DATA / ID / COV-SRC / ID2 工作已有真实 evidence，不得重新按陈旧 Formal 14 / pre-ID2 状态施工：

- DATA：shared authoritative baseline 已核验为 1,554 historical results / 160 team-strength snapshots；Europa v3 summary 的 staging 数字为 `record_count=2,153`、`eligible_count=1,559`、`excluded_count=594`，不代表 shared DB 已迁移；
- ID：deterministic bridge 已完成，formal eligible=9、excluded pilot=5，状态为 AVAILABLE=1、COMPETITION_UNSUPPORTED=6、HISTORY_UNAVAILABLE=1、IDENTITY_UNAVAILABLE=1；
- COV-SRC：来源、cutoff、provenance 与赛后/赛前语义已进入现有 evidence，不重跑 source coverage audit；
- ID2：same-match paired sample=1，`result_gate=PARTIAL_PAIRED_EVALUATION`，`verdict=TOO_SMALL_FOR_DECISION`；Champion 不变，Challenger shadow-only，CA-1 paused，PA-3 not started；
- 旧 `Formal 14` 只保留为历史 label；当前正式 cohort 使用 `formal eligible=9 + excluded pilot=5`。

# 2. ID3 最短执行路径

## A. Hearts–Benfica：先审语义，再决定是否补历史

- 现有两队 identity 已由官方 fixture/球队证据 deterministic solved；不要重复做 identity mapping；
- 先检查 Challenger 的历史窗口、recency 与 `min-history` 语义，确认 2/5 是哪一侧/哪一层 prior 门槛；
- 只有真实、pre-cutoff、同一 `UEFA Europa League` competition 的历史记录仍具统计意义时，才允许定向补充；禁止混入 Conference League，也禁止为了凑满 5 场纯补数量；
- 若历史窗口/recency 语义表明补更老样本不再有研究价值，立即停止该分支。

## B. 另外三个 Europa formal target：补 production-side deterministic identity

Pafos–Salzburg、Rangers–Jagiellonia、Anderlecht–PAOK 已有官方赛事 corroboration，但 production-side identity 仍不足以进入 paired。优先检查现有 Nowscore/500 structured snapshots 中的稳定 provider team IDs 与既有 crosswalk：

- 仅接受可复现的 provider ID、既有 canonical registry/crosswalk 或 competition-constrained exact unique alias；
- 不使用中文翻译、非唯一 kickoff time、fuzzy、LLM 或人工“看起来像”匹配；
- 目标不是增加 alias 数量，而是让真实 fixture 获得可审计、可复现的 production-side identity。

## C. Elfsborg：独立 secondary blocker

Elfsborg 继续保持 `IDENTITY_UNAVAILABLE`。没有新的 deterministic provider/crosswalk evidence 就停止，不 fuzzy、不借用未验证别名。

## D. Retrospective 与 prospective 分界

如果 2026-08-14 的 retrospective fixture 因 capture timing 或 identity 不能合法解锁，停止强行补旧比赛，转向 prospective pre-kickoff capture readiness。赛后抓到的 Europa source 必须标注为 post-match captured evidence，不能改写成 pre-match prospective evidence。

# 3. ID3 成功标准

满足以下任一项即可形成可验收进展：

1. 在完全相同 match IDs 上，真实 paired sample 增加；或
2. 关键 blocker 被 deterministic 关闭，并形成可执行、赛前冻结时可复现的 prospective pair-capture 路径。

“新增了多少 alias”或“凑到 5 场历史”本身不算成功。

# 4. 停止条件与硬边界

bounded history 检查没有新的同赛事、pre-cutoff 且统计上有意义的 prior；三场 Europa target 没有稳定 provider ID/crosswalk；Elfsborg 没有新的 deterministic identity；或 retrospective capture 无法满足赛前证据链时，停止历史扩展并等待 prospective pair capture。

不得在 ID3 中：

- 启动 PA-3、CA-1 或 Champion promotion；
- 修改 Champion、模型数学、预测、production/shared DB 或 frozen prediction；
- 扩新 provider、混入 Conference League、使用十年前无意义历史、重跑 DATA/ID/COV-SRC/ID2；
- 把任何 post-match source 当作 prospective evidence。

# 5. 完成状态

Codex 完成 ID3 后只能写：

`READY_FOR_ACCEPTANCE`

不得自行写 `SEALED`。

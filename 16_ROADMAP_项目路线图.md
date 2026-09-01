# 16_ROADMAP_项目路线图.md

最后更新：2026-09-01
路线原则：Gate 驱动，不使用虚假日期承诺。

# Current Route Pointer

# NOWSCORE-JC-SALES-PAGE-1 - Current route gate

CURRENT ROUTE MILESTONE: NOWSCORE-JC-SALES-PAGE-1
CURRENT ROUTE STATUS: READY_FOR_ACCEPTANCE / PASS
CURRENT ROUTE DECISION: PASS / Nowscore direct JC sales page

The direct JC sales page is the current-universe route. It supplies selected
SelDate, matching niDate date/group, explicit 11:00--next-day-11:00 sales
window, 周XNNN match number, unique Nowscore ID, kickoff, and identity fields.
Paired replay is 12 rows for 2026-08-31 and 10 rows for 2026-09-01; all
next-calendar-day kickoffs remain under selected business date. Duplicate,
ambiguous, and cross-date ID overlap are zero. A32 is optional corroboration,
not an acceptance intersection.

The route is Nowscore JC sales page -> canonical fixture / identity -> existing
evidence -> BASE. Sporttery and 500 are not current-universe blocking sources;
independent optional capabilities remain. STOP at READY_FOR_ACCEPTANCE; no
merge and no Challenger Promotion Review.

# Historical NOWSCORE-JC-BUSINESS-DATE-1 - Current route gate

CURRENT ROUTE MILESTONE: NOWSCORE-JC-BUSINESS-DATE-1

CURRENT ROUTE STATUS: READY_FOR_ACCEPTANCE / NO_CODE

CURRENT ROUTE DECISION: NO_CODE

The public Nowscore JC sales page exposes the deterministic anchor
SelDate + niDate header date and the explicit 11:00--??11:00 sales
window. The paired replay preserved the exact existing membership contract
SetLevel(3) -> A[j][32] == 1: 12/12 public rows for 2026-08-31 joined
explicitly, while the nonempty 2026-09-01 public group had 0/10 explicit
live sc1 joins. The full decision gate is therefore NO_CODE, not a
permission to guess membership.

Exact evidence is recorded in docs/data-foundation/NOWSCORE-JC-BUSINESS-DATE-1_PROBE_RUN_33470293458.json and the report
docs/data-foundation/NOWSCORE-JC-BUSINESS-DATE-1_PROBE_REPORT.md. No current-universe business-date production code was changed in
this milestone. STOP at READY_FOR_ACCEPTANCE; no merge and no Challenger
Promotion Review.

# Historical milestone: NOWSCORE-JC-UNIVERSE-1 - Current route gate

CURRENT ROUTE MILESTONE: NOWSCORE-JC-UNIVERSE-1

CURRENT ROUTE STATUS: READY_FOR_ACCEPTANCE

CURRENT ROUTE DECISION: PASS / Nowscore public JC

The bounded GitHub-runner gate proved the public Nowscore current `ft1` page
and backing data contract for `2026-09-01`: `SetLevel(3)` maps to
`A[j][32] == 1`, yielding 12 deterministic fixtures with duplicate IDs `0`
and ambiguous IDs `0`. Exact evidence is recorded in
`docs/data-foundation/NOWSCORE-JC-UNIVERSE-1_PROBE_RUN_33466072890.json`.

The route is now Nowscore JC → canonical fixture / identity → existing
evidence → BASE. Sporttery and 500 are retired from current-universe schedule
dependency, while independent optional market/corroboration and 500 deep
evidence capabilities remain. No model or historical/prospective state is
changed.

STOP at `READY_FOR_ACCEPTANCE`; no merge and no Challenger Promotion Review.

# Historical milestone: CURRENT-UNIVERSE-ROLLOVER-1 - Current route gate

HISTORICAL ROUTE MILESTONE: CURRENT-UNIVERSE-ROLLOVER-1

HISTORICAL ROUTE STATUS: READY_FOR_ACCEPTANCE / NO CODE

HISTORICAL ROUTE DECISION: WAF_BLOCK / NO_CODE

The route gate is a bounded production-source probe for the 2026-09-01 business date. It keeps Sporttery primary, preserves the existing 2026-08-31 path, and does not authorize a production change because every official Sporttery route and the 500 fallback surface was blocked or challenged before target rows could be observed. The exact runner artifact and classification are recorded in docs/data-foundation/CURRENT-UNIVERSE-ROLLOVER-1_PROBE_REPORT.md and the paired JSON evidence file.

No later model, identity, provenance, or promotion route is opened by this milestone.

# Historical milestone: PRED-INPUT-PROVENANCE-1 - Deterministic Prematch Input Provenance

HISTORICAL ACTIVE MILESTONE:

`HISTORICAL-PRED-INPUT-PROVENANCE-1`

HISTORICAL STATUS: `ACCEPTANCE PASS / MERGE AUTHORIZED`

HISTORICAL DECISION: `PRED-INPUT-PROVENANCE-1 = ACCEPTANCE PASS / MERGE AUTHORIZED`

The milestone closes the general error-classification gap between source
fetch, observation timestamp, cache/form provenance, official market timing,
deterministic snapshot construction, and cutoff validation. Durable current
history cannot distinguish the two target fixtures beyond the observed
run-level 500 deep fetch failures, so no historical relabeling or eligibility
change is allowed.

Evidence: `docs/data-foundation/PRED-INPUT-PROVENANCE-1_IMPLEMENTATION_REPORT.md`.
Engineering acceptance is PASS and merge is authorized. Real production
verification follows merge; no next milestone starts here.

# Previous milestone: PRED-IDENTITY-SAFE-PARTIAL-1 - Deterministic Nowscore Fallback

`PRED-IDENTITY-SAFE-PARTIAL-1 - Deterministic Nowscore Fallback`

CURRENT STATUS: `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

CURRENT DECISION: `PRED-IDENTITY-SAFE-PARTIAL-1 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

PR #139 = `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Closed historical milestone; current pointer is `PRED-INPUT-PROVENANCE-1`.

PR #139 implements the replay-approved Candidate B as a fail-closed fallback
behind the existing strict resolver. The current 12-fixture replay preserves
all eight existing IDs, adds `2913703`, `2913701`, and `2912252`, and leaves
`500-1427969` unresolved. Historical wrong binding, ambiguous collision,
orientation conflict, accepted-binding regression, and existing-eight
regression are all zero. The fallback does not relax fuzzy thresholds, add
aliases or provider data, special-case team IDs, use LLM matching, or hardcode
match IDs.

Evidence is recorded in
`docs/data-foundation/PRED-IDENTITY-SAFE-PARTIAL-1_IMPLEMENTATION_REPORT.md`.
PR #139 merged at `ac96358b161abe35e931d873357f6fb69635c0b4`. Production Run
`33399507542` completed with durable write
`c0a30839867eefd83d822643e54eecc15cafec7f`; Nowscore binding was `11/12`.
Focused tests, `py_compile`, and `git diff --check` pass. This milestone is
deployed, sealed, and production-accepted.

# Previous milestone: NEXT-UNIVERSE-TRUTH-1 / PR #138

Status: `DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

Decision: `NEXT-UNIVERSE-TRUTH-1 / PR #138 = DEPLOYED / SEALED / PRODUCTION ACCEPTANCE PASS`

PR #138 merged at `db4b79793bb79c8637dbd69c0444aa4b5d8bbca6`. This milestone
recorded one bounded live probe and the smallest deterministic
fallback-provenance fix. Current Sporttery truth was HTTP 200 with only
`businessDate=2026-08-31`; current 500 truth was a successful page with 12
`2026-09-01` kickoff rows assigned to `data-processdate=2026-08-31`, so the
business-date parser returned 0 for `2026-09-01`. The production 15:41 upstream
classification remained `UNKNOWN_NOT_PROVEN` because the exact historical
fallback status/error was not persisted.

Evidence remains recorded in
`docs/data-foundation/NEXT-UNIVERSE-TRUTH-1_FINAL_REPORT.md`. The milestone did
not change production data, identity aliases, providers, source order, Champion,
model, resolver, endpoint, business-date parser semantics, frozen history, or
frontend. Its route is closed and is not reopened.

`PROD-HEALTH-1 = SEALED / ACCEPTANCE PASS` is a closed previous milestone.
`MARKET-SIDE-SHADOW-1 = DEPLOYED / SEALED / ACCEPTANCE PASS` remains closed.
`GLOBAL-MARKET-0` remains parallel research only.

# Previous milestone: PROD-WRITE-1 - Production Main Write Serialization

The write contract is: commit generated durable state, fetch/rebase the current
`origin/main`, push with bounded retry, never regenerate on retry, never force
push, and fail closed on a real rebase conflict. Pages deployment follows the
durable write. Acceptance requires controlled A/B/C/D writer simulations plus
one merged `Refresh data and deploy Pages` production verification. STOP after
verification and remote delivery.

# Previous milestone: MARKET-SIDE-SHADOW-1

The accepted PRED-TRUST-3 Challenger C is now wired as a background-only
paired shadow. The existing runner captures Champion and C from the same
fixture, source cutoff, freeze-eligibility contract, and frozen input digest.
Each capture is immutable and uses `PAIRED` or failure-isolated
`CHALLENGER_ABSTAIN`; Champion remains the user-facing and formal prediction.
The independent shadow evaluator stores full C score distributions, BTTS
calibration reliability bins, right-tail measures, and deterministic 50/100
sample checkpoint states without automatic promotion.

Engineering smoke is complete on one existing PRED-TRUST-2 pinned record:
`PAIRED`, `169` exact-score rows, `0` verified paired results, and
`NOT_REACHED` checkpoint. Evidence is under
`data/prediction_quality/market_side_shadow_1/` and the final report. This
milestone stops after wiring, smoke, tests, and PR delivery; it does not wait
for future sample growth.

Closure evidence additionally proves automatic evaluation: the refresh reads
the existing verified result artifacts, matches one result to the immutable
pair, atomically persists `latest.json`, and reports total pairs `1`, paired
`1`, promotion-eligible pairs `0`, excluded non-promotion pairs `1`, verified
promotion sample `0`, checkpoint `NOT_REACHED`, and `auto_promote=false`.
The matched pair remains engineering smoke evidence, not prospective promotion
cohort evidence. `automation_cycle.py` runs this research step after postmatch
and prospective settlement as optional failure-isolated work.

PRED-TRUST-3 remains recorded as `ACCEPTANCE PASS` with independent product
decision `MARKET_SIDE_FUSION_PROMISING_FOR_SHADOW`. Its original replay
artifact still records the original machine result
`MARKET_SIDE_ONLY_NOT_SUFFICIENT`; the BTTS ECE increase is retained as a
shadow watch risk. No Champion or production promotion follows from either
record.

`DATA-PLANE-2-PROD - Production Deployment Verification` is now
`SEALED / DEPLOYED / ACCEPTANCE PASS`. PR #124 is the governance-only closeout
record. Publisher live validation remains `DEFERRED / NON_BLOCKING`, licensing
review remains `LICENSING_REVIEW_REQUIRED`, and the known workflow item is
`NON_SECRET_LOG_HYGIENE_DEBT`.

Decision: `B. PRIVATE_SNAPSHOT_STORE`. The implementation uses a
vendor-neutral private versioned snapshot plus the existing read-only DuckDB
vendor-neutral private versioned snapshot plus the existing read-only DuckDB
runtime model. PR #123 merged at
`8e432d84f5c4d68bd25fb32fb31c3d55a7b6e651`; PR #120 remains OPEN and
unmerged. Production run `33294381128` completed SUCCESS: bootstrap READY,
runtime count `1778`, dataset SHA-256
`48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2`,
durability gate PASS, public-data write-back SUCCESS, and Pages deployment
SUCCESS.

That production run reported an explicit product warning
`DUPLICATE_FROZEN_PREDICTION`; `runtime_data_snapshot.status=READY` and the
data-plane parity remained PASS. The dashboard was `22 FROZEN / 3
INSUFFICIENT_DATA` out of 25, so daily availability is `PARTIAL`, not
`SEVERELY_BLOCKED`. No PRED-AVAIL-3, ID-AUTO-2, provider addition, alias work,
or model change is active.

The accepted PRED-TRUST-1 and PRED-TRUST-2 audits used canonical unique-match
cohorts and did not alter the Champion, frozen/prospective state, or public
repository data boundary. The bounded PRED-TRUST-3 replay stopped before any
model, provider, identity, or presentation change; the new shadow sidecar is
an independent research namespace and does not rewrite those artifacts.

PRED-TRUST-1 audit evidence is recorded in
`docs/prediction-quality/PRED-TRUST-1_FINAL_REPORT.md` and
`data/prediction_quality/pred_trust_1/audit_2026-08-30.json`. The result is
`MIXED`: `A=51/B=0/C=0/D=0` duplicate classification, `22` current unique
matches, `217` historical unique matches, and `181` verified prospective
matches. Exact-score Top1 `1-1` is `72.73%` current and `76.50%` historical;
lambda gap `<0.5` is `63.64%` current and `66.36%` historical. The ranked
evidence is P0 lambda generation, P1 product presentation, P2 market fusion.
PRED-TRUST-2 and PRED-TRUST-3 are accepted and sealed. That previous route was
the engineering-only shadow wiring milestone; it was not a Champion change,
production promotion, or frontend change.

Open workflow-hygiene item: the production Bootstrap step exposed endpoint,
bucket, and region configuration values through GitHub step environment
metadata. Runtime credentials remained masked. This is separate from the
successful snapshot parity result and requires a bounded follow-up before the
log-hygiene requirement can be considered closed.

# Historical PRED-AVAIL-1 Route Record

PREVIOUS PHASE:

`PRED-AVAIL-1 - Daily Prediction Availability Closure`

CURRENT STATUS: `READY_FOR_ACCEPTANCE`

The exact 25-fixture 2026-08-30 cohort is frozen. BEFORE was 1 FULL/frozen and
24 `MISSING_RECENT_FORM`; the bounded same-cohort AFTER replay is 2 FULL, 0
DEGRADED, 23 `MISSING_RECENT_FORM`, 0 prediction failures, and 0 blocked
Champion jobs. The generic authoritative-history route released one fixture
without changing Champion math or production automatic state. Detailed audit
artifacts are under `data/football_data/pred_avail_1/`.

`ID-AUTO-1 = SEALED / ACCEPTANCE PASS` and `HC-AUTO-1 = SEALED / ACCEPTANCE PASS`
after independent acceptance. PR #118 merged to `main` at
`04a548416513865e4af4771603fb4369074ecd57` without reverting automatic state.
`IDENTITY_BACKLOG = NON_BLOCKING / ON_DEMAND`; ID-AUTO-2 is not active.

PRED-AVAIL-1 remains a product blocker at 23/25 unavailable and stops at
`READY_FOR_ACCEPTANCE`. After independent acceptance, the next candidate is
Multi-Market Prediction Quality. No model-tuning task is active here.

# ID-AUTO-1 Historical Route Record

ID-AUTO-1 used one competition-scoped exact identity registry and resolver. It
retains provider-ID reuse, Champion fail-open behavior, no per-fixture aliases,
and no league-specific resolver. Its independently accepted result is
`SEALED / ACCEPTANCE PASS`; no ID-AUTO-2 is started.

# North Star

建立：

`真实比赛发现 → 数据/身份 → 足球+市场情报 → 赛前概率预测 → 不可篡改冻结 → 用户解释 → 真实赛果 → Prospective → Challenger 改进`

的完整足球智能平台。

原则：

`预测质量 > 页面丰富度`  
`真实验证 > 主观感觉`  
`可复现 > 看起来聪明`  
`先修上游 > 给错误结果做解释`

# Phase 0 — Production Foundation

状态：`SEALED`

已包含：

- Prediction Universe；
- BASE jobs；
- minimum eligibility；
- immutable freeze；
- verified result；
- prospective ledger；
- automation；
- health；
- GitHub Pages；
- workspace freshness。

# Phase 1 — Product Workspace

状态：`PARTIALLY SEALED`

- 1A Homepage：`SEALED`
- 1B Match Detail Infrastructure：`DONE`
- Legacy Mapper：`HISTORICAL COMPATIBILITY ONLY`
- CA-1 Current Constrained Analysis：`BLOCKED / PAUSED`

恢复条件：Prediction Quality Gate 通过。

# Phase 2 — Prediction Integrity

状态：`CURRENT PROGRAM`

## PA-1 — Prediction Sanity Audit

`SEALED`

## PA-1-R1 — Replay & Metric Integrity

`SEALED`

## PA-2 — Opponent-Adjusted Strength Challenger

`HISTORICAL RESEARCH VALID / OVERALL INCOMPLETE`

## PA-2-R1 — Canonical Identity & Paired Evaluation（历史研究）

`HISTORICAL`

目标：

- production identity signal audit；
- historical canonical identity audit；
- deterministic bridge；
- 区分 identity coverage 与 history coverage；
- current 23 coverage；
- formal eligible coverage（旧 `Formal 14` 为历史 label，当前为 eligible=9 + excluded pilot=5）；
- same-subset paired metrics。

ID2 已验证：AVAILABLE=1、COMPETITION_UNSUPPORTED=6、HISTORY_UNAVAILABLE=1、IDENTITY_UNAVAILABLE=1，paired=1；结果为 `PARTIAL_PAIRED_EVALUATION / TOO_SMALL_FOR_DECISION`。Hearts–Benfica identity solved 但 Europa history 为 2/5，Elfsborg 仍 unresolved。

FE-SE-HIST-1 后 shared authoritative baseline 为 1,778 historical results / 160 team-strength snapshots；PA-2-R1 旧快照中的 1,554 是 closure 前基线，Europa v3 summary 为 `record_count=2,153`、`eligible_count=1,559`、`excluded_count=594`，仅为 staging。

### Gate A — Paired signal promising

→ `PA-3 — Prospective Shadow Challenger`

### Gate B — History / identity coverage 是主 blocker

→ `PA-2-R1-ID3 — Bounded targeted closure, then prospective pair capture`

只扩高价值、真实阻塞赛事，不全世界一起抓；不为凑满 5 场引入统计上无意义的十年前数据。bounded closure 没有新 eligible 时停止历史扩展。

### Gate C — Challenger paired 明显弱

→ `PA-2-RX — Model Rethink`

### Gate D — Paired sample too small

ID2 的 paired=1 只能保持 `TOO_SMALL_FOR_DECISION`，不得自动进入 PA-3、不得改变 Champion。先执行 ID3；只有新的真实 prospective paired evidence 具备后，才单独评估是否启动 PA-3。

## FE-SE-HIST-1 — Sweden Historical Completeness Closure

状态：`SEALED / ACCEPTANCE PASS`

FE-DC-1 已独立验收为工程/研究实验 PASS，但 Dixon-Coles `NOT_PROMOTABLE`；PR #114 保留为 research evidence，暂不 merge。本里程碑只修复其上游 Sweden Allsvenskan historical completeness：

- Football-Data 2025：240/240，16 队；
- authoritative 2025：16 → 240，2026 保持 119；
- identity unresolved、duplicate conflict：0；
- 2025 每队 30 场、120 条无向对手边，connected network=true；
- raw hash、source timestamp、exact identity evidence、secondary OpenFootball 53/53 cross-check 和 DuckDB rebuild digest 均已留存。

硬边界：不改 FE-DC-1 的 rho/half-life/attack-defense 参数，不扩 provider/联赛，不改 Champion、production 或 frozen prediction。完成 FE-SE-HIST-1 后，是否继续研究完整 network 的模型质量由独立验收和后续 research milestone 决定，不自动 promotion。

# Phase 3 — Prospective Challenger Validation

状态：`FUTURE / GATED`

## PA-3 — Prospective Shadow Challenger

未来每场同时保存 Current Champion + Challenger Shadow。

Champion 面向 production；Challenger 不影响用户推荐。

积累约 40–50 新 prospective 后进入 review。

## PA-4 — Challenger Review

比较：

- 1X2 Brier / LogLoss；
- Goal MAE；
- BTTS；
- Exact Top1/Top3/Top5；
- Score NLL；
- 1-1 / draw concentration；
- lambda gap；
- strong favourite performance。

## PA-5 — Champion Promotion

状态：`FUTURE`

需要更成熟 prospective 样本（约 100+）与历史 holdout 共同支持。

# Phase 4 — Analysis Intelligence

状态：`BLOCKED`

恢复 CA-1。

目标：

`Frozen Prediction + Football Evidence + Market Evidence`
`→ constrained structured analysis`
`→ deterministic validation`
`→ user-facing match report`

五段分析：

1. 强弱与主动权；
2. 节奏与进球环境；
3. 得分路径；
4. 关键分叉；
5. 最终收敛。

# Phase 5 — Prediction + Analysis Product

状态：`FUTURE`

统一今日比赛、快速结论、单场详情、市场证据、足球证据、赛后真实验证、模型长期表现。

# Phase 6 — Targeted Coverage Expansion

状态：`FUTURE / DEMAND-DRIVEN`

根据：

`需求高 + 缺失高 + 已证明模型能从历史数据获益`

定向补充赛事。

# Phase 7 — Advanced Football Features

状态：`FUTURE`

可能逐项研究：

- xG opponent adjustment；
- player-level strength；
- lineup impact；
- injury value；
- manager effect；
- rest / travel；
- weather；
- set-piece strength；
- advanced Dixon-Coles；
- hierarchical competition model。

# Phase 8 — Betting Decision Layer

状态：`FUTURE / DOWNSTREAM`

只有在概率可信、校准可验证、市场价格可执行后，才重新提升 EV、value、stake sizing、串关相关性、portfolio。

# Roadmap 规则

阶段状态只能使用：

- `SEALED`
- `CURRENT`
- `READY`
- `BLOCKED`
- `FUTURE`
- `CANCELLED`

Roadmap 不是承诺。任何 Gate 未通过，后续阶段可以取消、替换或重排。

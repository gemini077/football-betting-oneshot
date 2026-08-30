# 16_ROADMAP_项目路线图.md

最后更新：2026-08-30
路线原则：Gate 驱动，不使用虚假日期承诺。

# Current Route Pointer

CURRENT PHASE:

`MARKET-SIDE-SHADOW-1 - Bounded Prospective Shadow Validation`

CURRENT STATUS: `READY_FOR_ACCEPTANCE`

CURRENT DECISION: `MARKET-SIDE-SHADOW-1 = READY_FOR_ACCEPTANCE`

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

The production health result is an explicit product warning
`DUPLICATE_FROZEN_PREDICTION`; `runtime_data_snapshot.status=READY` and the
data-plane parity remains PASS. The dashboard is `22 FROZEN / 3
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
PRED-TRUST-2 and PRED-TRUST-3 are accepted and sealed. The current route above
is the engineering-only shadow wiring milestone; it is not a Champion change,
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

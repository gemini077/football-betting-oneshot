# 16_ROADMAP_项目路线图.md

最后更新：2026-08-29
路线原则：Gate 驱动，不使用虚假日期承诺。

# Current Route Pointer

CURRENT PHASE:

`HC-AUTO-1 - League-Agnostic Historical Coverage Foundation`

CURRENT STATUS: `READY_FOR_ACCEPTANCE`

`FE-SE-HIST-1` is `SEALED / ACCEPTANCE PASS` after PR #115 merged to main.
`FE-SE-DC-CLOSE` is `ACCEPTANCE PASS / CLOSED` with model verdict
`INCONCLUSIVE` because 7 of 103 fixed-config targets had optimizer fit
failures. `SWEDEN_SPECIFIC_FURTHER_TUNING` is `CLOSED`; PR #114 remains OPEN
and unmerged. No Sweden/DC computation is part of HC-AUTO-1.

HC-AUTO-1 builds a reusable registry from existing manifests, adapters,
reviewed exact identity evidence and the authoritative historical store. It
adds the automatic `SUPPORTED` / `DEGRADED` / `UNSUPPORTED` gate before BASE
job intake, without changing the Champion, frozen predictions or model math.

Current milestone result: `READY_FOR_ACCEPTANCE`. Independent acceptance is
still required before any `SEALED` state.

NEXT MAINLINE CANDIDATE:

> Stop after HC-AUTO-1 acceptance. Do not automatically start HC-AUTO-2.
>
> Any future coverage expansion must use the same registry/manifest route and
> a separately accepted milestone.

BLOCKED / NOT ACTIVE:

- PR #114 FE-DC-1 remains research evidence and OPEN / unmerged.
- Dixon-Coles, Sweden-specific parameter tuning, and PA-3 are closed / not active.
- Champion promotion, production model changes, frozen prediction changes, new providers, and other-league expansion are not active.
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

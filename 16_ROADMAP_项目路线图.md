# 16_ROADMAP_项目路线图.md

最后更新：2026-08-17  
路线原则：Gate 驱动，不使用虚假日期承诺。

# 当前路线指针

CURRENT PHASE：

`PA-2-R1 — Canonical Identity & Paired Challenger Evaluation`

NEXT GATE：

> 能否让 Challenger 在与 production Current 完全相同的正式比赛子集上被公平评价？

BLOCKED：

`CA-1 — Current Constrained Analysis Layer`

NOT ACTIVE：

- Betting expansion
- Live betting
- Advanced football feature expansion
- Champion promotion
- 全联赛历史数据扩展

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

## PA-2-R1 — Canonical Identity & Paired Evaluation

`CURRENT`

目标：

- production identity signal audit；
- historical canonical identity audit；
- deterministic bridge；
- 区分 identity coverage 与 history coverage；
- current 23 coverage；
- formal 14 coverage；
- same-subset paired metrics。

### Gate A — Paired signal promising

→ `PA-3 — Prospective Shadow Challenger`

### Gate B — History coverage 是主 blocker

→ `PA-2-R2 — Targeted Historical Coverage Expansion`

只扩高价值、真实阻塞赛事，不全世界一起抓。

### Gate C — Challenger paired 明显弱

→ `PA-2-RX — Model Rethink`

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

# 16_ROADMAP_项目路线图.md

最后更新：2026-09-04
状态：`CLEAN BASELINE / MULTI-MARKET QUALITY REBASE LOCKED`

角色：只描述产品如何从当前状态走向**预测更强、可验证、可公开、可持续使用**。不保存历史 milestone。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. North Star

Football Betting OneShot 的核心不是“做一个 Trust 页面”，也不是“再做一个会猜比分的网站”。

核心产品价值：

> **在用户真正关心的多个足球玩法上，持续提高赛前预测命中率与概率质量，并且能用不可篡改的 prospective evidence 证明这些成绩真实、可复现、适用范围明确。**

长期闭环：

`比赛发现 → 足球/市场证据 → 多玩法概率 → 赛前冻结 → 用户决策 → 赛后真实结算 → 逐玩法评价 → failure analysis → Challenger → 持续提高预测质量`

关系必须保持：

`Prediction Quality = 发动机`
`Trust / Freeze / Calibration / Benchmark = 证明系统`
`UI / Beta / Rights / Operations / Compliance = 交付系统`

不得再次把“透明/信任”本身写成预测能力的替代品。

---

# 2. 目标玩法不是只有四个

旧控制面长期把核心玩法缩成 `1X2 / Exact Score / O-U / BTTS`，不完整。

## Tier A — 中国竞彩第一等目标

1. **胜平负 / FT 1X2**
2. **让球胜平负** — 必须冻结赛前官方让球线并有正确结算语义
3. **比分**
   - raw exact-score distribution / Top-N scenarios
   - 官方竞彩比分结果桶在语义验收后单独评价
4. **总进球数 0–7+**
5. **半全场** — 必须先建立可靠 first-half truth 与专门评价/模型链

`混合过关` 是 downstream 组合方式，不是独立 prediction target。

## Tier B — 国际/分析核心补充

- O/U lines
- BTTS
- Asian/common handicap
- team totals
- winning margin
- double chance

## Tier C — Specialized Future

corners / cards / player props 等，只在用户需求、合法赛前数据、可结算 truth、独立 evaluation 均成立时进入。

---

# 3. Prediction Quality Scorecard — 产品第一指标体系

禁止一个跨玩法 blended “overall accuracy”。不同玩法难度不同，把 Double Chance、O1.5、Exact Score 混成一个数字会失真。

**每个玩法单独建立成绩表。**

最小字段：

1. `eligible unique matches`
2. `settled unique matches`
3. **full-coverage Top1 hit rate**
4. **served hit rate**
5. **served coverage / abstain rate**
6. **same-market baseline hit rate**
7. **delta vs baseline**
8. proper score：Brier / LogLoss / NLL 等
9. calibration / ECE（样本允许时）
10. sample size + uncertainty / CI
11. competition/population slice
12. chronology / stability
13. failure taxonomy

Exact Score 额外：

- Top1 / Top3 / Top5
- Score NLL
- concentration / entropy
- 官方竞彩比分桶准确率（语义完成后）

命中率是重要的用户结果指标，但必须和 coverage 一起看：

> **不能通过只预测少量“容易场”把命中率做漂亮。**

因此长期同时评价 `Hit Rate @ Coverage / risk-coverage`。

---

# 4. Baseline Contract — 不能只比随机强

每个玩法优先和最接近的强基线比较。

- 1X2 → same-match de-vigged 1X2 / market favourite；
- handicap → 同一冻结 handicap line / market；
- goals → 同一 totals / category baseline；
- score → rights-clear correct-score market；
- HTFT → 同玩法市场（若合法可得）。

同时保留：

- Football-only
- Market-only
- Fusion

这样才能知道模型是真有足球增量，还是只是复制市场。

“比随机 33% / 50% 强”不能单独成为模型优秀证据。

---

# 5. Model Architecture — 共享底盘，但允许玩法专门优化

长期目标不是“一套 Poisson 包打天下”，也不是每个玩法完全割裂。

推荐结构：

`shared football / market features`
`→ authoritative full-time joint goal state`
`→ mathematically coherent derived FT markets`
`→ market-specific calibration/head when prospective evidence proves gain`

## 从 full-time joint score state 可自然推导

- FT 1X2
- double chance
- Exact Score / Top-N scenarios
- official score buckets
- total goals 0–7+
- O/U
- BTTS
- full-time handicap outcomes
- team totals / winning margin

## 可允许独立 market head / calibration

如果 fixed experiment + holdout + prospective evidence 证明某个玩法使用专门模型更准，可以拥有独立 head，例如：

- 1X2 classifier/calibrator
- goals classifier/calibrator
- BTTS classifier/calibrator
- handicap calibration

但必须继续检查与 authoritative score state 的冲突，不能为了命中率制造互相矛盾的产品结论。

## 必须独立建模的典型目标

- **半场 / HTFT**：不能简单 `90m lambda / 2`；先建立 first-half score/outcome truth、再建模/评价。
- corners / cards / player props：specialized event models。

---

# 6. Segmented Serving

正式 serving 单位：

`Market × Competition Support × Evidence Quality × Prediction Quality`

Competition：`SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED`

Evidence：`FULL / PARTIAL / INSUFFICIENT`

Serving：`NORMAL / CAUTION / DEGRADED / ABSTAIN`

一个玩法失败不得拖累其它玩法；其它玩法好也不得替它背书。

用户最终应该能够看到全部合法玩法概率，同时系统可以突出：

> **这场当前证据下，哪一个玩法是历史上最有把握的正式判断。**

这个“最佳玩法”必须来自历史 calibration / performance，不得硬编码永远是比分或胜平负。

---

# 7. Current Program

Public Launch 总门仍为：`PUBLIC-LAUNCH-TRUST`

但当前最大技术/产品发动机正式改为：

> **`MULTI-MARKET-PREDICTION-QUALITY`**

## Lane A — Multi-Market Prediction Quality | TECHNICAL P0

当前最重要的模型问题不再只问“Exact Score 怎么提高”，而是：

- 我们每个玩法现在到底多准？
- 全覆盖和精选分别多准？
- coverage 多大？
- 是否优于同玩法强基线？
- 哪些赛事最强/最弱？
- 哪些玩法已经可服务，哪些根本还没有 truth/evaluation chain？

Exact Score 仍是最大已知单项技术难题；Challenger C=`56 verified / PROMISING_NOT_ESTABLISHED / shadow-only`，后台自然积累到 >=100，不调参救显著性。

## Lane B — Prediction Proof / Trust / Serving | P0

职责：证明 Lane A 的成绩是真的。

包括：

- immutable freeze
- unique-match prospective ledger
- market-specific calibration
- coverage / abstain
- uncertainty
- market/simple benchmark
- failure taxonomy
- segmented serving

Trust 是证据层，不是替代模型表现的主产品。

## Lane C — User Decision Product / Trust Center

用户 30 秒内要知道：

- 这场各玩法怎么看；
- 哪个玩法当前最值得关注；
- 概率/比分情景；
- 数据是否完整；
- 风险与冲突；
- 哪些玩法应谨慎/abstain；
- 过去同类玩法/赛事真实表现。

Trust Center 必须以**逐玩法成绩表**为主体之一，而不是只有工程指标或一个“总命中率”。

## Lane D — Data / Identity / Rights | P0 FOUNDATION

当前 Issue #180 属于此 lane 的 bounded research preflight。

它只回答 Reep 是否能低成本解决 cross-provider identity 并恢复 correct-score benchmark probe；完成后不自动继续 identity 子树。

## Lane E — Operations / Reliability

Public Launch 前关闭 freshness、silent missing、settlement continuity、provider degradation、rollback/fail-safe、secret/log hygiene、stale-page detection。

## Lane F — Closed Beta / User Validation

模型不等完美才给真实用户，但要最小测量：用户看哪些玩法、是否理解概率/abstain、是否回看赛果、是否重复使用。

## Lane G — Compliance / Commercial

分析信息服务，不提供购彩交易/代购/充值/自动下注。数据 rights、宣传 claim、收费边界独立关闭。

## Lane H — Distribution / Business Model

Closed Beta 有信号以后再验证获客、复访、付费；不复制“红单/稳赚”叙事。

## Lane I — Advanced Model R&D

不再以“模型更高级”为理由启动。

启动条件改成：

`per-market measured failure → legal prematch inputs → population fit → fixed evaluation → prospective path`

---

# 8. Current Execution / Background

### Current bounded execution

Issue #180：`EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`

保持执行，不因本次 Roadmap correction 中断。

### Background

Challenger C 自然 prospective accumulation to >=100。

---

# 9. Post-#180 Highest-Value Candidate

这不是预授权 Issue；#180 完成后仍需完整 Project Gate。

当前外部研究后的最高候选变为：

## `MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT`

先回答：

1. 当前 frozen full-time score state 已经能准确推导哪些玩法？
2. 当前 90m result truth 已能合法结算哪些玩法？
3. 当前 unique prospective cohort 上，各玩法实际 hit rate / proper score 是多少？
4. 哪些玩法已有 strong/simple/market baseline？
5. 官方竞彩让球胜平负需要的 handicap line 是否已有合法 frozen truth？
6. 官方 0–7+ 总进球、比分桶是否只是缺 projection/evaluation，而不是缺模型？
7. HTFT 是否缺 first-half result truth？
8. strongest / weakest market 分别是谁？
9. 哪些问题是 evaluation/product gap，哪些才是真正 model-quality gap？

**没有这张地图以前，不默认造新模型。**

---

# 10. Public Launch Gate

Public Launch 至少要求：

1. 各一级玩法有明确 prediction-quality scorecard / serving state；
2. 不把一个玩法的好成绩包装成全产品成绩；
3. Competition support 可见；
4. Trust/prospective record 可审计；
5. Data/Rights 可接受；
6. Operations 可无人值守；
7. Compliance 边界关闭；
8. Closed Beta 证明真实重复价值；
9. release smoke 真实通过。

---

# 11. Anti-Patterns

以后不允许：

- 把 Trust Center 当成预测质量的替代品；
- 一个跨玩法“总命中率”；
- 只报精选命中率不报 coverage；
- 用 Double Chance/O1.5 等容易玩法抬高其它玩法声誉；
- 只和 random baseline 比；
- Exact Score 单项绑架整个产品；
- 因 Exact Score 难就降低它的一等能力地位；
- 永久把核心 market universe 缩成 1X2/O-U/BTTS/Exact；
- half-time 用 90m lambda/2 直接伪造；
- 为了玩法数量直接上模型而不先建 truth/evaluation；
- 一个 bounded Issue 完成后自动沿同技术树继续；
- 把历史 milestone 塞回 Roadmap。

---

# 12. Historical / Research Pointer

路线研究在 Memory-Hub：

- `RESEARCH/2026-09-04-MULTI-MARKET-PREDICTION-QUALITY-REBASE.md`
- `RESEARCH/2026-09-04-PRODUCT-ROADMAP-REBASE.md`
- 其它 Exact Score / identity / benchmark research assets。

历史 milestone 只从 Git history、Issues/PR/Actions、`docs/*` evidence 恢复，禁止复制回当前 Roadmap。

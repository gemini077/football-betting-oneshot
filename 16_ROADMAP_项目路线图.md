# 16_ROADMAP_项目路线图.md

最后更新：2026-09-04
状态：`CLEAN BASELINE / PRODUCT REBASE LOCKED`

角色：**只描述产品如何从当前状态走向可公开、可信、可持续使用。**

本文件不保存历史 milestone、不承担 Issue/PR 日志职责。长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. North Star

建立一个能够：

`自动发现比赛 → 形成可审计足球/市场证据 → 给出多玩法概率与比分情景 → 赛前冻结 → 明确表达置信度/风险 → 赛后自动验真 → 长期公开自身表现 → 持续 Challenger 改进`

的足球赛前决策产品。

核心差异化不是“也能预测比分”，也不是“有一个公开命中率页”，而是：

> **预测有依据、概率有边界、可靠性按场景可验证、错误可追溯、历史不能篡改、系统知道什么时候不该强猜。**

---

# 2. 战略判断

当前市场已经普遍具备 1X2、Correct Score、O/U、BTTS、统计、解释、历史结果等能力；越来越多新产品也开始公开完整 track record。

因此 FBOS 不应把以下内容单独视为护城河：

- 预测玩法数量；
- “AI 分析”；
- 单一比分；
- 公开历史记录；
- Football + Market fusion 本身。

真正要形成复利的是一个 **Prediction Trust System**：

`immutable ledger + segmented calibration + selective serving + benchmark + failure taxonomy + user trust loop`

随着 prospective 样本、赛事分层、错误类型和真实用户行为积累，这个系统会比单一模型版本更难复制。

---

# 3. 当前产品阶段

`LEVEL 4A — ENGINEERING CLOSED-BETA READY / TRUST-BETA MEASUREMENT PREP / PUBLIC LAUNCH NOT READY`

已经具备：

- 比赛发现 / Universe；
- canonical fixture / identity 主链；
- 足球 + 市场 evidence；
- Champion 多玩法概率；
- prematch freeze / 90m settlement / prospective ledger；
- Challenger shadow / promotion governance；
- Homepage + Match Detail + public Pages；
- Exact Score degraded-serving warning；
- 数据不足 / prediction failure / missed prematch 等 fail-closed 状态；
- 单场 postmatch verification；
- Closed Beta 边界文案。

但还不能称为“Product Beta measurement-ready”，因为当前仍缺：

- 可验证的用户置信度语义；
- 按玩法/赛事分层的 serving contract；
- 聚合 Trust Center；
- Closed Beta 最小行为/理解度测量；
- 完整 Public Launch rights / operations / compliance closure。

---

# 4. Core Product Contract — Segmented Trust Matrix

以后不再使用“整站预测可信 / 不可信”这种粗粒度概念。

正式 serving 单位至少由四个维度共同决定：

`Market × Competition Support × Evidence Quality × Prediction Quality`

## 4.1 Market

至少分别治理：

- `1X2`
- `O/U`
- `BTTS`
- `Exact Score`

一个玩法 DEGRADED 不得自动拖累其他玩法；其他玩法表现好也不得替 Exact Score 背书。

## 4.2 Competition Support

每个赛事/赛事族最终应明确属于：

- `SUPPORTED`
- `LIMITED`
- `EXPERIMENTAL`
- `UNSUPPORTED`

当前 mixed-universe、friendlies contamination 与小样本异质性已经证明：不能把所有比赛视为同一个 population。

## 4.3 Evidence Quality

至少区分：

- `FULL`
- `PARTIAL`
- `INSUFFICIENT`

来源 freshness、identity、recent form、market evidence、timing/provenance 必须共同影响 serving。

## 4.4 User-Facing Serving State

每个玩法最终映射为：

- `NORMAL`
- `CAUTION`
- `DEGRADED`
- `ABSTAIN`

规则必须由 prospective evidence / calibration / risk-coverage 验证，不允许拍脑袋阈值。

---

# 5. Current Program — PUBLIC-LAUNCH TRUST

当前产品级 Program 由并行 Gate 组成，不是模型优先的串行 Phase。

## Lane A — Prediction Trust

状态：`CURRENT / P0`

目标：让每个正式输出的 probability / score scenario 都有可解释的 prospective reliability。

当前：

- Exact Score 是最大技术 P0；
- Challenger C=`56 verified unique / PROMISING_NOT_ESTABLISHED / shadow-only`；
- C 后台自然积累到 >=100，禁止为显著性调参；
- external correct-score market benchmark 作为正交 benchmark lane，先过 identity/rights/coverage。

重点：

- proper scoring rule；
- calibration；
- uncertainty / stability；
- risk-coverage / selective serving；
- per-market × competition-tier performance；
- Champion / Market-only / Football-only / Fusion 分开比较。

## Lane B — User Trust / Decision Product

状态：`CURRENT / P0`

用户 30 秒内应知道：

- 这场怎么看；
- 最可能的比赛情景；
- 哪个玩法值得看、哪个玩法应谨慎；
- 系统有多大把握；
- 这种把握是否有历史依据；
- 支持证据与最大冲突；
- 什么情况下系统选择 abstain。

### 必须新增的产品原则

**Confidence 不能是主观“高/中/低”。**

只有当历史 prospective calibration / bucket reliability / sample uncertainty 能支持时，才允许显示用户置信度；否则显示 evidence state / uncertainty，而不是伪造精确 confidence。

Homepage 长期应成为真正的 Decision Queue：

- 默认帮助用户优先发现“证据最完整 / serving 最健康”的比赛；
- 仍允许查看全部比赛；
- 不再只按 kickoff 时间暗示所有比赛同等值得关注。

Match Detail 保持：

`30秒结论 → score scenarios → market probabilities → evidence → risk/conflict → prematch freeze → postmatch verification`。

## Lane C — Trust Center / Public Track Record

状态：`CURRENT DESIGN PRIORITY`

透明历史记录本身已逐渐商品化，因此 FBOS 的 Trust Center 必须比“命中率排行榜”更深。

最小目标：

- 所有 formal prematch predictions 可追溯；
- wins / losses / abstentions 都保留；
- per-market proper scores；
- calibration / reliability；
- sample size + uncertainty；
- per competition tier / regime；
- known weak spots；
- Champion vs market baseline / Challenger（治理允许时）；
- serving coverage：系统选择预测多少、放弃多少，以及放弃后风险是否真的更低。

不以 ROI 或单一 hit rate 作为产品真相。

## Lane D — Data / Identity / Rights

状态：`CURRENT / P0 FOUNDATION`

目标：identity 可审计、timing 可证明、coverage 可测、rights 清楚、provider 可替换。

当前 Issue #180 属于本 lane 的 bounded preflight，不是整个 Roadmap。

#180 完成后必须回项目 Gate。若 Reep 不能以低维护成本提供有用 exact bridge，不得仅为了外部 benchmark 无限建设 identity 基础设施。

## Lane E — Operations / Reliability

状态：`REQUIRED BEFORE PUBLIC LAUNCH`

需要关闭：

- business-date / daily freshness；
- silent missing；
- result/settlement continuity；
- provider degradation observability；
- durable write / rollback；
- fail-safe / stale-page protection；
- secret/log hygiene；
- monitoring / incident boundary。

一次 Actions SUCCESS 不等于可运营。

## Lane F — Closed Beta / User Validation

状态：`NEXT PRODUCT MATURITY GATE`

不等待模型完美，但在邀请真实用户前先完成**最小测量能力**。

至少需要观察：

- 首页 → 单场详情 activation；
- score scenario / probability comprehension；
- evidence expansion；
- Trust Center usage；
- postmatch return；
- serving / abstain 是否被正确理解；
- 哪些玩法与赛事真正被反复使用；
- 用户为什么第二天/下周还会回来。

优先零现金、小样本真实用户验证；不为了 analytics 先搭重型账户体系。

## Lane G — Compliance / Commercial Readiness

状态：`REQUIRED BEFORE PUBLIC COMMERCIALIZATION`

保持分析信息服务边界：不提供彩票交易、代购、出票、充值、自动下注。

必须关闭：

- critical data source commercial-use / storage / display / redistribution rights；
- 中国市场宣传 claim policy；
- accuracy / calibration / “best” 等引证数据的出处、样本、适用范围；
- responsible-use / 未成年人边界；
- 若以后引入账号、支付、用户数据，再单独过 privacy/security/payment gate。

## Lane H — Distribution / Business Model

状态：`DISCOVERY AFTER CLOSED-BETA SIGNAL / NOT LOCKED`

旧 Roadmap 基本没有回答“用户怎么来、为什么回来、以后为什么付费”。现在补上，但不提前锁死商业模式。

当前研究只形成假设：

- 不与 FotMob/懂球帝争通用新闻、比分、社区广度；
- 公开 track record / methodology / completed reviews 很可能应该长期保持免费，作为信任获客资产；
- future predictions、完整 evidence、advanced filtering/alerts 等可以作为未来付费候选，但必须先由 Closed Beta willingness-to-pay 和 Compliance Gate 验证；
- 不因竞品普遍卖 VIP picks 就复制“红单/稳赚”叙事。

## Lane I — Advanced Model R&D

状态：`SUPPORTING / DEMAND-TRIGGERED`

只有满足：

`measured failure mode + legal prematch input + population fit + fixed evaluation plan + prospective path`

才启动新模型。

候选包括 hierarchical team strength、richer score distribution、xG、lineup/injury、rest/travel、set-piece 等；“更高级”本身不是理由。

---

# 6. Current Execution / Background

### Bounded execution
- Issue #180：Reep cross-source identity + correct-score benchmark preflight。

### Background
- Challenger C：自然 prospective accumulation to >=100。

### Product-level work
- Roadmap Rebase 已形成战略结论；后续每个 bounded issue 完成后都回 `PUBLIC-LAUNCH TRUST` 全局 Gate。

三者不能互相冒充。

---

# 7. Public Launch Gate

Public Launch 至少同时要求：

1. **Prediction Trust**：各正式玩法有独立 serving state；没有已知严重 collapse 被包装成 NORMAL；
2. **Competition Support**：用户知道哪些赛事是 SUPPORTED / LIMITED / EXPERIMENTAL；
3. **User Trust**：结论、概率、风险、confidence/uncertainty、abstain 能被理解；
4. **Trust Center**：历史 formal record、样本、弱点与 benchmark 可审计；
5. **Data/Rights**：critical sources rights 可接受；
6. **Operations**：持续无人值守运行并 fail visibly/safely；
7. **Compliance**：交易、宣传、数据与商业边界明确；
8. **Closed Beta Evidence**：真实用户核心 journey 有重复价值；
9. **Release Smoke**：真实公开环境端到端通过。

---

# 8. Product Metrics

## Prediction
- per-market NLL / Brier / LogLoss；
- Exact Top1/3/5；
- calibration / ECE；
- risk-coverage / selective quality；
- competition-tier stability。

## Evidence / Operations
- formal usable coverage；
- NORMAL / CAUTION / DEGRADED / ABSTAIN coverage；
- settlement coverage；
- identity ambiguity；
- freshness / silent missing。

## User
- detail activation；
- evidence expansion；
- Trust Center usage；
- postmatch return；
- repeat weekly use；
- probability / abstention comprehension。

## Business（Beta 形成信号后）
- repeat users；
- willingness-to-pay；
- conversion hypothesis；
- data/tool cost per active user；
- founder maintenance burden。

---

# 9. Anti-Patterns

以后不允许：

- 把历史 milestone 塞回 Roadmap；
- 把 Issue 当产品 Phase；
- Exact Score 一个玩法拖住整个产品，或反过来用 1X2 表现替比分背书；
- 用未经验证的“高/中/低信心”制造确定感；
- 所有赛事共享同一个可靠性标签；
- 一个局部任务完成后自动沿同技术树继续；
- 为竞品 feature parity 去造新闻/社区/全量 live-score 门户；
- 把公开 track record 当成唯一护城河；
- 把“数据能抓到”当成“商用权利已解决”；
- 把版本行当独立比赛样本；
- 为了收费提前复制 VIP/红单/稳赚叙事。

---

# 10. Historical Archive Pointer

旧 Roadmap 全量历史只从 Git history、Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub Research Assets 恢复。

**Current Roadmap 只允许保存仍影响产品未来的战略真相。**

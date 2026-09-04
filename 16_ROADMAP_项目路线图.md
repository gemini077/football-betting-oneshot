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

# 2. 玩法宇宙

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

O/U、BTTS、Asian/common handicap、team totals、winning margin、double chance。

## Tier C — Specialized Future

corners / cards / player props 等，只在用户需求、合法赛前数据、可结算 truth、独立 evaluation 均成立时进入。

---

# 3. Prediction Quality Scorecard

禁止一个跨玩法 blended “overall accuracy”。不同玩法难度不同，把 Double Chance、O1.5、Exact Score 混成一个数字会失真。

每个玩法单独建立成绩表：

1. `eligible unique matches`
2. `settled unique matches`
3. full-coverage Top1 hit rate
4. served hit rate
5. served coverage / abstain rate
6. same-market baseline hit rate
7. delta vs baseline
8. proper score：Brier / LogLoss / NLL 等
9. calibration / ECE（样本允许时）
10. sample size + uncertainty / CI
11. competition / population slice
12. chronology / stability
13. **forecast horizon / freeze lead-time**
14. failure taxonomy

Exact Score 额外：Top1 / Top3 / Top5、Score NLL、concentration / entropy、官方竞彩比分桶准确率（语义完成后）。

命中率是一级用户结果指标，但必须和 coverage 一起看。

> **不能通过只预测少量“容易场”把命中率做漂亮。**

长期同时评价 `Hit Rate @ Coverage / risk-coverage`。

---

# 4. Baseline Contract

每个玩法优先和最接近的强基线比较：

- 1X2 → same-match de-vigged 1X2 / market favourite；
- handicap → 同一冻结 handicap line / market；
- goals → 同一 totals / category baseline；
- score → rights-clear correct-score market；
- HTFT → 同玩法市场（若合法可得）。

同时保留 Football-only / Market-only / Fusion。

“比 random 33% / 50% 强”不能单独成为模型优秀证据。

### Forecast Horizon 公平性

- T-24h、T-6h、T-60m 等不是同一个信息集；
- 先审 current `minutes_to_kickoff_at_freeze` 分布，再锁 horizon bins；
- 同一 match 的多个 horizon 是 repeated paired forecasts，不是多个独立样本；
- 早期 FBOS forecast 优先与同一时点或更早的 market snapshot 比；
- closing market 可作为最终信息 benchmark，但不能冒充 equal-information control。

---

# 5. Model Architecture

长期目标不是“一套 Poisson 包打天下”，也不是每个玩法完全割裂。

推荐结构：

`shared football / market features`
`→ authoritative full-time joint goal state`
`→ mathematically coherent derived FT markets`
`→ market-specific calibration/head when prospective evidence proves gain`

共同 score state 可自然推导 FT 1X2、double chance、Exact Score、official score buckets、0–7+ goals、O/U、BTTS、full-time handicap、team totals / winning margin。

若 1X2 / Goals / BTTS / handicap 使用独立 head，必须 fixed experiment + holdout + prospective evidence 证明对应玩法增益，同时检查与 authoritative score state 的显著冲突。

HTFT 不能简单 `90m lambda / 2`；corners/cards/player props 属于 specialized model lane。

---

# 6. Feature Incremental Value Gate

任何 rich feature /复杂模型都必须证明增量，而不是因为“更高级”直接接入。

适用于 xG/xT、shot quality、lineup/player、injury、manager、weather、travel/rest、NLP/news、GNN/embeddings 等。

必须走：

`time-safe acquisition`
`→ paired current control`
`→ fixed +feature ablation`
`→ chronological holdout`
`→ coverage / competition audit`
`→ prospective shadow if promising`

核心问题：

> 在相同比赛、相同赛前截止时点上，它相对当前 Champion 和 closest same-time strong market baseline 增加了什么？

解释性增益不自动等于预测增益；rich-data feature 也不能把广覆盖产品拖成只剩少量比赛可用。

---

# 7. Class-Balance / Anti-Favourite Gate

1X2 不得只看 overall accuracy。

至少同时审：

- Home / Draw / Away predicted class mix；
- actual class mix；
- confusion matrix；
- per-class recall；
- Draw recall；
- multiclass Brier / LogLoss；
- RPS 可作为附加 ordinal metric；
- class-wise calibration（样本允许时）。

防止“永远猜热门 / 几乎不猜平局”获得漂亮 accuracy。

其它多类玩法同理：0–7+ 关注尾部类别，HTFT 关注九类失衡。

---

# 8. Segmented Serving

正式 serving 单位：

`Market × Competition Support × Forecast Horizon × Evidence Quality × Prediction Quality`

Competition：`SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED`

Evidence：`FULL / PARTIAL / INSUFFICIENT`

Serving：`NORMAL / CAUTION / DEGRADED / ABSTAIN`

一个玩法失败不得拖累其它玩法；其它玩法好也不得替它背书。

用户可看到全部合法玩法概率，同时系统最终可突出：

> **这场当前证据下，哪一个玩法是历史上最有把握的正式判断。**

这个“最佳玩法”必须来自历史 calibration / performance，不得硬编码永远是比分或胜平负。

---

# 9. Current Program

Public Launch 总门仍为：`PUBLIC-LAUNCH-TRUST`

当前最大技术/产品发动机：`MULTI-MARKET-PREDICTION-QUALITY`

## Lane A — Multi-Market Prediction Quality | TECHNICAL P0

当前最重要的问题：

- 每个玩法到底多准？
- 全覆盖和精选分别多准？
- coverage 多大？
- 是否优于同玩法、同时点强基线？
- 哪些赛事 / horizon 最强或最弱？
- 1X2 是否存在 draw/class collapse？
- 哪些高级 feature 真有增量？
- 哪些玩法其实只是缺 projection / truth / evaluation，而不是缺模型？

Exact Score 仍是最大已知单项技术难题；C=`56 verified / PROMISING_NOT_ESTABLISHED / shadow-only`，后台自然积累到 >=100，不调参救显著性。

## Lane B — Prediction Proof / Trust / Serving | P0

immutable freeze、unique-match prospective ledger、market-specific calibration、coverage/abstain、uncertainty、benchmark、failure taxonomy、segmented serving。

## Lane C — User Decision Product / Trust Center

用户 30 秒内知道各玩法怎么看、哪个玩法当前最值得关注、概率/比分情景、风险/冲突、哪些玩法谨慎/abstain、过去同玩法/同赛事表现。

## Lane D — Data / Identity / Rights | P0 FOUNDATION

Issue #180 属于此 lane 的 bounded research preflight；完成后不自动继续 identity 子树。

## Lane E — Operations / Reliability

Public Launch 前关闭 freshness、silent missing、settlement continuity、provider degradation、rollback/fail-safe、secret/log hygiene、stale-page detection。

## Lane F — Closed Beta / User Validation

真实验证用户看哪些玩法、是否理解概率/abstain、是否回看赛果、是否重复使用。

## Lane G — Compliance / Commercial

分析信息服务，不提供购彩交易/代购/充值/自动下注。数据 rights、宣传 claim、收费边界独立关闭。

## Lane H — Distribution / Business Model

Closed Beta 有信号以后再验证获客、复访、付费；不复制“红单/稳赚”叙事。

## Lane I — Advanced Model R&D

只有：`per-market measured failure → legal prematch inputs → population fit → fixed evaluation → prospective path` 才启动。

---

# 10. Current Execution / Background

### Current bounded execution

Issue #180：`EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`

保持执行，不因 Roadmap correction 中断。

### Background

Challenger C 自然 prospective accumulation to >=100。

---

# 11. Post-#180 Highest-Value Candidate

这不是预授权 Issue；#180 完成后仍需完整 Project Gate。

当前最高候选：

## `MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT`

先回答：

1. current frozen full-time joint score state 已经能准确推导哪些玩法？
2. current result truth 已能合法结算哪些玩法？
3. current unique prospective cohort 上，各玩法 hit rate / proper score / coverage 是多少？
4. 哪些玩法已有 same-market / same-horizon baseline？
5. actual freeze lead-time 分布怎样，是否能形成 horizon scorecard？
6. 1X2 Home/Draw/Away class mix / recall 是否健康？
7. 官方竞彩让球胜平负需要的 handicap line 是否已有合法 frozen truth？
8. 官方 0–7+、比分桶是否只是缺 projection/evaluation？
9. HTFT 是否缺 first-half result truth？
10. rich-feature coverage / potential ablation surface 已有哪些？
11. strongest / weakest market 分别是谁？
12. 哪些是 evaluation/product/data gap，哪些才是真正 model-quality gap？

**没有这张地图以前，不默认造新模型。**

---

# 12. Public Launch Gate

Public Launch 至少要求：

1. 各一级玩法有明确 prediction-quality scorecard / serving state；
2. 不把一个玩法的好成绩包装成全产品成绩；
3. Forecast Horizon 与 baseline 比较公平；
4. 1X2 / 多类玩法无隐藏 class collapse；
5. Competition support 可见；
6. Trust/prospective record 可审计；
7. Data/Rights 可接受；
8. Operations 可无人值守；
9. Compliance 边界关闭；
10. Closed Beta 证明真实重复价值；
11. release smoke 真实通过。

---

# 13. Anti-Patterns

以后不允许：

- 把 Trust Center 当成预测质量替代品；
- 一个跨玩法“总命中率”；
- 只报精选命中率不报 coverage；
- 用容易玩法抬高其它玩法声誉；
- 只和 random baseline 比；
- T-24h forecast 和 T-0 closing market 当同信息条件比较；
- overall 1X2 accuracy 掩盖不猜 Draw；
- “xG/阵容/球员/GNN 更高级所以一定更准”；
- Exact Score 单项绑架整个产品；
- 因 Exact Score 难就降低它的一等能力地位；
- 永久把核心 market universe 缩成 1X2/O-U/BTTS/Exact；
- half-time 用 90m lambda/2 直接伪造；
- 为玩法数量直接上模型而不先建 truth/evaluation；
- 一个 bounded Issue 完成后自动沿同技术树继续；
- 把历史 milestone 塞回 Roadmap。

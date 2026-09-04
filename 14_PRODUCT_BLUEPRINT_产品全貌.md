# 14_PRODUCT_BLUEPRINT_产品全貌.md

最后更新：2026-09-04
状态：`CURRENT NORTH STAR / CLEAN V2`

角色：描述 Football Betting OneShot **最终要造什么**。不是任务清单，不保存 milestone、Issue/PR 日志或临时实验结论。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. 一句话产品定义

Football Betting OneShot 是一个面向中国用户的：

> **足球信息 + 市场信息 + 多玩法赛前概率预测 + 可审计赛后验证的决策支持产品。**

核心用户价值不是“AI 分析”或“有一个比分模型”，而是：

> **在用户真正关心的足球玩法上持续提高预测命中率与概率质量，并且能证明这些成绩不是靠挑样本、赛后改答案、永远猜热门或只挑容易玩法得到的。**

Prediction Quality 是发动机。

Freeze / Benchmark / Calibration / Trust / Selective Serving 是证明和交付发动机性能的系统，不能替代预测能力本身。

产品不是彩票交易、代购、出票、充值、自动下注或官方彩票机构服务。

---

# 2. 产品为什么存在

现有足球产品通常只解决部分问题：

- 新闻/数据很多，但不给明确概率判断；
- 给预测，但不公开完整长期成绩；
- 只宣传“命中率”，却不说覆盖率、玩法难度和样本；
- 一个模型同时硬推所有玩法，局部失真被总成绩掩盖；
- 赔率很强，但普通用户不知道模型到底增加了什么；
- 输的预测、失败赛事、模型弱点往往不可追溯。

FBOS 要形成完整闭环：

`比赛发现`
`→ canonical identity`
`→ 足球证据 + 市场证据`
`→ 多玩法概率状态`
`→ 赛前冻结`
`→ 用户决策表达`
`→ 90m / 对应玩法结果真相`
`→ 逐玩法 prospective evaluation`
`→ Challenger / calibration / serving 改进`

---

# 3. 核心产品目标：Multi-Market Prediction Quality

禁止用一个跨玩法 blended “overall accuracy”代表模型水平。

每个正式玩法独立回答：

- 全覆盖时命中率多少？
- 精选/正式 serving 后命中率多少？
- 覆盖了多少比赛？
- 与同玩法强 baseline 相比怎样？
- 概率本身是否可靠？
- 哪些赛事/时点/数据状态更强或更弱？

最低 Scorecard：

`Full-Coverage Hit Rate`
`+ Served Hit Rate`
`+ Served Coverage / Abstain Rate`
`+ Same-Market Baseline`
`+ Delta vs Baseline`
`+ Proper Score`
`+ Calibration`
`+ Sample Size / CI`
`+ Competition / Regime Scope`
`+ Forecast Horizon`

Exact Score 额外：Top1 / Top3 / Top5、Score NLL、score concentration / entropy。

命中率是一级用户结果指标，但不能脱离 coverage、baseline 与 probability quality 单独解释。

---

# 4. 玩法宇宙

## 4.1 Tier A — 中国竞彩第一等目标

长期必须覆盖并分别治理：

1. **胜平负 / FT 1X2**
2. **让球胜平负** — 必须绑定并冻结对应官方让球线
3. **比分** — raw score distribution + 官方竞彩比分结果桶
4. **总进球数 0–7+**
5. **半全场胜平负** — 需要 first-half truth 与 dedicated model/evaluation lane

混合过关是 downstream composition，不是独立预测模型 target。

## 4.2 Tier B — 国际 / 分析型核心补充

- O/U lines
- BTTS
- Asian/common handicap
- team totals
- winning margin
- double chance

它们仍有真实用户价值，但不能挤掉中国目标市场真正的一等玩法。

## 4.3 Tier C — Specialized Future

- corners
- cards
- player props
- other event markets

只有当 `用户需求 + 合法数据 + prematch timing + settlement truth + evaluation` 都成立时进入。

---

# 5. 模型架构原则：共享底层，不强迫一套模型包打天下

长期优先架构：

`Football latent state`
`+ Market latent state`
`+ Competition / Home-Away / Context`
`→ authoritative full-time joint score state`
`→ coherent full-time market projections`
`→ market-specific calibration/head when evidence proves gain`

共同 full-time score state 可数学一致地推导：

- 1X2
- exact score / score scenarios
- official correct-score buckets
- total goals 0–7+
- O/U
- BTTS
- common handicap outcomes
- team totals / winning margin / double chance

但：

> **一个数学上统一的 Poisson/score grid，不等于它必须是每个玩法预测质量最好的最终模型。**

如果 prospective evidence 证明独立 1X2 / goals / BTTS / handicap head 能稳定改善对应玩法，允许使用 market-specific calibration/head，同时保持逻辑一致性审计。

HTFT 不允许机械用 `90m lambda / 2` 生成；半场、角球、牌、球员等 specialized target 使用独立真相与模型链。

当前 Champion 只是 production baseline，不定义未来架构。

---

# 6. Football 与 Market 的关系

正式目标不是“模型对抗赔率”，而是区分并验证：

- `Football-only`
- `Market-only`
- `Fusion`

原因：

- 市场本身是非常强的预测系统；
- 模型不能因为比 random 好就自称优秀；
- 也不能因为使用市场后变准，就误称全部增量来自足球分析。

每个玩法优先寻找 closest same-market baseline。

Forecast Horizon 必须公平：

- T-24h / T-6h / T-60m 等不同信息集不能混成一份成绩；
- 早期 FBOS forecast 优先与同一时点或更早的 market snapshot 比较；
- closing market 可以作为最强 final-information benchmark，但必须明确它拥有更多晚期信息。

同一场不同 horizon 的预测是 repeated forecasts，不是多场独立样本。

---

# 7. Feature Incremental Value Gate

任何“更高级”的输入都不是自动升级理由。

适用于：

- xG / xT / shot quality / VAEP / OBV
- lineup / player strength / player form
- injury / suspension
- manager / tactics
- rest / travel / weather
- NLP/news/social signals
- GNN / embeddings / deep representation

必须经过：

`time-safe acquisition`
`→ paired current-control comparison`
`→ fixed +feature ablation`
`→ chronological holdout`
`→ coverage / competition audit`
`→ prospective shadow if promising`

核心问题：

> 在相同比赛、相同赛前信息截止时点上，这个特征相对当前 Champion 和强 market baseline 增加了什么？

解释性增强不自动等于预测质量增强。

Rich-data features 只在稳定覆盖赛事启用，不能为了高级输入让整个产品失去广覆盖能力。

---

# 8. Competition / Population Gate

不能把所有比赛当成同一个 population。

至少区分：

- Big-5 / top
- other top
- lower / small league
- domestic cup
- continental club
- national friendly
- national qualifier / nations
- national major tournament
- unknown / mixed

还需要长期观察：

- early season / cold start
- promoted/newly-covered teams
- major manager/roster regime shift
- fixture congestion / special tournament format

先证明错误在哪个 population 集中，再针对性建模；不能先发明 penalty。

---

# 9. 1X2 与多类别反作弊

Overall accuracy 不能掩盖类别塌陷。

1X2 至少同时监控：

- Home / Draw / Away predicted share
- actual share
- confusion matrix
- per-class recall
- Draw recall
- multiclass Brier / LogLoss
- RPS 可作为附加 ordinal metric
- class-wise calibration（样本允许时）

避免模型靠“永远猜热门”“几乎不猜平局”获得漂亮 accuracy。

其它多类玩法同理：0–7+ 关注尾部类别；HTFT 关注九类失衡。

---

# 10. Selective Serving

产品不要求每场每个玩法都强行给主推。

正式 serving 最小单位：

`Market × Competition Support × Forecast Horizon × Evidence Quality × Prediction Quality`

Competition Support：

- SUPPORTED
- LIMITED
- EXPERIMENTAL
- UNSUPPORTED

Evidence Quality：

- FULL
- PARTIAL
- INSUFFICIENT

Serving State：

- NORMAL
- CAUTION
- DEGRADED
- ABSTAIN

一个玩法失败不得拖累其它玩法；其它玩法强也不得替弱玩法背书。

任何“精选命中率”必须同时显示或可追溯 coverage，否则没有意义。

---

# 11. 用户产品形态

## 11.1 首页：Today Decision Queue

首页不是工程 dashboard，也不是所有比赛/玩法等权重的信息墙。

用户首先需要知道：

- 今天哪些比赛值得看；
- 每场当前最强的预测观点是什么；
- 哪个玩法是该场最可靠/最有信息价值的；
- 系统是否没有强观点；
- 数据/预测状态是否完整。

每场仍保留完整多玩法概率，但主卡长期应突出**经历史验证当前最强的 supported market/view**，而不是永远硬编码 Exact Score 或 1X2。

如果没有玩法过 serving Gate，应明确 `ABSTAIN / 无强观点`。

## 11.2 单场详情：Decision Dossier

30 秒内回答：

- 主判断；
- 当前最强玩法；
- 其它主要玩法概率；
- Score scenarios；
- 证据与市场是否一致；
- 最大风险 / 冲突；
- 数据/预测状态；
- 该类判断过去表现。

随后展开：

`强弱 → 节奏 → 得分路径 → 分叉 → 市场状态 → 完整证据 → 冻结真相 → 赛后验证`

内部 model family、文件路径、checkpoint jargon 默认折叠。

---

# 12. Trust Center 的正确位置

Trust Center 不是产品发动机，也不是“命中率战报”。

它负责证明 Multi-Market Prediction Quality 真实存在。

样本允许时展示：

- formal frozen prediction count
- settlement coverage
- per-market hit rate
- served hit rate + coverage
- proper scores
- calibration / reliability
- sample / CI
- forecast horizon
- competition / regime
- class-balance diagnostics
- market/simple baseline
- known weak spots
- abstain effectiveness
- Champion / Challenger（治理允许时）

wins / losses / abstentions 都保留。

失败月份和弱赛事不能为了营销被隐藏。

---

# 13. Immutable Prediction

正式预测必须保存：

- fixture identity
- source cutoff
- freeze timestamp / minutes-to-kickoff
- input snapshot / provenance
- model identity
- probabilities
- joint score state
- market-specific calibrated outputs（若存在）
- source/model fingerprints

赛后只能追加结果与评价，不能改写赛前答案。

`one football match = one observation`。

版本/不同 horizon 只作为 paired/repeated audit truth，不能放大 independent sample。

---

# 14. Data / Identity / Rights

长期需要：

- canonical competition identity
- canonical team identity
- canonical fixture identity
- provider crosswalk
- deterministic fail-closed binding
- source freshness / completeness
- prematch timing proof
- commercial-use / storage / display / redistribution boundary
- provider replacement strategy

原则：

> 宁可 UNKNOWN，也不能 fuzzy 猜错球队。

技术可访问不等于可商业复用。

---

# 15. Research / Challenger

任何模型或 feature 升级：

`External/Internal Research`
`→ Applicability Gate`
`→ fixed hypothesis`
`→ historical chronological holdout / replay`
`→ paired baseline comparison`
`→ prospective shadow`
`→ unique-match evaluation`
`→ independent Promotion Review`

不得因为：

- 新论文；
- 更复杂；
- 短窗口漂亮；
- 某个比分看起来更合理；
- 同一 cohort 多次扫描；

就进入 production。

---

# 16. Operations / Automation

长期自动链：

`发现比赛`
`→ Identity`
`→ Evidence`
`→ Multi-Market Prediction`
`→ Freeze`
`→ Site`
`→ Result Truth`
`→ Per-Market Evaluation`
`→ Monitoring`
`→ Challenger Review`

系统健康至少覆盖：

- Universe / freshness / silent missing
- identity / provider degradation
- freeze continuity
- prediction concentration / class collapse
- settlement continuity
- Pages freshness
- secrets / logs
- durable write / rollback
- fail-safe / stale protection

一次 Actions SUCCESS 不等于长期可运营。

---

# 17. Closed Beta / User Validation

不用等模型“最终完成”才让真实用户使用，但必须明确未成熟玩法与 uncertainty。

Closed Beta 最低成本验证：

- 首页是否能快速找到值得看的比赛；
- 用户实际反复看哪些玩法；
- “最强观点 / 无强观点”是否容易理解；
- score scenarios / probability 是否被理解；
- evidence 是否有价值；
- 用户是否赛后回来；
- 用户第二天/下一周为什么继续使用；
- 哪些赛事/玩法真的形成需求。

用户喜欢不等于模型可信；模型可信也不等于产品成立。

---

# 18. Betting Decision Layer

EV、value、stake sizing、串关、portfolio 是预测之后的 downstream layer。

只有当：

`概率可信 + calibration 可验证 + executable price + compliance`

才考虑提升其产品优先级。

当前产品不以自动投注执行为核心。

---

# 19. Compliance / Commercial

面向中国用户保持分析与信息服务边界：

- 不在线售彩；
- 不代购/出票/充值；
- 不自动下注；
- 不宣传稳赚/保证收益；
- accuracy / historical-performance claim 必须可审计并注明样本与适用范围；
- 数据源商业权利独立验收；
- 未来账号/支付/用户数据另过 privacy/security/payment Gate。

---

# 20. 产品不是什么

FBOS 不是：

- 每天随便给几个比分的预测器；
- 一个 Poisson 模型包打天下；
- 用 Double Chance / O1.5 拉高“综合命中率”的营销站；
- 只押热门、不预测平局却声称高准确率的分类器；
- 只展示赢单的 tipster 页面；
- 新闻/live-score/社区大而全门户；
- 通过赛后修改答案制造成绩的系统；
- 自动下注机器人。

---

# 21. 产品建设优先级

任何新需求先问：

1. 它是否提高某个正式玩法的真实预测质量？
2. 是否有同玩法 baseline、固定评价方法和 prospective path？
3. 是 model gap，还是 projection / settlement / data / rights gap？
4. 是否提高核心玩法覆盖，而不是只提高少量 rich-data 比赛？
5. 用户是否真实需要？
6. 是否已有免费/稳定/开源能力可复用？
7. 是否会让产品更复杂却没有 measurable value？

如果只是“看起来高级”，默认延后。

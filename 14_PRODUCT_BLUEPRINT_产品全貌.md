# 14_PRODUCT_BLUEPRINT_产品全貌.md

最后更新：2026-09-04
状态：`CURRENT NORTH STAR / CLEAN V3`

角色：描述 Football Betting OneShot **最终要造什么**。不是任务清单，不保存 milestone、Issue/PR 日志或临时实验结论。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. 一句话产品定义

Football Betting OneShot 是一个面向中国用户的：

> **赛前足球理解 + 多玩法概率预测 + 市场对照 + 可审计赛后验证的决策支持产品。**

它长期同时完成两个 Job：

1. **Match Understanding｜帮助想了解赛事的人更懂这场球**：强弱、节奏、得分路径、关键分叉、市场怎么看、什么信息可能改变判断。
2. **Prediction Decision Support｜帮助有竞彩足球或其它合法足球投注决策需求的人获得更高质量的赛前判断**：逐玩法给出可验证概率、首选结果、风险与适用范围。

其中：

> **Exact Score / 比分 / 波胆是旗舰玩法。**

它应获得最深的模型研究、概率分布、Top-k 场景和历史验证，但不是唯一玩法，也不得再次绑架整个产品路线。

核心用户价值不是“AI 分析”或“有一个 Poisson 模型”，而是：

> **在用户真正关心的玩法上持续提高真实命中率与概率质量，并证明这些成绩不是靠挑样本、赛后改答案、只猜热门、只挑容易玩法或把近似命中冒充精确命中得到的。**

Prediction Quality 是发动机。

Historical Football Memory、Market Prior、Freeze、Benchmark、Calibration、Trust、Selective Serving 是让发动机变强、证明它变强并可靠交付的系统。

产品不是彩票交易、代购、出票、充值、自动下注或官方彩票机构服务。

---

# 2. 产品闭环

长期闭环：

`比赛发现`
`→ canonical identity`
`→ Historical Football Memory`
`→ 当前足球证据 + 同时点市场证据`
`→ 多玩法概率状态 / joint score state`
`→ 赛前冻结`
`→ 用户赛事理解 + 预测决策表达`
`→ 90m / 对应玩法结果真相`
`→ 逐玩法 prospective evaluation`
`→ Challenger / calibration / serving 改进`

用户不应该只得到一个“推荐”。

用户应该能回答：

- 这场更可能怎么踢？
- 哪个玩法当前最稳？
- 比分/波胆最可能是什么，Top3/Top5 场景是什么？
- 模型和市场哪里一致、哪里分歧？
- 哪个结论只是低置信度场景？
- 哪些信息最可能推翻当前判断？
- 过去同玩法、同赛事、同时点，系统究竟表现怎样？

---

# 3. 技术主轴：Multi-Market Prediction Quality

禁止使用跨玩法 blended “overall accuracy”。

每个正式玩法独立回答：

`Full-Coverage Hit Rate`
`+ Served Hit Rate`
`+ Served Coverage / Abstain Rate`
`+ Same-Market / Same-Horizon Baseline`
`+ Delta vs Baseline`
`+ Proper Score`
`+ Calibration`
`+ Sample Size / CI`
`+ Competition / Regime`
`+ Forecast Horizon`
`+ Stability / Drift`

命中率是一级用户结果指标，不能因为强调 Brier/NLL 就把“到底猜对多少”藏起来。

同样，命中率不能脱离 coverage、赔率难度、baseline 与概率质量单独宣传。

---

# 4. Exact Score / 波胆旗舰契约

Exact Score 是最高优先级技术玩法之一。

## 4.1 严格命中定义

- Top1 Exact Score：只有 90 分钟含伤停的双方进球数完全一致才算命中；
- Top3 / Top5：只有真实比分位于冻结候选集合才算命中；
- “差一球”“方向对”“总进球对”只能作诊断，不能冒充波胆命中。

## 4.2 最低评价

- Top1 / Top3 / Top5 hit rate；
- Score NLL；
- actual-score rank；
- score concentration / entropy；
- Top-k cumulative predicted probability vs observed Top-k coverage；
- home-goal / away-goal error；
- total-goal / goal-difference / 1X2 / BTTS structural diagnostics；
- 同赛事/同时点 baseline。

## 4.3 Exact Score baseline ladder

至少逐步比较：

1. global common-score baseline；
2. competition/era-specific modal-score baseline（严格只用目标比赛之前的数据）；
3. historical dynamic attack/defence baseline；
4. same-horizon market-implied score matrix；
5. current Champion / Challenger；
6. rights-clear direct correct-score market baseline（可得时）。

如果连简单常见比分或市场隐含 MAP 都不能稳定超过，不得通过模型复杂度包装成“高质量波胆”。

## 4.4 用户表达

每场可以保留完整 score distribution 供赛事理解；

但“强波胆观点”只有在 Exact Score 自己的 serving Gate 通过时才突出。

长期用户至少看到：

- 唯一中心比分 / Top1；
- Top3 / Top5；
- 每个比分概率；
- Top-k 累计概率；
- 比分适用状态：NORMAL / CAUTION / DEGRADED / ABSTAIN；
- 当前最大的比分分叉与失效条件。

---

# 5. 玩法宇宙

## Tier A — 中国竞彩足球第一等目标

1. **胜平负 / FT 1X2**
2. **让球胜平负** — 必须冻结对应官方让球线
3. **比分 / Exact Score** — raw score distribution + 官方比分结果桶
4. **总进球数 0–7+**
5. **半全场胜平负** — 必须先有 first-half truth 与 dedicated model/evaluation lane

混合过关是 downstream composition，不是独立模型 target。

## Tier B — 国际 / 分析型核心补充

- O/U lines
- BTTS
- Asian/common handicap
- team totals
- winning margin
- double chance

## Tier C — Specialized Future

corners / cards / player props 等，只在 `用户需求 + 合法数据 + prematch timing + settlement truth + evaluation` 全部成立时进入。

---

# 6. 训练样本与正式证明样本必须分开

这是长期硬规则。

## Historical Training / Research Sample

可以通过合法历史比赛大幅扩张，用于：

- dynamic team attack/defence；
- league/competition scoring environment；
- home advantage；
- opponent adjustment；
- promoted/new-team priors；
- generic score-shape / tail behaviour；
- historical chronological holdout。

## Formal Prospective Proof Sample

只能由未来真实赛前冻结比赛逐场增长，用于：

- 证明完整 production 链在未来真实成立；
- 证明当前数据时点、市场时点、identity 与 serving 都没有 hindsight；
- Promotion / calibration / public claims。

历史扩到 100,000 场，也不能把 56 场 prospective 写成 100,056 场。

bootstrap / Monte Carlo / synthetic outcomes 只能做不确定性或模拟，不能创造独立真实比赛。

---

# 7. Historical Football Memory｜长期上游底座

当前 production Champion 的 Football-side 主要依赖近期主客场/整体进失球与当前市场；它不是一个大历史长期球队状态模型。

长期架构必须显式加入：

`Historical Football Memory`
`→ Dynamic Team / League / Competition Strength`
`→ Current Match Evidence`
`+ Same-Horizon Market State`
`→ Shared Match / Goal State`

Historical Football Memory 优先学习：

- team attack / defence；
- league scoring level；
- home advantage；
- competition/tier strength；
- promoted/new teams；
- national-team / club 分域；
- regime / era change；
- opponent-adjusted recency。

历史数据默认 chronological / prequential：目标比赛只能读取它之前的信息。

禁止把当前 Elo、赛季终表、未来阵容、未来积分或今天的球队实力回填到过去。

---

# 8. 小样本解决策略

默认优先级：

## 8.1 扩真实历史结果

优先复用权利清晰、低成本、可持续的数据源与现有历史管线。

已有 OpenFootball CC0 pilot，因此不是从零开发。

其它大型开放 corpus 必须先过 regulation-90m semantics / identity / license / competition-quality Gate。

## 8.2 Hierarchical / Partial Pooling

避免一个小联赛、升班马或新覆盖球队只凭 5–10 场独立估计全部参数。

候选层级：

`Global`
`→ Competition Universe / Tier`
`→ League / Competition`
`→ Season / Regime`
`→ Team Dynamic Attack / Defence`

小样本向父层收缩；样本足够后允许更多本地信息主导。

具体 Bayesian / shrinkage 实现必须通过 chronological evidence 选，不预授权。

## 8.3 Market as Strong Prior / Baseline

市场是强预测器，不是“低级捷径”。

尤其 Exact Score 可研究：

`de-vigged 1X2 + totals (+ handicap)`
`→ market-implied score matrix`
`→ Historical Football Memory / current evidence 学 residual correction`

目标不是“抄赔率”，也不是证明 pure-football 必须击败市场；目标是测出 Football-only / Market-only / Fusion 各自贡献。

## 8.4 Shared Latent State / Multi-Task Supervision

一场合法 90m score 同时提供：

- 1X2；
- total goals；
- BTTS；
- margin；
- exact score；
- 与已知 line 对应的 derivative labels。

这些标签可以共同约束 shared latent football state，但统计上依然只算一场 independent match。

---

# 9. 模型架构：共享底层，不强迫一套模型包打天下

长期候选架构：

`Historical Football Memory`
`+ Current Match Evidence`
`+ Same-Horizon Market Prior`
`→ Core State Champion / authoritative full-time joint goal state`
`→ coherent FT market projections`
`→ Per-Market Serving Champion / Calibrator when evidence proves gain`

Core State 保证足球逻辑和比分概率的一致底盘。

允许 1X2 / Goals / BTTS / Handicap 等专门 head，但只有在 fixed experiment + independent/prospective evidence 证明对应玩法提升后存在。

HTFT 不得机械使用 `90m lambda / 2`；需要 first-half state/truth。

Poisson、Dixon-Coles、bivariate、negative-binomial、zero-inflated、state-space、tree/boosting、ensemble、LLM/context reranker 都只是候选方法，不是路线身份。

“更复杂”没有优先权。

---

# 10. Football 与 Market：两种信息源，不是敌人

正式长期保留：

- `Football-only`
- `Market-only`
- `Fusion`

每个玩法优先找 closest same-market / same-horizon baseline。

T-24h / T-6h / T-60m 不混成绩。

closing market 可以作为 final-information benchmark，但不能拿它的晚期信息优势冒充同条件比较。

模型与市场概率差先叫 **disagreement / 分歧**。

只有固定分歧 regime 在 prospective 上持续增加预测质量或价值，才允许使用 validated edge 等更强措辞。

---

# 11. Accuracy-first 与 Market-value 分开

长期产品允许两个不同镜头，但不能混成一个“AI信心分”。

## Accuracy-first｜命中优先

回答：

> 哪个玩法/选项在当前 serving scope 下最可能猜对？

核心：calibrated top-choice correctness + hit rate + coverage。

## Market-value｜价值优先

回答：

> FBOS 概率与可执行价格相比是否存在经过验证的概率差？

核心：同时间概率差、赔率、成本、prospective validation。

高命中 ≠ 高价值；高分歧 ≠ 真 edge。

---

# 12. Selective Serving / Market Router

正式 serving：

`Market × Competition Support × Forecast Horizon × Evidence Quality × Prediction Quality`

Competition：SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED

Evidence：FULL / PARTIAL / INSUFFICIENT

Serving：NORMAL / CAUTION / DEGRADED / ABSTAIN

一个玩法失败不得拖累其它玩法；其它玩法好也不能替它背书。

如果未来首页自动选择“本场最稳观点”，这个 Best-Market Router 本身也是 prediction policy：

- routing rule 必须冻结；
- 不能用同一批历史数据既选 router 又证明 router；
- 独立 holdout / prospective 验真；
- 全量未被选中的 prediction 仍留在 ledger。

---

# 13. 用户产品形态

## 首页：Today Decision Queue

不是工程 dashboard。

每场快速展示：

- 比赛；
- 当前最稳观点；
- Exact Score flagship 快照；
- 是否存在模型-市场明显分歧；
- serving / evidence 状态；
- 无强观点时明确 ABSTAIN。

完整多玩法概率进入详情。

## 单场详情：Decision Dossier

30 秒内回答：

1. 这场更可能怎么踢？
2. 当前最稳玩法是什么？
3. Exact Score Top1 / Top3 / Top5 是什么？
4. 1X2 / 让球 / 总球 / BTTS 等怎么看？
5. Football evidence 与 market 是否一致？
6. 最大风险与分叉是什么？
7. 哪个新信息会让判断失效？
8. 同玩法/同赛事/同时点过去表现怎样？

随后再展开强弱、节奏、阵容、xG/状态、赛程、市场变化与完整 evidence。

LLM/深度研究更适合作为 evidence synthesis / explanation / hypothesis layer；除非有严格 time-safe holdout 证明增量，不直接改写概率。

---

# 14. Trust Center

Trust Center 是证明层，不是发动机。

长期至少展示：

- frozen prediction count；
- settlement coverage；
- per-market full/served hit rate；
- coverage / abstain；
- baseline + delta；
- proper score；
- calibration；
- sample / CI；
- forecast horizon；
- competition/regime；
- Exact Top1/3/5；
- known weak spots；
- drift；
- Champion/Challenger governance（允许时）。

失败时期不得隐藏。

---

# 15. Feature Incremental Value Gate

xG、xT、shot quality、lineup/player、injury、manager、weather、travel/rest、GNN/embeddings、LLM context 等只有经过：

`time-safe acquisition`
`→ paired current control`
`→ fixed +feature ablation`
`→ chronological holdout`
`→ coverage/population audit`
`→ prospective shadow if promising`

才能进入概率核心。

解释更丰富 ≠ 预测更准。

---

# 16. Competition / Population / Small-Cell Gate

至少区分：

- Big-5 / top
- other top
- lower / small
- domestic cup
- continental club
- national friendly
- national qualifier/nations
- national major tournament
- unknown/mixed
- early season / cold start
- promoted/new teams
- major roster/manager regime shift

评价可以细分，但 tiny cells 的参数/校准不能假装独立可靠；需要 conservative fallback / partial pooling / uncertainty。

---

# 17. Anti-Favourite / Class-Balance

1X2 不能只看 overall accuracy。

至少检查 Home/Draw/Away predicted share、actual share、confusion matrix、per-class recall、Draw recall、proper score 与 calibration。

其它多类市场同理。

---

# 18. Immutable Prediction / Data Truth

正式 prediction 必须保存：

- fixture identity；
- source cutoff；
- freeze timestamp / minutes-to-kickoff；
- input snapshot / provenance；
- model identity；
- full probabilities / joint score state；
- market-specific outputs；
- source/model fingerprints。

赛后只能追加 result/evaluation。

`one football match = one independent observation`。

不同 version / horizon 只能作 paired/repeated truth。

---

# 19. Data / Identity / Rights

长期需要 canonical competition/team/fixture identity、provider crosswalk、freshness/completeness、prematch timing、commercial-use/storage/display/redistribution boundary 与 provider replacement strategy。

宁可 UNKNOWN，也不能 fuzzy 猜错。

技术可访问不等于可商业复用。

历史 corpus 同样必须过 rights 与 90m semantics Gate；extra time / penalties 不得污染 regulation-time Exact Score。

---

# 20. Research / Challenger / Multiple Testing

任何升级：

`Research`
`→ Applicability`
`→ fixed hypothesis`
`→ chronological holdout/replay`
`→ paired baseline`
`→ prospective shadow`
`→ unique-match evaluation`
`→ independent Promotion Review`

如果同时扫描大量 model × market × competition × horizon × feature，不能拿最好看的单个 slice 的未校正 CI 当 Promotion 证据；需要 fresh prospective confirmation 或适当 data-snooping/multiplicity guard。

---

# 21. Operations / Drift

长期自动链：

`发现 → Identity → Evidence → Prediction → Freeze → Site → Result Truth → Per-Market Evaluation → Monitoring → Challenger Review`

Drift 至少按 `Market × Competition × Forecast Horizon` 观察。

Drift 触发 investigation / CAUTION / ABSTAIN；不自动授权 retrain / recalibration / 调参。

---

# 22. Closed Beta / User Validation

不等模型“最终完成”才让真实用户用，但未成熟玩法必须明确。

低成本测量：

- 用户主要打开哪些比赛/玩法；
- 是否真正理解 score scenarios / probabilities / ABSTAIN；
- 是为“懂比赛”回来，还是为“命中判断”回来；
- Exact Score 是否是主要 retention driver；
- evidence 是否真正被看；
- 赛后是否回来核验；
- 什么结论会被误解成保证；
- 哪些赛事/玩法形成 repeat use。

---

# 23. Betting Decision Layer / Compliance

EV、stake、串关、portfolio 都属于概率预测之后的 downstream layer。

只有 `概率可信 + calibration + executable price + compliance` 才提高优先级。

产品保持分析/信息服务边界，不售彩、不代购、不出票、不充值、不自动下注，不宣传稳赚或保证收益。

用户可将信息用于其所在地法律允许的竞彩足球或其它足球投注决策，但 FBOS 不执行交易。

---

# 24. 产品建设优先级

任何新任务先问：

1. 它是在解决 Prediction Quality，还是只是界面/数据/settlement 缺口？
2. 它能否提高某个正式玩法的真实 hit rate / probability quality？
3. 对 Exact Score 是否改善严格 Top1/Top-k/NLL，而不是只让比分“看起来更合理”？
4. 是否拥有足够、合法、time-safe 的训练 truth？
5. 小样本问题能否先通过历史扩容/partial pooling/market prior 解决，而不是堆复杂模型？
6. 是否有 same-market / same-horizon baseline？
7. 是否能进入 chronological holdout 与 prospective path？
8. 是否保留覆盖率和用户赛事理解能力？
9. 用户是否真实需要？
10. 是否已有免费/稳定/开源能力可复用？
11. 是否会让系统更复杂但没有 measurable incremental value？

**如果只是“看起来高级”，默认延后。**

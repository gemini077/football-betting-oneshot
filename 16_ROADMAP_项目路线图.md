# 16_ROADMAP_项目路线图.md

最后更新：2026-09-04
状态：`CLEAN BASELINE / PRODUCT REBASE IN PROGRESS`

角色：**只描述产品如何从当前状态走向可公开、可信、可持续使用。**

本文件不保存历史 milestone、不承担 Issue/PR 日志职责、不把已完成技术任务按时间倒序堆叠。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. North Star

建立一个能够：

`自动发现比赛 → 形成可审计足球/市场证据 → 给出多玩法概率与比分情景 → 赛前冻结 → 明确表达置信度/风险 → 赛后自动验真 → 长期公开自身表现 → 持续 Challenger 改进`

的足球赛前决策产品。

差异化目标不是“也能猜比分”，而是：

> **预测有依据、概率有边界、错误可追溯、历史不能篡改、用户知道什么时候值得信。**

---

# 2. Roadmap 设计原则

1. **产品结果驱动，不按技术组件串行排队。**
2. Prediction Trust 是核心能力，但模型研究不是整个 Roadmap 的唯一主干。
3. Product / Data / Operations / Compliance / User Validation 必须并行推进。
4. 已完成的基础设施不因新任务重新变回主线。
5. 每个 lane 只有在真实 blocker 存在时才开工程任务；不得因“还能优化”无限下钻。
6. 一个 bounded issue 结束后回项目级 Gate；不允许 `identity→identity→identity` 或 `model→model→model` 自动连锁。
7. Roadmap 是动态假设。新事实可重排、取消或替换后续路线。
8. 历史执行证据留在 Git/Issues/PR/docs evidence；不回填进 Roadmap。

---

# 3. 当前产品阶段

`LEVEL 4 — CLOSED BETA READY / PUBLIC LAUNCH NOT READY`

已经证明：

- 比赛发现 / Universe 可运行；
- canonical fixture / identity 主链存在；
- 足球 + 市场 evidence 能进入预测；
- Champion 能生产多玩法概率；
- prematch freeze / result settlement / prospective ledger 已建立；
- Challenger shadow / promotion governance 已建立；
- Homepage + Match Detail + Pages / 自动化基础已存在。

因此当前问题不再是“能不能造出一个系统”。

当前问题是：

> **这个系统是否足够可信、可理解、可运营、合规，值得真实用户持续使用并进一步公开扩大？**

---

# 4. Current Program — PUBLIC-LAUNCH TRUST

这是当前产品级 program。它由并行 Gate 组成，不是单一技术 Phase。

## Lane A — Prediction Trust

状态：`CURRENT / P0`

目标：证明正式输出的概率与比分情景在真实 prospective 条件下有足够质量，并能知道自己在哪些场景不可靠。

当前事实：

- Exact Score 仍是最大技术 P0；历史存在 1-1 / lambda compression failure mode。
- Challenger C accepted 50+ checkpoint=`56 verified unique / PROMISING_NOT_ESTABLISHED / shadow-only`。
- C 后台自然积累到 >=100；禁止为显著性调参。
- external correct-score market benchmark 是正交证据 lane，先解决可审计 identity/coverage。

方向：

- score distribution / score scenarios，而不是把单一比分包装成确定答案；
- proper scores + calibration + stability + subgroup safety；
- selective serving / abstention；
- Champion / Market-only / Football-only / Fusion 可区分。

退出当前 P0 的标准必须来自 prospective evidence，而不是“感觉模型已经够复杂”。

## Lane B — User Trust / Decision Product

状态：`CURRENT / P0 PRODUCT REBASE`

目标：用户在 30 秒内明确知道：

- 这场怎么看；
- 最可能的比赛情景；
- 1X2 / O-U / BTTS / Score 之间是否一致；
- 系统有多大把握；
- 支持证据是什么；
- 最大冲突和错误触发点是什么；
- 如果证据不足，系统为什么选择谨慎或 abstain。

重点不是继续增加页面模块，而是把后台已有的 prediction-quality / freeze / verification truth 变成用户能理解的信任产品。

候选核心能力：

- confidence / evidence quality；
- score scenario distribution；
- visible abstention/degraded state；
- postmatch verification；
- Trust Center / historical performance transparency。

## Lane C — Data / Identity / Rights

状态：`CURRENT / P0 FOUNDATION`

目标：保证模型与用户产品依赖的数据：

- identity 可审计；
- source timing 可证明；
- coverage 可测；
- rights/commercial-use 边界清楚；
- provider 可替换而非硬耦合。

当前执行 Issue：`#180 EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`。

#180 只是本 lane 的 bounded task；完成后必须回项目 Gate。

## Lane D — Operations / Reliability

状态：`REQUIRED BEFORE PUBLIC LAUNCH`

目标：产品不是“某次 Actions 绿了”，而是能持续无人值守运行。

Public Launch 前至少需要验证：

- business-date rollover / daily freshness；
- silent missing detection；
- result settlement continuity；
- durable write / rollback；
- provider degradation observability；
- user-facing fail-safe；
- monitoring 与明确 incident boundary；
- no secret / sensitive log leakage。

具体 soak 门槛由后续 release-readiness audit 基于真实 runtime 决定，不在这里拍脑袋写固定天数。

## Lane E — User Validation / Closed Beta

状态：`SHOULD START BEFORE MODEL PERFECTION`

目标：获取我们目前最缺的数据——**真实用户如何使用产品**。

验证问题包括：

- 用户第一眼最想看什么；
- 单一比分 vs Top-N score scenario 哪个更有决策价值；
- confidence / abstain 是否增强信任；
- 用户是否点击 evidence；
- 是否回看 postmatch verification；
- 哪些玩法真正高频；
- 用户是否因为“透明展示错误”而更信任，而不是只看所谓命中率；
- 什么信息导致复访。

Closed Beta 不等于 Public Launch；也不能用用户喜欢替代概率质量 Gate。

## Lane F — Compliance / Commercial Readiness

状态：`REQUIRED BEFORE PUBLIC COMMERCIALIZATION`

产品边界：分析信息服务，不提供彩票交易、代购、出票、充值、自动下注或官方彩票服务。

需要在公开商业化前独立关闭：

- 数据源 commercial-use / redistribution rights；
- 中国市场宣传用语与可验证指标边界；
- 收费产品的实际服务边界；
- 用户数据 / privacy / account 若引入后的治理；
- 不把“预测概率”宣传成稳赚、保证收益或官方投注结论。

## Lane G — Advanced Model R&D

状态：`SUPPORTING / DEMAND-TRIGGERED`

候选：

- opponent-adjusted strength；
- hierarchical competition model；
- richer joint-score distribution；
- xG / shot quality；
- player / lineup / injury impact；
- rest / travel / weather / manager / set pieces。

启动条件：

> 当前真实 failure mode + 输入可得 + timing 合法 + population 适用 + 有独立 evaluation plan。

禁止因为论文新、模型高级或“还可以再提升”就自动启动。

---

# 5. Downstream — Betting Decision Layer

状态：`FUTURE / GATED`

EV、value、stake sizing、串关相关性、portfolio 等仍然属于 downstream。

只有在：

`probability trust + calibration + executable market price + rights/compliance`

均达到可用水平后，才重新提升优先级。

产品不是自动下注机器人。

---

# 6. 当前执行与后台任务

### Current bounded execution

- Issue #180：Reep exact cross-source identity bridge preflight。

### Background accumulation

- Challenger C：自然 prospective accumulation to >=100。

### Product-level active work

- 2026-09-04 Roadmap Rebase / Product Maturity Review：由 ChatGPT 研究线完成，不交给 Codex。

**这三者不能互相冒充。**

#180 完成 ≠ 产品主线自动继续 identity；C 到 100 ≠ 自动 promotion；Roadmap Review ≠ 立即大改所有代码。

---

# 7. Public Launch 不是一个按钮

最终 Public Launch Gate 至少同时要求：

1. Prediction Trust：正式输出没有已知严重 collapse，概率质量/适用范围有 prospective 证据；
2. User Trust：用户看得懂结论、置信度、风险与 abstention；
3. Data/Rights：关键 production source 的使用边界与 fallback/替换策略可接受；
4. Operations：无人值守持续运行、silent failure 可发现、可恢复；
5. Compliance：产品与宣传/收费边界清晰；
6. User Validation：真实 Closed Beta 证明核心 journey 有价值；
7. Release Smoke：真实公开环境端到端通过。

具体每个 Gate 的量化阈值必须由对应 evidence/research 决定，不在 Roadmap 中凭空写死。

---

# 8. Roadmap Anti-Pattern

以后不允许重新出现：

- 把历史 milestone 倒序塞回 Roadmap；
- 把 GitHub Issue 当成产品 Phase；
- 因当前 blocker 是模型就停止产品验证；
- 因产品 UI 可用就忽略 Prediction Trust；
- 一个局部任务完成后自动沿同技术树继续；
- 为了让 Roadmap 看起来“有计划”而预先锁死模型路线；
- 把“数据能抓到”当成“商业权利已解决”；
- 把版本行/重复预测当独立比赛样本。

---

# 9. Historical Archive Pointer

旧 Roadmap milestone 流水账不再复制在本文件。

需要历史时读取：

- Git history 中本文件 2026-09-01 及以前版本；
- GitHub Issues / PR / Actions；
- `docs/data-foundation/`；
- `docs/prediction-quality/`；
- `docs/model-governance/`；
- `docs/research/`；
- Memory-Hub `RESEARCH_ASSETS.md`。

**Current truth 只允许向前演进，不允许通过复制旧 milestone 重新污染 Roadmap。**

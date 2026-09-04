# 18_ACCEPTANCE_验收标准.md

最后更新：2026-09-04
角色：定义**当前项目长期通用的验收原则与产品级 Gate**。

本文件不保存已结束 milestone 的逐项验收清单。每个具体 Issue 的细粒度验收标准写在该 Issue 契约中。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. 通用 Acceptance Gate

任何工程、研究或产品任务声称“完成”，至少必须回答：

1. 目标是否真正完成；
2. 是否有可复现 evidence，而非报告自述；
3. scope 是否最小且无 hidden behavior change；
4. 是否保持 prematch / frozen integrity；
5. identity 是否 deterministic / fail closed；
6. silent missing / degradation 是否可见；
7. focused/full tests 是否与风险匹配；
8. production/network 声明是否有真实 runtime 证据；
9. secret / data rights 是否安全；
10. PASS 是否被错误扩张成下一路线授权；
11. 是否留下可复核 evidence；
12. 是否在 bounded task 后重新回 Project Gate。

测试全绿 ≠ Acceptance PASS。

---

# 2. Research-Only Gate

- 默认 `DO NOT MERGE`，除非 Issue 明确改变契约；
- 不改 Champion / serving / frozen history / authoritative result truth；
- observed fact / inference / counterfactual / unknown 必须分开；
- 同一 cohort 的重复扫描不能冒充新增独立证据；
- 研究结束后必须回项目级 Gate。

---

# 3. Engineering Fix Gate

Bug fix 只有在：

- 根因有独立证据；
- 修改落在最小确定性边界；
- regression test 直接覆盖 bug；
- 旧合法行为保持；
- real current-data/runtime replay 证明关闭；
- changed files / CI / artifact 可独立核验

时才能进入 merge consideration。

若 bug 影响 evaluation truth，修复后必须重算受影响正式指标。

---

# 4. Model / Challenger Gate

`Research hypothesis → fixed implementation → holdout/replay → prospective shadow → unique-match evaluation → independent Promotion Review`

硬规则：

- `one match = one observation`；
- 不按 version rows 放大样本；
- 不用 postmatch outcome 生成 prematch；
- 不为显著性反复调参；
- proper score / calibration / stability / subgroup safety 优先于单一命中率；
- 保留 Champion control；
- Promotion 必须独立验收。

C governance：`<50 NOT_REACHED / 50–99 CHECKPOINT / >=100 PROMOTION_REVIEW_READY at most / auto_promote=false`。

---

# 5. Segmented Prediction Trust Gate

以后不允许用一个全局“预测健康”替代各玩法的正式 serving judgment。

验收单位至少为：

`Market × Competition Support × Evidence Quality × Prediction Quality`

## Market
- 1X2
- O/U
- BTTS
- Exact Score

## Competition Support
- SUPPORTED
- LIMITED
- EXPERIMENTAL
- UNSUPPORTED

## Evidence Quality
- FULL
- PARTIAL
- INSUFFICIENT

## Serving State
- NORMAL
- CAUTION
- DEGRADED
- ABSTAIN

验收要求：

- 一个玩法的 DEGRADED 不得机械拖累其他玩法；
- 一个玩法表现好不得替另一个玩法背书；
- competition / regime 小样本不得伪装成稳定支持；
- serving threshold 必须有 prospective / calibration / risk-coverage evidence；
- UI 必须忠实呈现 serving state。

---

# 6. Confidence / Calibration Gate

任何用户看到的“高/中/低”“70%可信”或类似 confidence 语义，必须能回答：

- 这个 confidence 来自什么可复现量；
- 历史相同 bucket / regime 实际发生率是多少；
- sample size 多大；
- uncertainty 多大；
- 是否经过 prospective / time-safe 验证。

若不能回答，产品应显示 evidence completeness / uncertainty / serving state，而不是制造 confidence 标签。

正式概率评价优先 proper scoring rules；不能只看 hit rate。

---

# 7. User Trust / Decision Product Gate

Homepage / Match Detail / Trust Center 按用户任务验收，而不是按组件数量验收。

用户至少应能快速回答：

1. 这场系统怎么看？
2. 哪些比分情景最可能？
3. 各玩法是否同样可信？
4. 为什么？
5. 最大风险/冲突？
6. 什么情况下系统选择 abstain？
7. 过去同类判断表现如何？

Homepage 若称为 Decision Queue，必须证明它能帮助用户优先发现更值得看的比赛，而不是仅按 kickoff 排列表格。

内部 model family / file path / checkpoint jargon 默认不做主视觉。

---

# 8. Trust Center Gate

Trust Center 不能只显示一个“命中率”。至少在样本允许时覆盖：

- immutable formal prediction count；
- settlement coverage；
- per-market proper scores；
- Exact Top1/3/5；
- calibration / reliability；
- sample size / uncertainty；
- competition tier / regime；
- known weak spots；
- market / simple baseline comparison；
- abstain / served coverage 与 selective quality。

失败样本、低表现月份和 weak slices 不得被隐藏以美化营销。

---

# 9. Data / Identity / Rights Gate

关键链同时过：

- availability；
- deterministic identity；
- prematch timing；
- freshness / completeness；
- provenance；
- commercial-use / storage / display / redistribution boundary；
- replacement/fallback strategy。

禁止 fuzzy/LLM translation/kickoff overlap 单独成为 authoritative identity；禁止把可访问等同可商用。

---

# 10. Operations / Release Gate

Public Launch 至少关闭：

- daily/business-date freshness；
- silent missing；
- provider degradation observability；
- freeze/result/settlement continuity；
- durable write / rollback；
- monitoring / fail-safe；
- secret/log hygiene；
- public-site smoke / stale-page protection。

一次成功 run 不等于 unattended reliability。

---

# 11. Closed Beta Measurement Gate

`ENGINEERING CLOSED-BETA READY` 不等于 `TRUST-BETA MEASUREMENT READY`。

邀请真实用户前至少需要一个低成本、隐私最小化的测量方案，能够回答：

- 首页是否成功带到 match detail；
- 用户是否理解 score scenarios / probability / abstain；
- evidence 是否被查看；
- Trust Center 是否被使用；
- 用户是否赛后回来；
- 哪些玩法/赛事被重复使用；
- 哪里发生误解；
- 用户为什么愿意第二天/下周回来。

允许小规模人工访谈/结构化反馈作为早期方案；不要求先搭重账户系统或昂贵 analytics。

User preference 不能替代 Prediction Trust；Prediction Trust 也不能替代用户验证。

---

# 12. Compliance / Commercial Gate

公开商业化前确认：

- 产品保持分析/信息服务边界；
- 不提供彩票交易、代购、出票、充值、自动下注；
- 数据源商业使用/展示/存储/衍生使用有依据；
- accuracy / calibration / historical-performance claim 有可审计出处、样本和适用范围；
- 不使用稳赚/保证收益式表达；
- responsible-use / 未成年人边界清晰；
- 引入账号、支付、用户数据后另过 privacy/security/payment gate。

---

# 13. Distribution / Monetization Gate

商业模式目前是 hypothesis，不是既定产品要求。

未来收费或扩张前至少验证：

- repeat use 存在；
- 用户明确愿意为什么能力付费；
- 免费信任资产与付费能力边界合理；
- 数据/工具成本与 founder 维护成本可持续；
- 商业包装不破坏 transparency / compliance。

不得因为竞品卖 VIP picks 就复制 VIP/红单/高命中宣传。

---

# 14. Historical Pointer

旧专项验收条款从 Git history、Issue、PR、Actions、`docs/*` evidence 与 Memory-Hub 恢复。

**历史 milestone 长清单重新进入本文件视为控制面污染。**

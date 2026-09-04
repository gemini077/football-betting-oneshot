# 18_ACCEPTANCE_验收标准.md

最后更新：2026-09-04
角色：定义**当前项目长期通用验收原则与产品级 Gate**。

本文件不保存已结束 milestone 的逐项验收清单。每个具体 Issue 的细粒度验收标准写在该 Issue 契约中。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. 通用 Acceptance Gate

任何工程、研究或产品任务声称“完成”，至少回答：

1. 目标是否真正完成；
2. 是否有可复现 evidence，而非报告自述；
3. scope 是否最小且无 hidden behavior change；
4. 是否保持 prematch / frozen integrity；
5. identity 是否 deterministic / fail closed；
6. silent missing / degradation 是否可见；
7. tests 是否与风险匹配；
8. production/network 声明是否有真实 runtime 证据；
9. secret / data rights 是否安全；
10. PASS 是否被错误扩张成下一路线授权；
11. 是否留下可复核 evidence；
12. bounded task 后是否重新回 Project Gate。

测试全绿 ≠ Acceptance PASS。

---

# 2. Research-Only Gate

- 默认 `DO NOT MERGE`，除非 Issue 明确改变契约；
- 不改 Champion / serving / frozen history / authoritative result truth；
- observed fact / inference / counterfactual / unknown 分开；
- 同一 cohort 重复扫描不能冒充新增独立证据；
- 结束后回项目级 Gate。

---

# 3. Engineering Fix Gate

Bug fix 只有在根因有独立证据、修改最小确定、regression test 直接覆盖、旧合法行为保持、real current-data/runtime replay 证明关闭、PR/CI/artifact 可独立核验时，才能进入 merge consideration。

若 bug 影响 evaluation truth，修复后必须重算受影响正式指标。

---

# 4. Multi-Market Prediction Quality Gate

**预测质量是模型/产品的核心结果，Trust 是证明层。**

任何一级玩法验收必须逐玩法进行，禁止使用一个跨玩法 blended “overall accuracy”。

每个玩法在数据允许时至少报告：

1. eligible unique matches；
2. settled unique matches；
3. full-coverage top-choice hit rate；
4. served hit rate；
5. served coverage / abstain rate；
6. same-market simple/market baseline；
7. delta vs baseline；
8. appropriate proper score（Brier / LogLoss / NLL 等）；
9. calibration / ECE；
10. sample size + uncertainty / CI；
11. competition/population scope；
12. chronology/stability；
13. forecast horizon / freeze lead-time；
14. failure taxonomy。

Exact Score 额外报告 Top1/Top3/Top5、Score NLL、concentration/entropy；官方竞彩比分桶建立后单独报告其 accuracy。

验收解释：

- 命中率是核心指标，不得因为强调 proper score 就回避用户实际关心的“猜对多少”；
- 命中率不能脱离 coverage：精选越少通常越容易抬高 hit rate，因此必须报告 `Hit Rate @ Coverage / risk-coverage`；
- 一个容易玩法的高命中率不得替其它玩法背书；
- 只优于 random/naive baseline 不足以证明竞争力；有同玩法市场/强简单基线时必须比较。

---

# 5. Forecast Horizon / Benchmark Fairness Gate

T-24h、T-6h、T-60m 等 forecast 不属于同一信息条件。

验收必须：

- 保留真实 freeze lead-time；
- 先审 lead-time 分布，再定义 horizon bins；
- 同一 match 不同 horizon 视为 paired/repeated forecasts，不放大 independent sample；
- 早期 forecast 优先与同一时点或更早的 market snapshot 比较；
- closing market 可作为 final-information benchmark，但不得冒充 equal-information control；
- 若不同 horizon 混合汇总，必须同时提供分层结果或明确限制。

---

# 6. Class-Balance / Anti-Favourite Gate

1X2 不能只用 overall accuracy 验收。

至少在样本允许时检查：

- Home / Draw / Away predicted share；
- actual share；
- confusion matrix；
- per-class recall；
- Draw recall；
- multiclass Brier / LogLoss；
- RPS 可作为附加 ordinal metric；
- class-wise calibration。

若模型通过“几乎不预测 Draw / 总是押 favourite”提高 overall accuracy，不能视为无条件提升。

其它多类玩法同理：0–7+ 关注尾部类别，HTFT 关注九类失衡。

---

# 7. Feature Incremental Value Gate

任何新 rich feature /复杂表示（xG/xT、lineup/player、injury、manager、weather、travel/rest、NLP/news、GNN/embedding 等）进入 production 前必须证明增量。

最低验收：

`time-safe acquisition → same-match paired control → fixed +feature ablation → chronological holdout → coverage/population audit → prospective shadow if promising`

必须回答：

- 相同赛前截止时点上，相对当前 Champion 增加了什么？
- 相对 closest same-time strong market baseline 增加了什么？
- 是否只提升解释性而没有提升预测？
- 是否因 rich-data 缺失显著压缩产品覆盖率？
- 是否只在某个 competition/horizon 有效？

“更高级/更贵/数据更多”不能作为 PASS 理由。

---

# 8. Model / Challenger Gate

`Research hypothesis → fixed implementation → holdout/replay → prospective shadow → unique-match evaluation → independent Promotion Review`

硬规则：

- `one match = one observation`；
- 不按 version rows 放大样本；
- 不用 postmatch outcome 生成 prematch；
- 不为显著性反复调参；
- hit rate + coverage + baseline + proper score + calibration + stability + subgroup safety 联合判断；
- 保留 Champion control；
- Promotion 必须独立验收。

C governance：`<50 NOT_REACHED / 50–99 CHECKPOINT / >=100 PROMOTION_REVIEW_READY at most / auto_promote=false`。

---

# 9. Market Target / Truth Gate

### Tier A — 中国竞彩

- FT 1X2 / 胜平负
- 让球胜平负
- 比分 / official score buckets
- 总进球 0–7+
- 半全场

### Tier B

O/U / BTTS / Asian/common handicap / team totals / winning margin / double chance 等。

任何新玩法正式上线前必须先证明 target semantics、prematch 必需输入、result/settlement truth、evaluation unit/metric、market/source rights、与已有玩法数学定义的兼容性。

**半全场专门 Gate**：必须先证明 first-half score/outcome truth 与 dedicated evaluation；禁止用 `90m lambda / 2` 直接宣称完成。

---

# 10. Shared-State / Market-Specific Model Gate

full-time joint score state 可作为共同底盘，并尽量数学一致推导 FT 玩法。

但不得把“一套模型对所有玩法最优”写成硬规则。

若 1X2 / Goals / BTTS / handicap 使用 market-specific calibration/head，必须：

- 预先固定 hypothesis 与参数搜索边界；
- 用独立 holdout/prospective evidence 证明该玩法提升；
- 检查 probability calibration；
- 检查与 authoritative score state 的显著矛盾；
- 不因单一 hit-rate 增长牺牲其它关键指标而不披露。

---

# 11. Segmented Serving Gate

正式 serving 单位：

`Market × Competition Support × Forecast Horizon × Evidence Quality × Prediction Quality`

Competition：`SUPPORTED / LIMITED / EXPERIMENTAL / UNSUPPORTED`

Evidence：`FULL / PARTIAL / INSUFFICIENT`

Serving：`NORMAL / CAUTION / DEGRADED / ABSTAIN`

验收要求：

- 一个玩法 DEGRADED 不得机械拖累其它玩法；
- 一个玩法表现好不得替另一个玩法背书；
- competition / regime / horizon 小样本不得伪装成稳定支持；
- serving threshold 必须有 prospective / calibration / risk-coverage evidence；
- UI 忠实呈现 serving state；
- 任何“精选高命中”必须能审计 coverage 与被 abstain 的比赛。

---

# 12. Confidence / Calibration Gate

任何用户看到的“高/中/低”“70%可信”或类似 confidence，必须能回答来源、相同 bucket/regime 实际发生率、sample size、uncertainty、是否经过 prospective/time-safe 验证。

若不能回答，显示 evidence completeness / uncertainty / serving state，而不是制造 confidence。

---

# 13. User Decision Product / Trust Center Gate

用户至少应快速回答：

1. 这场各玩法怎么看？
2. 哪个玩法当前历史证据最强？
3. 比分情景/概率是什么？
4. 哪些玩法应谨慎或 abstain？
5. 为什么？最大风险/冲突是什么？
6. 过去同玩法、同赛事层、同 horizon 表现如何？

Trust Center 不能只显示一个“命中率”，也不能只显示 NLL/Brier 而把 hit rate 藏掉。

样本允许时至少覆盖 per-market full/served hit rate、coverage、baseline+delta、proper scores、Exact Top1/3/5、calibration、sample/uncertainty、competition/horizon、class-balance diagnostics、known weak spots、abstain/selective quality。

失败样本和低表现时期不得被隐藏。

---

# 14. Data / Identity / Rights Gate

关键链同时过 availability、deterministic identity、prematch timing、freshness/completeness、provenance、commercial-use/storage/display/redistribution boundary、replacement/fallback strategy。

禁止 fuzzy/LLM translation/kickoff overlap 单独成为 authoritative identity；禁止把可访问等同可商用。

---

# 15. Operations / Release Gate

Public Launch 至少关闭 daily/business-date freshness、silent missing、provider degradation observability、freeze/result/settlement continuity、durable write/rollback、monitoring/fail-safe、secret/log hygiene、public-site smoke/stale-page protection。

一次成功 run 不等于 unattended reliability。

---

# 16. Closed Beta Measurement Gate

邀请真实用户前至少需要低成本、隐私最小化测量方案，回答首页→detail、用户主要查看哪些玩法、是否理解 strongest view/probability/score scenarios/abstain、evidence/Trust Center 是否被使用、是否赛后回来、哪些玩法/赛事被重复使用、哪里误解、为什么第二天/下周回来。

允许小规模人工访谈/结构化反馈；不要求先搭重账户系统。

---

# 17. Compliance / Commercial Gate

公开商业化前确认：

- 分析/信息服务边界；
- 不提供彩票交易、代购、出票、充值、自动下注；
- 数据商业使用/展示/存储/衍生有依据；
- accuracy / hit rate / calibration / historical-performance claim 有可审计出处、coverage、样本和适用范围；
- 不使用稳赚/保证收益式表达；
- responsible-use / 未成年人边界清晰；
- 引入账号、支付、用户数据后另过 privacy/security/payment gate。

---

# 18. Distribution / Monetization Gate

商业模式目前是 hypothesis。

收费或扩张前至少验证 repeat use、用户愿为什么能力付费、免费信任资产与付费能力边界、数据/工具/Founder 维护成本可持续，以及商业包装不破坏 transparency/compliance。

不得因为竞品卖 VIP picks 就复制高命中/红单叙事。

---

# 19. Historical Pointer

旧专项验收条款从 Git history、Issue、PR、Actions、`docs/*` evidence 与 Memory-Hub 恢复。

**历史 milestone 长清单重新进入本文件视为控制面污染。**

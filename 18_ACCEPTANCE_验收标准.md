# 18_ACCEPTANCE_验收标准.md

最后更新：2026-09-04
角色：定义**当前项目长期通用的验收原则与产品级 Gate**。

本文件不保存已结束 milestone 的逐项验收清单。每个具体 Issue 的细粒度验收标准应写在该 Issue 契约中，并由 PR / Actions / artifact 提供证据。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. 通用 Acceptance Gate

任何工程、研究或产品任务声称“完成”，至少必须回答：

1. **目标真实性**：任务真正回答了契约中的问题，而不是只跑完代码。
2. **Evidence**：结论是否有代码、测试、runtime、artifact、provider response 或其他可复现事实支撑。
3. **Scope**：是否只改了允许范围；是否出现 unrelated refactor / hidden behavior change。
4. **Prematch Integrity**：不得使用目标赛果、postmatch truth 或未来信息生成赛前预测。
5. **Frozen Integrity**：既有合法 frozen prediction 不重写。
6. **Identity Integrity**：一个足球比赛一个 observation；跨源 identity 不靠模糊猜测偷过 Gate。
7. **Silent Failure**：缺失、provider failure、ambiguous identity、degraded state 必须可见，不能静默变成正常结果。
8. **Tests**：focused tests 必须与风险对应；需要 full/regression 时必须真实运行。
9. **Runtime Truth**：声称 production / network / deployment 成功时，必须有真实远端/runtime 证据，不能只用 mock。
10. **Security / Rights**：不得泄露 secret；technical accessibility 不得冒充 commercial-use permission。
11. **Decision Discipline**：PASS 只证明本任务，不自动授权下一模型、Promotion、provider migration 或 production integration。
12. **Reusable Evidence**：结论必须留下足够证据供未来独立复核，而不是依赖聊天记忆。

测试全绿 ≠ Acceptance PASS。

---

# 2. Research-Only Task Gate

Research-only PR 默认：

- `DO NOT MERGE`，除非 Issue 明确说明其工程产物本身需要进入 main；
- 不改 Champion / serving / frozen history / authoritative result truth；
- 不因研究结论“看起来好”自动进入 production；
- 研究 artifact 必须区分 observed fact、inference、counterfactual 与 unknown；
- 对同一 cohort 的反复扫描不得包装成新增独立证据。

研究任务结束后必须回项目级 Gate。

---

# 3. Engineering Fix Gate

真正的 bug fix 只有在以下条件满足时才能进入 merge consideration：

- 根因有独立证据；
- 修改落在最小确定性边界；
- regression tests 直接覆盖 bug；
- 旧合法行为保持兼容；
- 不顺手改模型/参数/数据历史；
- real current-data/runtime replay 证明问题确实关闭；
- PR scope、Actions、changed files 与 artifact 可独立核验。

若 bug 影响 evaluation truth，修复后必须重新计算受影响的正式指标；旧错误评估不得继续作为 current truth。

---

# 4. Model / Challenger Gate

任何新 Challenger 或 Promotion 必须遵循：

`Research hypothesis → fixed implementation → historical holdout / replay → prospective shadow → unique-match evaluation → independent Promotion Review`

长期硬规则：

- `one match = one observation`；
- 不按版本行放大样本；
- 不用 postmatch outcome 拟合赛前生成；
- 不为显著性反复调参数；
- proper score / calibration / stability / subgroup safety 优先于单一命中率；
- 强制保留 Champion control；
- Promotion 必须独立验收。

Challenger C 当前 governance：

- `<50 verified unique = NOT_REACHED`
- `50–99 = CHECKPOINT / shadow-only`
- `>=100 = PROMOTION_REVIEW_READY at most`
- `auto_promote=false`

---

# 5. Prediction Trust Product Gate

用户面对的正式预测不能只满足“模型有输出”。

需要验证：

- distribution 没有已知严重 collapse；
- probability/calibration 有 prospective evidence；
- Exact Score / 1X2 / O-U / BTTS 数学关系一致或明确解释独立模型边界；
- confidence / evidence completeness 与实际错误风险有可解释关系；
- degraded / insufficient / abstain 状态不会被 UI 包装成 normal recommendation；
- 历史 performance 不能通过删失败样本或赛后改答案美化。

---

# 6. User Trust / Product Gate

Homepage / Match Detail / Trust Center 等用户面产品，应按用户任务验收，而不是按“组件都显示了”验收。

用户至少应能快速回答：

1. 这场系统怎么看？
2. 最可能的比赛情景是什么？
3. 这个判断有多大把握？
4. 为什么这么判断？
5. 最大冲突 / 风险是什么？
6. 什么情况下系统选择不强猜？
7. 过去类似判断真实表现如何？

内部 model family、文件路径、freeze 状态码等工程信息默认不应成为用户页面主视觉。

---

# 7. Data / Identity / Rights Gate

关键数据链必须同时过：

- source availability；
- deterministic identity；
- prematch timing；
- freshness / completeness；
- provenance；
- commercial-use / storage / redistribution boundary；
- replacement/fallback strategy。

禁止：

- 模糊身份直接成为 authoritative truth；
- kickoff overlap 单独证明 same match；
- LLM/翻译结果直接作为 cross-provider identity；
- “公开网页可访问”自动推导“可以商业抓取和再分发”。

---

# 8. Operations / Release Gate

Public Launch 需要真实无人值守证据，而不是一次成功运行。

至少需要关闭：

- daily/business-date freshness；
- silent missing；
- provider degradation observability；
- freeze/result/settlement continuity；
- durable write / rollback；
- monitoring / fail-safe；
- secret/log hygiene；
- public-site smoke / stale-page detection。

具体 soak duration / threshold 由独立 release-readiness research + actual runtime evidence 决定，不在本文件拍脑袋固定。

---

# 9. Closed Beta / User Validation Gate

Closed Beta 不是“模型已完美”的奖章，而是验证产品是否真的被理解和使用。

应获得真实证据，例如：

- 用户能否找到今日比赛并理解主结论；
- score scenario / confidence / abstain 是否被正确理解；
- 用户是否查看 evidence / postmatch；
- 哪些玩法真正有使用需求；
- 哪些页面/字段造成误解；
- 是否存在可重复的 return behavior / core journey value。

用户喜欢产品不能替代 Prediction Trust；Prediction Trust 也不能替代用户验证。

---

# 10. Compliance / Commercial Gate

公开商业化前必须独立确认：

- 产品保持分析/信息服务边界；
- 不提供彩票交易、代购、出票、充值、自动下注；
- 数据源的商业使用/展示/存储/衍生使用符合授权；
- 命中率、概率、历史表现等宣传有可审计出处，不使用保证收益/稳赚式表达；
- 若引入账号、支付、用户数据，再单独过 privacy/security/payment/compliance gate。

---

# 11. Historical Acceptance Pointer

旧 milestone 的专项验收条款不再留在当前文件。

历史可追溯于：

- Git history 中本文件旧版本；
- 对应 GitHub Issue；
- PR / review comments；
- Actions / artifacts；
- `docs/data-foundation/`；
- `docs/prediction-quality/`；
- `docs/model-governance/`；
- Memory-Hub Research Assets / Canonical Decision Lineage。

**任何已结束 milestone 的长清单再次复制回本文件，视为控制面污染。**

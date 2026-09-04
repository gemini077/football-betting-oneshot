# 17_NEXT_WORK_后续工作.md

最后更新：2026-09-04
角色：**只记录当前要做什么，以及为什么现在做。**

禁止保存历史 milestone、旧 STOP 状态、已关闭 Issue 正文。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. Product-Level Direction

状态：`MULTI-MARKET PREDICTION QUALITY REBASE LOCKED`

当前总门=`PUBLIC-LAUNCH-TRUST`。

当前技术/产品发动机=`MULTI-MARKET-PREDICTION-QUALITY`。

核心关系：

`预测质量 → prospective proof/trust → serving/product → public-launch gates`

Trust 不替代命中率/概率质量；命中率也不能脱离 coverage、baseline、proper score、sample/uncertainty、forecast horizon 单独宣传。

---

# 2. Current Bounded Execution

GitHub Issue #180：`EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`

Lane：`Data / Identity / Rights`。

目标：验证 current Reep v1 能否 deterministic 地桥接 FBOS 中文球队与 The Odds API 英文球队；只有身份成立后才 bounded probe `correct_score`。

边界：future-only / exact fail-closed / no fuzzy / no LLM translation / no bulk manual alias / no model or serving change / research-only PR。

**#180 不因 Roadmap correction 取消。完成后无论 PASS/FAIL，都必须回 Project Gate，不自动继续 identity/provider 子树。**

---

# 3. Background Work

Challenger C 自然 prospective accumulation。

Accepted：`56 verified unique / PROMISING_NOT_ESTABLISHED / shadow-only`。

- 不调 C；
- 不扫参数；
- 不因少量新增样本机械 review；
- 到 >=100 才进入新的 Promotion Review Gate；
- >=100 也不自动 Promotion。

---

# 4. Post-#180 Highest-Value Candidate — 不是预授权任务

## Candidate A — MULTI-MARKET-PREDICTION-COVERAGE-AND-EVALUATION-GAP-AUDIT

当前研究排序：`HIGHEST`。

优先只读回答：

1. current frozen FT joint score state 已经能数学一致推导哪些玩法？
2. current result truth 已能合法结算哪些玩法？
3. current unique prospective cohort 上，各玩法 full-coverage hit rate / proper score 是多少？
4. 若已有 selective serving，各玩法 served hit rate / coverage 是多少？
5. same-market strong/simple baseline 已有哪些？
6. actual freeze lead-time 分布怎样，T-24h / T-6h / T-60m 等是否可公平分层评价？
7. 1X2 Home/Draw/Away predicted mix、confusion matrix、per-class recall、Draw recall 是否健康？
8. 中国竞彩胜平负 / 让球胜平负 / 比分桶 / 0–7+总进球 / 半全场中，哪些只是缺 projection/evaluation，哪些缺 prematch line/truth？
9. HTFT 是否确实缺 first-half score/outcome truth？
10. 当前有哪些 xG/阵容/球员/伤停等 rich-feature surface 可做 paired incremental-value audit？
11. strongest / weakest market、competition、horizon 分别是谁？
12. 哪些 failure 是模型本身，哪些只是 evaluation/product/data/rights gap？

目的：先得到一张真实的“多玩法成绩与缺口地图”，再决定下一模型路线。

## Candidate B — Closed Beta Measurement Minimum

排序：`HIGH`。

低成本验证真实用户看什么玩法、能否理解 probability / strongest view / abstain、是否回看赛果、是否重复使用。

## Candidate C — Data Rights / Source Commercial Inventory

排序：`HIGH BEFORE PUBLIC SCALE`。

## Candidate D — Operations Release-Readiness Audit

排序：`HIGH BEFORE PUBLIC LAUNCH`。

## Candidate E — New Model / New Market Implementation

排序：`NOT BEFORE GAP AUDIT BY DEFAULT`。

只有 Candidate A 证明具体 per-market failure 后，才研究 Exact Score、handicap、goals、HTFT、market-specific head、xG/lineup/player 等哪条最值得做。

最终仍由：

`#180 accepted truth → Canonical Evolution Gate → Research-Backed route comparison → highest product information/value`

选择唯一下一项。

---

# 5. Current Market Priority

## Tier A — 中国竞彩

- FT 1X2 / 胜平负
- 让球胜平负
- 比分 / official score buckets
- 总进球 0–7+
- 半全场（先过 first-half truth gate）

## Tier B

O/U / BTTS / Asian/common handicap / team totals / winning margin / double chance 等。

禁止为了“玩法多”直接实现；先有 truth/evaluation。

---

# 6. Explicitly Not Next By Default

- Challenger E；
- Dixon-Coles/rho tuning；
- global lambda raise；
- half-life scan；
- friendlies weighting；
- provider hopping；
- bulk alias authoring；
- Trust Center UI 大改而没有逐玩法 scorecard；
- HTFT 用 90m lambda/2；
- 只为了“提高总命中率”加入 easy-market mix；
- T-24h 与 closing market 不公平比较；
- overall 1X2 accuracy 不查 Draw/class collapse；
- 因“高级”直接接 xG/球员/GNN；
- generic news/live-score/community expansion；
- EV/stake/portfolio。

---

# 7. Completion Rule

Founder 回复“已完成”时：

`Delta acceptance → Canonical Evolution Gate → 必要 Research Gate → route comparison → unique ACTIVE → self-contained Issue → Memory-Hub durable update → short Codex prompt`

如果事实推翻 Roadmap 假设，先改 Roadmap。

---

# 8. Historical Pointer

旧 Next Work 从 Git history、Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub 恢复。

**不得复制回当前文件。**

# 17_NEXT_WORK_后续工作.md

最后更新：2026-09-04
角色：**只记录当前要做什么，以及为什么现在做。**

禁止保存历史 milestone、旧 STOP 状态、已关闭 Issue 正文。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. Product-Level Roadmap Rebase

状态：`RESEARCH COMPLETE / STRATEGIC REBASE LOCKED`

旧串行路线 `data → model → analysis → product` 不再作为默认执行顺序。

当前 Program：`PUBLIC-LAUNCH TRUST`。

核心新增约束：

- serving 按 `Market × Competition Support × Evidence Quality × Prediction Quality` 分层；
- user confidence 必须有 calibration / reliability / sample evidence；
- Trust Center 不只显示 hit rate；
- Closed Beta 在模型完美前开始，但先补最小 measurement；
- Distribution / Business Model 独立 discovery，不复制 VIP/红单逻辑；
- Advanced Model R&D 只由 measured failure mode 触发。

详细路线见 `16_ROADMAP_项目路线图.md` 与 Memory-Hub Roadmap Rebase research asset。

---

# 2. Current Bounded Execution

GitHub Issue #180：

`EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`

Lane：`Data / Identity / Rights`。

这是一个 bounded preflight，不是 whole-product ACTIVE tree。

目标：验证 current Reep v1 能否 deterministic 地桥接 FBOS 中文球队与 The Odds API 英文球队；只有身份成立后才 bounded probe `correct_score`。

边界：future-only / exact fail-closed / no fuzzy / no LLM translation / no bulk manual alias / no model or serving change / research-only PR。

**#180 完成后必须回 Project Gate；无论 PASS/FAIL，都不得自动创建下一条 identity/provider Issue。**

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

# 4. Post-#180 Priority Gate — 候选排序，不是预授权任务

#180 验收后优先重新比较以下路线：

## Candidate A — Segmented Serving / Trust Surface Gap Audit

当前研究排序：`HIGH`。

先只读核对：

- 1X2 / O-U / BTTS / Exact Score 各自已有何种 prospective quality truth；
- 当前 competition universe 能否分成 SUPPORTED / LIMITED / EXPERIMENTAL；
- 当前页面已经展示哪些 degraded/abstain/evidence states；
- 哪些 confidence 仍不可验证；
- Trust Center 最小数据面是否已经足够。

目的：先定义真正需要工程实现的最小 trust surface，避免再凭感觉改 UI。

## Candidate B — Closed Beta Measurement Minimum

当前研究排序：`HIGH`。

在不引入重账户系统的前提下，设计最低成本的真实用户测量/反馈机制。

## Candidate C — Data Rights / Source Commercial Inventory

当前研究排序：`HIGH BEFORE PUBLIC SCALE`。

尤其要独立确认 production-critical Nowscore 与所有公开展示/缓存/衍生数据边界。

## Candidate D — Operations Release-Readiness Audit

当前研究排序：`HIGH BEFORE PUBLIC LAUNCH`。

核无人值守 freshness / silent missing / settlement / fail-safe / rollback / monitoring。

## Candidate E — New Model Research

当前研究排序：`NOT DEFAULT`。

只有新的 serving matrix / prospective evidence 暴露明确 failure mode 后才进入。

最终只能由：

`#180 accepted truth → Canonical Evolution Gate → Research-Backed route comparison → highest product information/value`

选出唯一下一项。

---

# 5. Explicitly Not Next By Default

- Challenger E；
- Dixon-Coles/rho tuning；
- global lambda raise；
- half-life scan；
- friendlies weighting；
- provider hopping；
- bulk alias authoring；
- generic news/live-score/community feature expansion；
- EV/stake/portfolio；
- uncalibrated high/medium/low confidence；
- 仅为了“看起来完整”造更多玩法。

---

# 6. Completion Rule

Founder 回复“已完成”时：

`Delta acceptance → Canonical Evolution Gate → 必要 Research Gate → route comparison → unique ACTIVE → self-contained Issue → Memory-Hub durable update → short Codex prompt`

如果事实推翻 Roadmap 假设，先改 Roadmap。

---

# 7. Historical Pointer

旧 Next Work 从 Git history、Issues/PR/Actions、`docs/*` evidence 与 Memory-Hub 恢复。

**不得复制回当前文件。**

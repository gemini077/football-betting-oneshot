# 17_NEXT_WORK_后续工作.md

最后更新：2026-09-04
角色：**只记录当前要做什么，以及为什么现在做。**

禁止保存历史 milestone、旧 STOP 状态、已关闭 Issue 正文。

长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`。

---

# 1. Product-Level Current Work

## ROADMAP-REBASE-2026-09-04

Owner：ChatGPT research line

目标：重新审视 Football Betting OneShot 的产品路线，避免继续沿早期“数据→模型→分析→产品”的串行假设机械推进。

本轮需要确认：

- 产品当前真正的用户价值与差异化；
- Prediction Trust 在全产品中的正确位置；
- User Trust / Trust Center / selective serving 是否应提前；
- Closed Beta 是否应在模型完美前开始；
- Data Rights / Compliance / Operations 是否被旧 Roadmap 排得过晚；
- Advanced Model R&D 应是主干还是 supporting lane；
- Public Launch 的真实多 Gate 标准。

研究结论形成后更新 Memory-Hub Canonical / Research Asset；不要把研究交给 Codex。

---

# 2. Current Bounded Execution

GitHub Issue #180：

`EXACT-SCORE-REEP-IDENTITY-BRIDGE-PREFLIGHT-1`

定位：Data / Identity / Rights lane 的 bounded preflight。

目标：验证 current Reep v1 能否通过 exact/typed aliases + competition context，把 FBOS 中文球队和 The Odds API 英文球队桥接到同一 stable team ID；身份成立后才允许 bounded `correct_score` probe。

边界：

- future-only；
- exact/fail-closed；
- no fuzzy / LLM translation / generated transliteration；
- no bulk manual aliases；
- no model / Champion / C / frozen truth / serving / promotion changes；
- research-only PR，DO NOT MERGE unless a later independent decision explicitly changes that contract。

**#180 完成后必须回项目级 Gate，不得自动创建 #181 继续 identity/provider 子树。**

---

# 3. Background Work — No Founder Time Required

Challenger C：自然 prospective accumulation。

Accepted checkpoint：`56 verified unique / PROMISING_NOT_ESTABLISHED / shadow-only`。

规则：

- 不调 C；
- 不扫参数；
- 不因新增几场就机械重跑 inference；
- 到 `>=100 unique` 才进入新的 Promotion Review Gate；
- >=100 也不自动 promotion。

---

# 4. Current Priority Candidates After Roadmap Rebase

下面只是**候选 lane**，不是预授权工程任务：

1. Prediction Trust / selective serving / external score benchmark；
2. User Trust / confidence / score scenarios / Trust Center；
3. Closed Beta user-validation instrumentation；
4. Data rights / cross-provider identity / source durability；
5. unattended operations / monitoring / fail-safe / rollback；
6. compliance / commercial readiness；
7. advanced model research only when a specific failure mode justifies it。

下一项只能由：

`Current truth → Product Gate → Research-Backed Route Comparison → highest-information / highest-product-value next step`

选出。

---

# 5. Explicitly Not Next By Default

除非新的项目级 Gate 重新证明价值，否则不默认启动：

- Challenger E；
- Dixon-Coles/rho tuning；
- global lambda raise；
- half-life scan；
- friendlies weighting；
- provider hopping；
- bulk alias authoring；
- UI richness expansion；
- EV / stake / portfolio；
- “为了提高命中率”但没有独立 evaluation plan 的模型改动。

---

# 6. Completion Rule

Founder 回复“已完成”时，不允许只验收上一项然后直接发下一条技术任务。

必须自动执行：

`Delta acceptance → Canonical Evolution Gate → 必要的 Research-Backed Next-Step Gate → route comparison → unique ACTIVE → self-contained Issue → Memory-Hub durable update → short Codex prompt`

如果新的事实表明当前 Roadmap 本身有问题，先改 Roadmap，不机械继续旧 ACTIVE。

---

# 7. Historical Pointer

旧 `17_NEXT_WORK` 的所有 milestone/STOP 流水账仍可从 Git history、Issues/PR/Actions、`docs/*` evidence 和 Memory-Hub Research Assets 找回。

**不得复制回当前文件。**

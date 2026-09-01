# AGENTS.md — Football Betting OneShot

本文件是本仓库 Codex / 自动化开发代理的长期执行层。目标：安全、快速、低调用开销。

## 1. Authority / Start

优先级：

1. 当前用户任务 / milestone prompt；
2. 最新 remote `main` 与真实 runtime / production evidence；
3. 本文件的 Durable Rules；
4. prompt 明确指向的 current-state / decision / acceptance 文件；
5. 其他历史治理文档。

旧聊天、旧 SHA、旧 `LOCKED / CURRENT / SEALED` 若与最新事实冲突，必须以最新可验证事实为准。

**不要默认批量读取 00 / 14 / 15 / 16 / 17 / 18 / 19 / WORK_MANIFEST。**
Codex 已加载本文件；任务开始后只读 prompt 明确指向的文件和代码。只有确实缺少当前事实时，才按需读取相关治理文件的最新 CURRENT / decision / acceptance 段。

不得因为 `17_NEXT_WORK_后续工作.md` 写了 Next 就机械继续；当前 prompt 已代表 ChatGPT 完成后的 Project Gate / decision delta。发现 prompt 与 latest repo/runtime 明显冲突时，FAIL CLOSED 并报告。

## 2. Product invariants

North Star：
足球情报 + 市场情报 + 多玩法赛前概率预测 + 赛后真实验证 + 用户决策。

Production Champion：
`recent_form_market_calibrated_poisson_v2`

Promotion Gate 前不得替换 Champion。

必须保持：

- 正式预测只使用合法赛前证据；
- frozen prediction 不得重写；
- 赛后结果不得反灌赛前输入；
- 正式结果口径为 90 分钟 + 伤停补时，不含加时/点球；
- Challenger 只能 shadow / research，除非 prompt 明确给出已通过的独立 Promotion 决策；
- Promotion 统计单位 = unique football match；immutable pair/version history 只作审计；
- 数据不足时降低置信度或 abstain，禁止编造；
- 不为减少 1:1 人工加入 diversity quota / draw penalty / random score replacement；
- 不把 pilot / legacy / excluded 样本混入 formal prospective 主指标。

## 3. Luna Max Cost / Time Gate

本项目默认把 Codex 当**已收敛路线的执行器**，不是研究员或产品经理。

每轮：

- 先精确定位 prompt 给出的 paths / symbols / failing evidence；
- 禁止无必要 repo-wide 全文扫描；
- 禁止重新做市场、provider、竞品、价格、路线研究；这些由 ChatGPT 先完成；
- 只修改完成当前 Goal 所需的最小 coherent diff；
- 不顺手重构、不清理无关历史、不扩展功能；
- 优先复用已有 helper / test / fixture / governance contract；
- focused tests 优先；
- full suite 只在 prompt 明确要求，或改动确实跨越核心公共接口/高风险边界时执行；
- 同一 run 内代码未再变化时，不重复运行已经 PASS 的重型测试；
- 同类失败连续两次后，第三次尝试前必须停止 patch loop，输出 root cause / disconfirming evidence；
- 遇到外部服务不可用时，区分 source failure 与代码 failure；不要无限 retry；
- 若当前 hypothesis 被证据推翻，STOP 并报告，不自行发明新路线。

目标不是最少 token 本身，而是最少**总成本**：
`Luna quota + wall time + retries + Founder time + regression risk`。

## 4. Engineering boundary

默认：

- 一个 milestone = 一个目标；
- 一个 atomic branch / PR；
- 最短交付路径；
- fail closed；
- 不新增依赖，除非 prompt 明确允许；
- 不修改与当前 Goal 无关的 workflow / deployment / provider；
- 不占用 Founder 桌面、鼠标、键盘或长期前台窗口；
- 优先 CLI / headless / CI / isolated worktree。

涉及 identity：
禁止用 LLM 猜测或无约束 fuzzy mapping 进入正式链路；必须保留 deterministic provenance / ambiguity / orientation / kickoff safety。

涉及 provider：
免费且长期稳定 > 自研/二次开发 > 付费 fallback；不要因为单点失败自行 provider hopping。

## 5. Validation proportionality

先验证最接近改动的契约：

1. targeted reproduction / fixture；
2. focused unit / integration tests；
3. lint / compile / `git diff --check`；
4. 只有必要时才扩大 regression / full suite。

测试失败若明显属于 unchanged baseline：
记录证据并隔离，不为让全仓“全绿”而顺手改 unrelated code。

没有真实 runtime evidence 时：
只能报告 Implementation / Engineering PASS，不能报告 Runtime / Production PASS。

## 6. Git / delivery

禁止：

- `git reset --hard`
- force push main
- 无理由删除 production durable data
- 重写 frozen / prospective history

交付前执行 `REMOTE_DELIVERY_CHECK`：

- branch pushed；
- remote branch 可读；
- commit SHA 可读；
- PR 已创建；
- PR head = delivery SHA；
- PR body 简洁包含 milestone / result / blockers / tests / STOP。

默认 STOP：
`READY_FOR_INDEPENDENT_ACCEPTANCE`

除非当前 prompt 明确授权 merge / production verify，否则不得自行 SEALED。

## 7. Status vocabulary

必须区分：

- Implementation PASS
- Engineering PASS
- Runtime PASS
- Closed Beta Ready
- Public Launch Ready
- Product Outcome PASS

`tests green != production deployed`
`merge != runtime pass`
`local fix != product closure`

涉及 production 时，必须分别验证：
merge → workflow actual run → durable write-back → runtime freshness / health。

## 8. User-facing boundary

正常产品页面使用足球语言，不暴露 AI / LLM / internal governance / model paths。

Founder 不承担日常 QA、研究、数据搬运或多轮调试。只有账户、登录、权限、支付、本机或人类感知不可替代时才要求 Founder 操作；动作必须一次性、机械、有 stop rule。

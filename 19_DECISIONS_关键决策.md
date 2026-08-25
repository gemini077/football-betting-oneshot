# 19_DECISIONS_关键决策.md

最后更新：2026-08-17  
角色：记录不能因换对话 / 换 Codex 而重复推翻的关键决定。若新证据足以改变决定，必须新增 superseding decision，不得静默改历史。

# D-001 — Prediction Universe 是当天 canonical schedule

状态：LOCKED

完整赛程更新 Universe。Filtered / single-match fetch 不得覆盖全天 Universe。

# D-002 — Frozen prediction immutable

状态：LOCKED

赛后只能追加 result / evaluation，不能改写赛前预测。

# D-003 — 足球业务时间使用 Asia/Shanghai

状态：LOCKED

# D-004 — 正式结果口径

状态：LOCKED

90 分钟 + 伤停补时，不含加时和点球。

# D-005 — Legacy Mapper 不再发展

状态：LOCKED

仅用于 historical compatibility。

# D-006 — Homepage Slice 1A 保持封版

状态：LOCKED UNTIL REAL PRODUCT EVIDENCE

# D-007 — P0 Workspace Auto-Update Recovery 已完成

状态：SEALED / DEPLOYED

# D-008 — Current exact-score selector 判定 FAIL

状态：LOCKED UNTIL NEW EVIDENCE

2026-08-15：FROZEN 23；21/23 unique score = 1-1；1X2 leader HOME 12 / AWAY 11 / DRAW 0。

# D-009 — 不直接启用 Outcome-conditioned MAP

状态：LOCKED UNTIL NEW PROSPECTIVE EVIDENCE

Formal 14：Exact Top1=0%，selection outcome=28.57%。

# D-010 — 不直接启用 Existing Scenario Challenger

状态：LOCKED UNTIL NEW PROSPECTIVE EVIDENCE

Freeze-time replay 有效，但 Formal 14：Exact Top1=0%，selection outcome=28.57%。

# D-011 — 不人工惩罚 1-1 / 平局

状态：LOCKED

禁止 1-1 penalty、draw penalty、每日 diversity quota、随机改比分。

# D-012 — 当前主问题进入 λ / team-strength 层

状态：LOCKED FOR CURRENT PROGRAM

问题不只是 selector，还包括 lambda compression。

# D-013 — PA-2 Challenger 只作为 Research / Shadow

状态：LOCKED

`opponent_adjusted_strength_poisson_v1` 尚未完成 production paired validation。

# D-014 — CA-1 当前暂停

状态：LOCKED UNTIL PREDICTION QUALITY GATE

禁止用高级自动分析包装已知存在结构问题的预测。

# D-015 — Canonical Identity 禁止 fuzzy 猜测

状态：LOCKED

允许 deterministic provider ID / canonical registry / exact unique alias。

# D-016 — Promotion 必须 prospective

状态：LOCKED

约 40–50 新 prospective 后才进入严肃 review；约 100+ 更成熟样本后才考虑 Champion promotion。

# D-017 — 数据覆盖按阶段治理

状态：LOCKED

不因少量缺口自动 provider hopping；历史赛事扩展按真实 blocker 定向进行。

# D-018 — 用户页面不暴露工程/AI术语

状态：LOCKED

# D-019 — 验收通过不等于已部署

状态：LOCKED

必须核 remote main、workflow、durable state、Pages、health。

# D-020 — Codex 不得自行 SEALED

状态：LOCKED

完成任务只能标记 READY_FOR_ACCEPTANCE。

# D-021 — 正式交付在仓库外

状态：LOCKED

`D:\MyProject\_deliveries\football-betting-oneshot\`

# D-022 — 默认不占用用户电脑前台

状态：LOCKED

优先 CLI / headless / scripts / worktree / CI。

# D-023 — 重大模块与 build-vs-buy 必须做当前缺口驱动的定向研究

状态：LOCKED

研究从当前 Football Betting OneShot 的产品、模型、数据与验证状态开始，不默认运行脱离产品需求的每日市场新闻/工具雷达。每个研究周期必须先选定并排序明确的产品/模型/数据/验证缺口，写明为什么现在优先；研究只围绕选定缺口提供证据，不得直接改动 Champion、生产模型或其他生产状态。

任何重大模块或 build-vs-buy 决策，必须针对选定缺口执行 `landscape → shortlist → horizontal compare → bounded validation → build/adopt/hybrid`，不得采用“用户找到一个候选 → 代理只研究该候选 → 沿近邻线索停止”的反应式流程。Landscape 必须覆盖所有实质不同的解决类别：直接竞品、替代方案、相邻类别、开源项目、国内外商业工具/API、上游/下游组件、fork/upstream/downstream 路线、近期发布或更新的选项、成熟旧方案，以及现实可行的低成本组合。用户提供的工具或仓库只是搜索种子，永远不是完整候选集。

每轮必须维护 shortlist 并做横向比较，至少比较适配度、质量、成本、许可证、数据合法性与可持续性、维护健康度、集成/迁移成本和锁定风险，明确选择直接使用、fork、改造、借鉴、混合或拒绝。近期/新工具不能挤出能更好解决当前缺口的成熟旧方案；重要主张必须核验，不得把营销文案当事实。

每轮研究记录必须包含：(1) 选定的当前产品缺口；(2) 为什么现在优先；(3) 候选解决类别；(4) 横向比较；(5) 如果今天从零开始是否仍会自建；(6) 最小验证实验与替换/采用门槛；(7) 对当前路线图的具体影响。对当前自研模块必须回答第 (5) 项；若答案为否，须定义替代方案。新发现本身不是架构变更理由；替换/采用必须有明确预期收益阈值和有界实验。研究结果只在与当前缺口实质相关时反馈到决策和路线图，且不得绕过 Champion、production、acceptance 或 promotion 既有门禁。

# Current Facts — 不是永久 Decision

以下未来可随新 artifact 更新：

- production Champion：`recent_form_market_calibrated_poisson_v2`
- calibration artifact 当前 `shadow_only / active=false`
- current production `rho=0.0`
- PA-2 historical Challenger Brier/LogLoss 优于 uniform，但 exact-score 1-1 仍过度集中。

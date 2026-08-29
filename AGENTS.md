# AGENTS.md — Football Betting OneShot Repository Rules
## 2026-08-28 CURRENT AUTHORITY

- 最新 `origin/main` 与真实 production evidence 优先于旧聊天、旧本地状态和旧 `LOCKED / CURRENT / SEALED` 叙述；冲突时以最新可验证事实为准，但不得伪造状态。
- 仓库治理阅读顺序：`14 → 15 → 19 → 16 → 17 → 18 → 00 → WORK_MANIFEST`。只引用仓库真实存在的文件。
- 产品 North Star：足球情报 + 市场情报 + 多玩法赛前概率预测 + 赛后真实验证 + 用户决策。
- `Market State / Football Evidence / Prematch Intelligence` 必须分层，并记录 `freshness / completeness / confidence`。证据质量决定影响力；低质量 shallow recent form 不能仅因固定权重覆盖 `FULL` market。现有 `60/40` 与 `65/35` 只是 legacy implementation，不是产品原则。
- `recent_form_market_calibrated_poisson_v2` 仍是 production Champion；Promotion Gate 前不得替换。
- 同一历史样本上的权重扫描、调参和回放只用于提出 hypothesis，不能直接 promotion；升级必须经过 prospective Shadow、按 unique match 评估和 Promotion Gate。
- bounded issue 收口后必须回到产品层，不得围绕 `1:1`、lambda 或单点表象连续打补丁。
- 产品必须边运行边优化；数据不足时降低置信度或不输出对应玩法，禁止编造。成本优先级：免费且长期稳定 > 自研 / 二次开发 > 付费 benchmark / fallback。
- `17_NEXT_WORK_后续工作.md` 是当前唯一执行指针；旧 PA-2-R1 / 1:1 / lambda / Shadow 记录只有在 17 的最新 `CURRENT` 块明确要求时才能恢复。

本文件是 Codex / 自动化开发代理进入本仓库时必须优先遵守的仓库级规则。

## 1. 每次任务开始前必须阅读

按以下顺序读取：

1. `14_PRODUCT_BLUEPRINT_产品全貌.md`
2. `15_PROJECT_STATUS_项目状态.md`
3. `16_ROADMAP_项目路线图.md`
4. `17_NEXT_WORK_后续工作.md`
5. `18_ACCEPTANCE_验收标准.md`
6. `19_DECISIONS_关键决策.md`
7. `00_PROJECT_INSTRUCTIONS_粘贴到项目指令.md`
8. `WORK_MANIFEST.json`

然后再根据当前任务读取对应业务/技术文件。

如果这些文件与旧历史文档冲突，以更新、更具体的当前状态、关键决策和验收标准为准。不得静默覆盖已锁定决定。

## 2. 当前产品定位

本项目是“足球情报 + 市场情报 + 赛前概率预测 + 赛后真实验证”的足球分析平台。

竞彩、亚盘、大小球、比分、EV、组合策略属于下游应用，不是所有开发工作的默认主线。

核心优先级：

1. 数据真实、完整、可追溯；
2. 预测赛前冻结、赛后不可篡改；
3. 模型质量通过真实 prospective 验证；
4. 用户能快速理解比赛结论、证据与风险；
5. 再扩展投注决策层。

禁止为了页面完整、分析好看或命中率叙事而掩盖底层模型问题。

## 3. 当前唯一主线

以 `17_NEXT_WORK_后续工作.md` 为唯一当前任务指针。

当前主线：

`17_NEXT_WORK_后续工作.md` 顶部最新 `CURRENT` 块定义当前主线；这里不再硬编码历史 Phase。

除非该文件被正式更新，否则不得擅自启动 Roadmap 中后续阶段。

## 4. 阶段状态权限

Codex / 开发代理不得自行宣布某阶段 `SEALED`。

允许状态流转：

`CURRENT → READY_FOR_ACCEPTANCE → PASS/FAIL（独立验收） → SEALED`

完成代码、测试全绿或生成交付 ZIP，只能说明 `READY_FOR_ACCEPTANCE`。

只有独立验收通过后，才允许将阶段标记为 `SEALED`。

## 5. Production / Research 边界

当前正式 Champion：

`recent_form_market_calibrated_poisson_v2`

已知其 exact-score headline 存在严重结构性 collapse。不能将当前“唯一比分”包装成高可信结论；但在没有通过 promotion gate 前，也不得直接替换 production Champion。

研究 Challenger 必须保持 shadow / research only。

禁止：

- 重写已有 frozen prediction；
- 赛后重跑模型冒充赛前预测；
- 用真实结果调当前比赛的 shadow 输出；
- 为减少 1-1 人工加入 score diversity、draw penalty、随机化；
- 未验证即启用 Outcome-conditioned 或 Scenario Challenger；
- 修改历史 prospective ledger 以改善指标；
- 将 pilot / legacy / excluded 样本混入 formal prospective 主指标。

## 6. 数据与时间规则

- 足球业务日期统一使用 Asia/Shanghai（UTC+8）。
- Prediction Universe 是当天赛程 canonical schedule。
- 正式结果口径：90 分钟 + 伤停补时，不含加时和点球。
- 正式研究必须防 future leakage；训练数据时间必须早于评价比赛。
- Canonical competition/team identity 是后续模型研究与产品数据层的基础能力。
- 禁止 fuzzy / LLM / 人工猜测式 identity mapping 进入正式链路。

## 7. 用户界面语言

正常用户页面使用足球产品语言，不暴露内部工程术语。

用户界面不得突出：

- AI / LLM / OpenAI；
- Claim / Validator / Taxonomy；
- FUSION_BASELINE；
- Frozen / lineage / governance；
- internal model family / internal file path。

工程信息只能放低权重、默认折叠的技术详情中。

## 8. 开发方式

默认：

- 成品优先；
- 最短交付路径；
- 小阶段、唯一任务名；
- 先修阻塞真实产品价值的问题；
- 不因为 Roadmap 存在未来阶段就顺手一起开发；
- 不做与当前阶段无关的重构。

凡需要占用用户桌面、鼠标、键盘或长期前台窗口的方式默认禁止。

优先后台脚本、CLI、headless、独立工作目录、临时 worktree、CI。

### 工具与市场发现

凡涉及重大模块或 build-vs-buy，执行顺序必须是 `landscape → shortlist → compare → bounded validation → build/adopt`。用户提供的工具或仓库只是搜索种子，不是完整候选空间；必须主动扩展到竞品、替代方案、相邻类别、开源项目、国内外商业工具/API、上下游组件、近期更新和低成本组合，并以 D-023 的比较与门禁规则为准。发现结果不得绕过现有 Champion、生产、验收或 promotion 门禁，也不得仅因出现新选项就无界限地 churn 架构。

## 9. Git 与交付

项目正式验收/交付目录位于仓库外：

`D:\MyProject\_deliveries\football-betting-oneshot\`

仓库内不得新增正式交付副本目录：

- `deliverables/`
- `delivery/`
- `handoff/`
- `evidence/`
- `screenshots/`
- `submission/`

历史 `artifacts/*handoff.zip` 属于待治理遗留物，不得在无独立清理任务时顺手删除。

临时 staging 使用 `%TEMP%`。

不得 `git reset --hard`、不得 force push、不得无理由清理 production durable data。

## 9A. REMOTE_DELIVERY_CHECK（永久规则）

从本规则生效起，每个后续 milestone 在任务结束前都必须执行一次
`REMOTE_DELIVERY_CHECK`，无论结果是 `READY_FOR_ACCEPTANCE`、`BLOCKED`、
`INCONCLUSIVE`、`NOT_IMPLEMENTED` 还是 `CREDENTIAL_MISSING`。

必须确认：

1. 当前交付 branch 已 push；
2. remote branch 存在；
3. commit SHA 可从 GitHub 读取；
4. GitHub PR 已创建；
5. PR head SHA 与本地交付 SHA 一致；
6. PR body 包含 milestone、result、blockers、tests/evidence 和 STOP state。

阻塞或未实现的 milestone 也必须创建最小 GitHub evidence PR。只有在
branch、commit、PR 和 head SHA 均可从 GitHub 读取后，才可向用户报告远端
交付状态；本地文件存在或本地提交本身不构成远端交付证据。

## 10. 任务完成时必须做的事

每个阶段结束时：

1. 按 `18_ACCEPTANCE_验收标准.md` 自检；
2. 运行该阶段 focused tests；
3. 运行完整测试（若阶段要求）；
4. 验证 production mutation safety；
5. 生成规定的仓库外交付；
6. 将阶段标记为 `READY_FOR_ACCEPTANCE`，不得自称 SEALED；
7. 如阶段改变项目事实，更新：
   - `15_PROJECT_STATUS_项目状态.md`
   - `17_NEXT_WORK_后续工作.md`
   - `16_ROADMAP_项目路线图.md`（仅当路线变化）
   - `19_DECISIONS_关键决策.md`（仅当有新锁定决定）

## 11. 部署类任务的额外验收

“测试通过”或“本地代码完成”不等于“已经上线”。

涉及 production / Pages / workflow 的任务，必须区分：

- local code accepted；
- remote branch / PR；
- merge to `main`；
- workflow actual run；
- durable GitHub state；
- actual Pages；
- runtime freshness / health。

没有真实远端证据时，不得写“已部署”。

## 12. 冲突处理

若当前任务要求与仓库状态、Roadmap、关键决策冲突：

- 不得默认照做；
- 先指出冲突；
- 优先保护 frozen history、prospective integrity、production Champion、自动化和数据完整性；
- 需要改变已锁定决定时，必须留下新证据和明确决策记录。

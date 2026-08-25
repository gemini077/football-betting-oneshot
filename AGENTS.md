# AGENTS.md — Football Betting OneShot Repository Rules

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

`Phase PA-2-R1 — Canonical Identity & Paired Challenger Evaluation`

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

市场/工具研究必须是 `CURRENT-PROJECT-CONTEXT + PRODUCT-GAP DRIVEN`，不是脱离产品需求的泛化每日市场新闻或工具雷达。每个研究周期先读取当前 Football Betting OneShot 产品、模型、数据与验证状态，明确并排序本周期要解决的产品/模型/数据/验证缺口，再对选定缺口做定向研究；不得采用“用户找到一个工具 → 只研究该工具 → 沿该工具扩展”的反应式流程。

对选定缺口，执行顺序必须是 `landscape → shortlist → horizontal compare → bounded validation → build/adopt/hybrid`。Landscape 必须覆盖所有实质不同的解决类别，包括直接竞品、替代方案、相邻类别、开源项目、国内外商业工具/API、上游/下游组件、fork/upstream/downstream 路线、近期工具与成熟旧方案，以及可行的低成本组合。用户提供的工具或仓库只能作为搜索种子，不能作为候选集；重要主张必须核验，不得把营销文案当事实。

每轮研究记录必须明确：

1. 选定的当前产品缺口，以及为什么现在优先；
2. 候选解决类别；
3. 横向比较结果；
4. 如果今天从零开始，是否仍会自建；
5. 最小验证实验，以及替换/采用门槛；
6. 对当前路线图的具体影响。

研究结论不得绕过现有 Champion、生产、验收或 promotion 门禁，也不得仅因出现新选项就无界限地 churn 架构。只有与当前缺口和路线图有明确关系的研究结果才进入决策记录；成熟旧方案若更能解决当前缺口，必须与新工具同台比较。

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

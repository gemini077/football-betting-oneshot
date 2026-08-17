# 14_PRODUCT_BLUEPRINT_产品全貌.md

最后更新：2026-08-17  
文档角色：产品长期北极星。描述“最终要造什么”，不是当前任务清单。

# 1. 一句话产品定义

Football Betting OneShot 的长期产品形态是：

> 一个能够自动形成、记录、解释并长期验证自己足球判断的“足球情报 + 市场情报 + 赛前概率预测”平台。

竞彩、亚盘、大小球、比分、EV 和串关属于下游使用场景，不是产品本体。

# 2. 产品为什么存在

普通足球信息服务通常只解决其中一部分问题：

- 只给新闻，没有明确结论；
- 只给赔率，没有足球解释；
- 只给预测，没有真实长期验证；
- 只给“命中率”，但赛前答案不可追溯；
- 只堆模型指标，普通用户看不懂比赛为什么会这样。

本产品要把这些能力连接成闭环：

`比赛发现 → 足球证据 → 市场证据 → 概率预测 → 赛前冻结 → 用户解释 → 赛后验证 → Challenger 研究`

# 3. 核心用户

## 3.1 足球分析用户

需要快速知道：

- 谁更强、谁更可能掌握主动；
- 比赛节奏可能快还是慢；
- 双方的主要得分路径；
- 最可能的比赛过程；
- 最大的不确定性和错误触发点。

## 3.2 竞彩 / 盘口用户

重点关注：

- 1X2；
- 亚洲让球；
- 大小球；
- BTTS；
- 比分分布；
- 市场变化；
- 模型与市场的同步和冲突。

## 3.3 模型验证型用户

需要确认平台过去是否真的有效：

- 赛前预测是否冻结；
- 赛果是否真实；
- 1X2 / Goals / BTTS / Exact Score 的长期指标；
- 哪类比赛表现更好、哪类更差；
- Challenger 是否经过真实样本验证。

# 4. 四个不可牺牲的产品价值

## 4.1 自动

每天比赛自动进入 Prediction Universe，不依赖用户逐场手工选择。

## 4.2 有结论

平台不能只堆数据，必须回答：

> 这场比赛最可能怎么发展？

## 4.3 有证据

不能只有“模型说”。结论需要可追踪到真实足球事实、市场证据和冻结概率状态。

## 4.4 可验证

每个正式预测都必须满足：

`赛前冻结 → 比赛结束 → 真实90分钟结果 → 自动评分 → 长期累计`

赛后不得修改赛前答案。

# 5. 最终用户产品结构

## 5.1 今日比赛中心

首页是扫描层，不是工程 dashboard。

每场比赛卡片最终应优先呈现：

- 开赛时间 / 赛事 / 对阵；
- 主方向；
- 首要比分情景 + 相邻比分；
- 总进球方向；
- BTTS；
- 当前亚洲盘 / 大小球；
- 市场方向或明显变化；
- 一句比赛脚本；
- 最大风险；
- 数据状态。

不应优先显示内部 model family、内部字段名、文件路径或工程状态码。

## 5.2 单场比赛详情

### Layer 1 — 30 秒结论

回答“这场到底怎么看”：

- 主方向；
- 首要比分情景；
- 相邻比分；
- 总进球；
- BTTS；
- AH / O-U；
- 1X2；
- 2–3 句比赛脚本；
- 最重要支持证据；
- 最大冲突；
- 最大错误触发点。

### Layer 2 — 比赛为什么会这样

固定五段：

1. 强弱与主动权；
2. 节奏与进球环境；
3. 得分路径；
4. 关键分叉 / 最大不确定性；
5. 最终收敛。

### Layer 3 — 完整证据

包括：

- 球队近期状态；
- 主客场表现；
- 对手强度；
- 进攻 / 防守效率；
- xG / 射门 / 射正 / Big Chances（有可靠数据时）；
- 阵容 / 伤停 / 休息（有可靠数据时）；
- 市场盘口与时间变化；
- 数据来源；
- 冻结预测和更新时间；
- 技术详情（默认折叠）。

# 6. 预测引擎的长期目标形态

最终预测状态应来自：

`Team Strength`
`+ Recent Performance`
`+ Opponent Adjustment`
`+ Competition Context`
`+ Home/Away`
`+ Market Intelligence`
`+ Lineup / Availability`
`+ Match Context`
`→ lambda / probability state`
`→ score distribution`
`→ 1X2 / Totals / BTTS / Score Scenarios`

当前 `recent_form_market_calibrated_poisson_v2` 只是早期 production baseline，不代表最终预测架构已经完成。

# 7. Football 与 Market 的关系

正式目标不是“模型对抗赔率”，而是：

> Football + Market Intelligence Fusion

必须长期保留至少三个可区分层：

- Football-only；
- Market-only；
- Fusion。

这样才能知道模型是否真正具有足球判断价值，还是只是复制市场。

市场层最终应关注：

- 多公司 1X2；
- 亚洲让球；
- 大小球；
- BTTS；
- 球队进球数；
- 正确比分；
- 半场；
- 时间轴；
- 多市场同步 / 背离；
- 热门拥挤与真实防范。

# 8. Canonical Football Identity

整个数据层最终需要稳定的：

- canonical competition identity；
- canonical team identity；
- provider identity crosswalk；
- canonical fixture identity。

这不是单一研究模块，而是 Elo、对手强度、xG、交锋、球员、教练、阵容、伤停以及模型评估的共同地基。

原则：

> 宁可明确 UNKNOWN，也不能 fuzzy 猜错球队。

# 9. Immutable Prediction

正式预测必须保存：

- fixture identity；
- source cutoff；
- input snapshot；
- model identity；
- probabilities；
- lambda；
- score distribution；
- freeze timestamp；
- source / model fingerprints。

赛后只能追加结果与评价，不能改写赛前预测。

# 10. 赛后验证中心

长期产品应让用户直接看到真实模型表现，而不是只在后台 ledger 中存在。

未来可展示：

- 最近 N 场 1X2 Top1；
- Brier；
- LogLoss；
- Goal MAE；
- BTTS Brier；
- Exact Top1 / Top3 / Top5 / Top10；
- Score NLL；
- 分联赛 / 强热门 / 均势 / 高低总球场景表现；
- Champion vs Market-only；
- Champion vs Shadow Challenger。

禁止只宣传单一“命中率”。

# 11. Research / Challenger 系统

任何新模型都应遵循：

`Research → Historical Holdout → Prospective Shadow → Review → Promotion Gate`

可能存在：

- Opponent-adjusted strength challenger；
- Dixon-Coles calibration challenger；
- xG challenger；
- lineup-impact challenger；
- player-strength challenger。

研究模型不得因短期表现好就直接进入用户页面。

# 12. Prediction Sanity Monitoring

系统 Health 不应只检测“脚本是否退出 0”。

长期要覆盖：

## 数据健康

- 今日 Universe 是否完整；
- 数据是否新鲜；
- 是否 silent missing；
- identity 是否成功；
- football / market evidence 覆盖。

## 预测健康

- unique-score 是否异常集中；
- 1-1 / draw score 是否异常；
- lambda 是否异常压缩；
- 概率是否漂移；
- Challenger 是否异常。

## 产品健康

- Workspace 日期；
- Dashboard 日期；
- Match detail 可达；
- Pages freshness；
- downstream fixture coverage。

# 13. 自动化最终形态

长期希望用户无需每天手工运行脚本：

`发现比赛`
`→ Universe`
`→ Canonical Identity`
`→ 数据采集`
`→ Prediction`
`→ Freeze`
`→ Market Update`
`→ Analysis`
`→ Site`
`→ Result`
`→ Evaluation`
`→ Model Review`

# 14. Betting Decision Layer 的位置

EV、价值盘、stake sizing、串关、组合风险等属于预测之后的 downstream layer。

只有当：

`概率可信 + 校准可验证 + 市场价格可执行`

之后，才值得把投注决策层重新提升为主开发路线。

# 15. 产品明确“不是什么”

本产品不是：

- 自动下注机器人；
- 滚球交易机器人；
- 单纯赔率展示站；
- 单纯聊天机器人；
- 每天随便给几个比分的预测器；
- 通过赛后修改答案制造高命中率的系统；
- 网络博主观点搬运器。

# 16. 产品全貌

```text
                 Football Intelligence Platform

┌─────────────────────────────────────────────────┐
│                  今日比赛中心                    │
│ 比赛 │ 预测 │ 市场 │ 风险 │ 数据状态            │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│                  单场比赛详情                    │
│ 30秒结论                                         │
│ 强弱 → 节奏 → 得分路径 → 分叉 → 最终收敛       │
│ 球队证据 │ 市场证据 │ 来源 │ 风险               │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│               Prediction Engine                 │
│ Team Strength / Form / Opponent / Market /      │
│ Context → 1X2 / Goals / BTTS / Score            │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│              Immutable Prematch Freeze          │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│                  赛后真实验证                    │
│ Result → Metrics → Prospective                  │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│                Research / Challenger            │
│ Shadow → 足够样本 → Review → Promotion Gate     │
└─────────────────────────────────────────────────┘
```

# 17. 产品建设优先级

任何新需求都应先问：

1. 它是否提高真实预测质量、证据质量或可验证性？
2. 它是否解决当前用户核心理解问题？
3. 是否已有可复用开源/现有能力？
4. 是否需要现在做，还是 Roadmap 后段才需要？
5. 是否会让产品看起来更复杂但没有真实价值？

如果只是“看起来高级”，默认延后。

# 输入规范

## 0. 自动获取与用户必需输入

系统应先运行 `scripts/fetch_football_data.py` 获取公开赛程、竞彩赔率、500比赛ID和市场数据。只有以下内容仍需用户优先提供：

- 用户实际购买渠道及可成交赔率；
- 只存在于用户截图、私有JSON或账户页面的价格与销售状态；
- 用户是否停止临盘更新；
- 明确的“锁单/已下单”确认。

用户实际渠道赔率不是生成首份报告的前置阻塞项：首份报告先用最新抓取赔率完成EV初审；用户补充渠道赔率后，再进行执行价复审。

确认首发、伤停、天气、场地与高级统计由系统继续联网核验；抓不到时再列为缺失输入。

## A. 比赛基础信息
```json
{
  "competition": "",
  "stage": "",
  "home": "",
  "away": "",
  "business_date": "",
  "kickoff_local": "",
  "timezone": "",
  "venue": "",
  "neutral": true,
  "analysis_timestamp": "",
  "minutes_to_kickoff": 0
}
```

`business_date` 为竞彩业务日期；`kickoff_local` 为实际北京时间开球时间，两者可能因跨午夜而不同。

## B. 赔率时间轴
每条必须含：
```json
{
  "source": "Pinnacle/Bet365/澳门/竞彩/交易所/截图",
  "market": "1X2/AH/OU/BTTS/team_total/correct_score",
  "timestamp": "",
  "line": "",
  "odds_format": "decimal/hong_kong/malay/indonesian",
  "home_or_over_odds": null,
  "away_or_under_odds": null,
  "normalized_decimal_odds": null,
  "raw_text": ""
}
```

所有EV计算统一使用十进制赔率。香港盘1.76表示净盈利1.76、十进制返还赔率2.76；十进制1.76表示含本金总返还1.76。未标明赔率格式时不得直接计算EV。

为执行基础MBI，深层市场数据还必须保留：

- 博彩公司名称和稳定 `cid`；
- 公司层级：Sharp / Asian / Retail；
- 欧赔开盘、即时、变化时间；
- 亚洲盘开盘盘口、即时盘口、两侧水位和变化时间；
- 大小球开盘盘口、即时盘口、两侧水位和变化时间；
- 必发三向价格、成交量、成交占比及交易明细时间序列；
- 必发back/lay方向、已成交/未成交状态、各价位可用深度、累计成交量与适用佣金；
- 30家公司平均值、离散值及其是否为推导值；
- 联赛DRI校准基线版本。

如需计算固定赔率市场的赛果情景盈亏，必须提供同一运营方、同一市场、同一截止时间的三项实际投注额和对应十进制赔率。媒体投票、客户调查、隐含概率、交易所成交量或第三方“投注比例”不得冒充实际投注额；缺少任一项时只能显示页面模拟值，不得输出机构利润。

缺失字段不能用叙述补成数值。允许降级计算时，必须同时输出 `calculation_status=degraded` 和缺失原因。

## C. 截图处理
读取截图后先输出：
- 截图时间；
- 公司；
- 市场；
- 初盘；
- 当前盘；
- 是否缺页；
- 无法辨认字段。
禁止把模糊数字猜成确定值。

若截图来自第三方预测软件，还必须记录：

- 工具/供应商名称、网址或应用标识；
- 模型或页面版本、生成时间、数据截止时间；
- 预测口径：90分钟、含加时、晋级或其他；
- 原始实力评分及评分尺度说明；
- 主胜、平局、客胜三项概率及其合计；
- 主客λ、比分矩阵或Top比分（若页面提供）；
- 是否公开ELO参数、xG供应商、Poisson修正、训练窗口和样本外校准结果；
- 页面免责声明、缺失字段和无法核验的算法宣传。

无法取得上述元数据时，统一标记 `external_model_status=uncalibrated_signal_only`。不得把第三方软件的单项百分比与本模型概率直接平均，也不得用于EV、Kelly或锁单。

Polymarket公开市场快照遵循 `schemas/polymarket_analysis_snapshot.schema.json`，至少保存事件ID、game ID、英文队名、开球时间、市场类型、合约ID、问题文本、结算来源、90分钟口径、买一、卖一、中间价、价差、流动性、24小时成交量、费用配置、是否开盘和抓取时间。三项胜平负必须来自同一事件的完整互斥集合；波胆必须包含“Any Other Score”尾部。固定标记 `analysis_input_only=true`、`used_for_ev=false`、`execution_source=false`、`account_connected=false`、`trading_enabled=false`，未完成时间外校准前不得改变融合概率或投注层。

## D. 体彩JSON
优先读取：
- HAD：胜平负；
- HHAD：让球胜平负；
- CRS：正确比分；
- TTG：总进球；
- HAFU：半全场；
- updateDate/updateTime；
- poolStatus；
- bettingSingle/bettingAllup。

## E. 基本面
尽量提供或联网核验：
- 预计/确认首发；
- 伤停停赛；
- 近5场逐场数据；
- xG、射门、射正、Big Chances；
- 教练与战术；
- 旅行、体能、天气、场地。

大小球建模需进一步保留：联赛与赛季基准进球率、主客场拆分、对手强度校正、样本时间窗与衰减参数、预计首发及关键进攻/防守球员状态、休息天数与连续作战次数。静态球队“大球/小球”标签或文章中的固定加减幅度不得代替这些字段；缺失时扩大概率误差范围或降级，不得猜填。

战术交叉验证应尽量保留：对低位防守的边路一对一、肋部进入、禁区触球、传中与二点球数据；弱势方由守转攻的推进、快速反击射门、定位球和前场接应点数据。近期战绩必须带对手强度、主客场、赛事性质与时间衰减；“连胜必终止”“状态周期到了”等字段禁止录入。

半全场建模需另外保存：上半场与下半场分别的进球、失球、xG/xGA、射门和红牌；半场比分状态；领先、平局、落后状态下的第二阶段攻防强度；教练换人时间与角色、阵型变化、比赛强度、样本场次、对手校正和赛前截止时间。标签必须注明 `perspective=home_team`；若来源按热门方或所选球队描述，必须先映射回主队视角并保存原始标签。

进球时间数据需保存每个区间的进球、失球、实际暴露分钟、当时比分状态、红牌人数、主客场、对手强度、赛事、赛季和补时归属规则；优先估计按分钟暴露归一化的分时段风险率，而不是直接使用“近10场某时段进球占比”。历史交锋还必须保存当时教练、核心阵容和距今时间；阵容或教练发生明显更替时降权，不得录入“关系好坏”“相生相克指数”等不可审计字段。

任何联赛/球队半全场概率表还必须提供：数据源、赛事、赛季、起止日期、总样本量、每个分组样本量、主客筛选、强队定义、赔率或排名筛选是否参与分组、升降级处理、延期/中断/加时排除规则、9项计数与概率和、生成代码/版本和样本外时间段。只给“近3场半场胜率”“近5场全场负率”或无分母百分比时，不得据此生成半全场联合概率。

xG输入必须包括：供应商、模型/数据版本、抓取时间、比赛级xGF/xGA、主客场拆分、样本场次、时间衰减、是否含点球以及是否为赛前截止数据。标准xG、post-shot xG/PSxG和xGOT必须使用不同字段。若跨供应商不可避免，先分别建模和校准，不得把数值直接平均。

伤停输入至少记录球员、位置/角色、预计缺阵分钟、预计替代者、替补质量、同位置其他缺阵、阵型变化、消息来源和确认时间。固定百分比扣分不得作为原始输入。

模型验证记录必须逐注保存：赛前概率三项、概率版本、实际玩法与盘口、十进制成交赔率、收盘赔率、金额、完整亚洲结算结果、盈亏和锁单时间。周度校准不得只比较平均概率与命中率；应按概率分箱并累计Brier score、log loss、校准误差、CLV、ROI、最大回撤和样本量。

机器学习实验还必须保存：模型与代码版本、特征清单、每个特征的最晚可用时间、训练/验证/校准/最终测试起止时间、比赛唯一键、去重规则、超参数选择区间、概率校准方法、基线模型和随机种子。交易所字段需保存供应商、原始back/lay语义、成交/挂单状态、时间戳、深度、佣金和主动方向是否推断；任何使用最终胜方、最终比分或赛后汇总生成的字段标记为 `target_leakage=true` 并禁止训练。

收益汇总需保存期初净值、期末净值、回测自然日、持有期收益、年化公式、逐日或逐注收益频率、最大回撤算法及Kelly注额基准。Sharpe需另外保存无风险利率、收益频率、年化因子、无投注日处理和费用；“红单率提升35%”必须注明是提高35个百分点还是相对提升35%，并同时给出基线、样本量和置信区间。

## F. 投注价格
用户实际可买价格优先于公开网页价格。必须记录来源和时间。

价格审核顺序：
1. `fetched_odds`：系统抓取价，用于首份报告的初算EV；
2. `user_channel_odds`：用户反馈的实际渠道价，用于最终候选复算；
3. `locked_odds`：仅在用户明确锁单后冻结。

若渠道盘口线与抓取盘口不同，必须同时提供玩法和盘口线，例如“主队-1.5 @1.88”，不得只提供裸赔率。

## G. 用户渠道滚球实时事件

滚球桥接原始事件遵循 `schemas/live_odds_event.schema.json`，至少包含：

```json
{
  "schema_version": "1.0",
  "captured_at": "",
  "source_type": "worker_message/shared_worker_message/websocket_message",
  "page_url": "",
  "session_id": "",
  "sequence": 0,
  "transport_meta": {},
  "payload": {}
}
```

本地服务同时按 `schemas/live_odds_normalized_event.schema.json` 写出标准化记录。`odds_quote` 已包含 `match_id`、`market_code`、`market_name`、`child_market_code`、`market_id`、`handicap_line`、`selection_code`、`selection_name`、`market_status`、`selection_status`、`raw_odds`、`inferred_decimal_odds`、`source_timestamp_ms`；`match_clock` 包含比赛ID、时钟和阶段。实时读取入口为 `GET http://127.0.0.1:8765/v1/latest?match_id=<比赛ID>`，默认仅返回开放且赔率有效的最新报价，并提供 `quote_age_ms`。

API初始快照与后续WebSocket更新均已支持中文玩法名/选项名映射。原始十万倍赔率与同一选项展示价换算一致时，核验依据记为 `direct_display_price_crosscheck`；同一比赛的相同 `ov` 字段已由其他选项直接交叉核验时，没有单独展示价的波胆等固定赔率可继承 `same_match_ov_field_peer_crosscheck`。两种依据均需随报价保存；完全没有核验依据的报价仍只能进入影子审计，禁止用于EV复算。

映射为模型可用报价前，必须进一步取得：

```json
{
  "match_id": "",
  "home": "",
  "away": "",
  "match_clock": "",
  "score_home": 0,
  "score_away": 0,
  "red_cards_home": 0,
  "red_cards_away": 0,
  "market": "AH/OU/1X2/team_total/other",
  "line": "",
  "selection": "",
  "odds_format": "decimal/hong_kong/malay/indonesian",
  "raw_odds": null,
  "normalized_decimal_odds": null,
  "market_status": "open/suspended/closed/unknown",
  "source_timestamp": "",
  "received_timestamp": "",
  "quote_age_ms": null
}
```

硬规则：

- 未确认赔率格式时不得计算EV；
- 比分、红牌、分钟、盘口线或销售状态缺失时，不得把报价视为可执行；
- 页面时间与本地接收时间必须同时保存，报价过期阈值须经实测后确定；
- 同一盘口换线时建立新合约，不得仅把赔率数字覆盖到旧盘口；
- 原始事件只进入影子分析，`execution_rules.in_play_betting=false` 时不得生成赛中下注指令；
- 捕获事件绝不等于锁单，仍只有用户明确说“锁单/已下单”才允许更新状态。

## H. 实时/用户渠道EV复算请求（v0.8.0）

请求遵循 `schemas/live_ev_reprice.schema.json`，入口为：

```powershell
python scripts\live_ev_reprice.py --request examples\live_ev_reprice_request.json
```

硬规则：

- 比赛ID、玩法、盘口线和选项必须精确匹配；`2.5/3`与`2.75`只作为同一数值盘口的等价写法，不进行模糊近似；
- 自动桥接价必须处于开放状态、`odds_scale_verified=true` 且不超过请求中的 `max_quote_age_ms`；
- 用户渠道手工价必须明确声明 `odds_format=decimal`；盘口线或选项变化时返回 `requires_probability_recompute`，不能沿用旧事件概率；
- 只有校准概率点估计和保守概率边界同时存在时，才允许通过保守EV执行线成为“候选”；缺少保守边界只展示影子诊断；
- 输出同时给出点估计EV、保守EV和最低可接受十进制赔率。报价瞬时变化但合约不变时，可直接用最低可接受赔率作价格闸门；换线必须重算概率；
- 当前仅支持无走盘二项事件或三项市场单一选项。亚洲整数/四分之一盘的走、赢半、输半结算必须使用完整结算分布，不能调用该简化入口；
- 所有结果固定 `execution_authorized=false`、`lock_state_changed=false`、`bankroll_state_changed=false`；通过价格闸门也只标记“候选”。

悬浮窗每秒向本地 `POST /v1/reprice` 发送同一结构的请求，但不落盘每一帧，避免产生无意义的高频文件。`staking` 仅使用项目模型余额、当前暴露、5%单场上限和2—3元固定小额分层，不读取渠道账户余额；Kelly字段仍只作诊断。

完整分析完成后，投注候选必须额外提供 `live_ev_profile`，报告生成器才会把数值自动赋给对应比赛的悬浮窗：

```json
{
  "match": {"live_match_id": "5503037"},
  "betting": {
    "candidates": [{
      "live_ev_profile": {
        "active": true,
        "overlay_primary": true,
        "contract": {
          "match_id": "5503037",
          "market_code": "2",
          "market_name": "全场大小",
          "child_market_code": "2",
          "market_id": "",
          "handicap_line": "2.5",
          "selection_code": "Over",
          "selection_name": "大",
          "contract_type": "binary_no_push"
        },
        "probability": {
          "point": 0.56,
          "conservative": 0.53,
          "confirmed_model_output": true,
          "source": "模型与校准版本",
          "calibration_status": "样本外校准状态"
        },
        "price": {"max_quote_age_ms": 15000},
        "execution": {"minimum_conservative_ev": 0.02}
      }
    }]
  }
}
```

发布文件遵循 `schemas/live_ev_profile.schema.json`：历史留存在 `data/live_ev_profiles/history/YYYYMMDD_HHMMSS/`，当前值写入 `data/live_ev_profiles/current/<match_id>.json`。同一比赛有多个候选时，必须且只能有一个 `overlay_primary=true`；否则发布“非活动配置”并清空金额。若报告有 `match.live_match_id` 但没有完整候选，也会发布非活动配置，防止悬浮窗沿用旧概率。任何缺失、未确认或不匹配的字段都不得推断补齐。

## H. 赛后严格结算合约（schema_version 1.1）

新生成的赛后复盘必须提供唯一主维度合约；不得只提交“方向命中”文字：

```json
{
  "schema_version": "1.1",
  "audit": {
    "primary_contract": {
      "explicit_unique": true,
      "market_type": "1x2/asian_handicap/total/btts/correct_score/team_total/total_goals/half_full",
      "selection": "home/draw/away/over/under/yes/no/具体比分或区间",
      "line": 2.25,
      "scope": "regulation_90m_plus_stoppage"
    }
  }
}
```

硬规则：

- `explicit_unique=false` 或缺少唯一合约时，主维度为“不可计入”；
- 亚洲盘严格输出 `全赢/半赢/走水/半输/全输`；
- 半全场必须同时提供半场与90分钟赛果，否则为“不可核验”；
- 玩法、选项、盘口线、结算时段任一不一致，不得沿用其他市场结果；
- 辅助玩法另建逐项结算数组，只用于分市场复盘，不进入唯一主维度命中率；
- 未锁单只记录模型结算与价格纪律，不写真实投入、回收或盈亏。


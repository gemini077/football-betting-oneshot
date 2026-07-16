# 自动数据抓取接入

## 统一入口

```powershell
python scripts\fetch_football_data.py --date YYYY-MM-DD [--match 球队或赛事] [--deep] [--no-cache] [--nowscore-id 比赛ID] [--polymarket-home 英文主队 --polymarket-away 英文客队]
```

`--date` 按竞彩业务日期解释，不等同于自然日开球日期。晚间销售周期内跨午夜开球的比赛仍归入前一业务日；输出同时保留 `business_date` 和 `kickoff_local`。

- 不加 `--deep`：抓取中国竞彩主源和500比赛列表、可见官方赔率、`shuju_id`。
- 加 `--deep`：对筛选后的比赛继续抓取500六个深层页，并从 Nowscore 三合一页面补充标准盘、让球盘和大小球的初盘/即时盘。
- `--shuju-id 1234567`：显式指定比赛ID；支持逗号分隔多个ID。
- `--sid 19476 --round A`：可选调用500联赛API核验赛程和比赛ID。
- `--no-cache`：强制刷新；默认缓存有效期为1小时。
- Polymarket默认只尝试公开赛事匹配；中文队名无法可靠匹配时，用 `--polymarket-home`、`--polymarket-away` 提供英文别名，并可用 `--polymarket-kickoff` 限定ISO开球时间。
- `--skip-polymarket`：不抓Polymarket公开只读市场证据。
- `--nowscore-id 2912840`：必要时显式指定 Nowscore 比赛ID；仍会核验主队、客队和开赛时间，不一致时拒绝赋值。
- `--skip-nowscore`：不抓 Nowscore 三合一盘口。

示例：

```powershell
python scripts\fetch_football_data.py --date 2026-07-15 --match 法国 --deep --no-cache
```

## 数据源优先级

1. 用户实际可买价格、截图及其时间戳：执行价格第一真源。
2. `sporttery.cn`：竞彩SPF/RQSPF主源。
3. `trade.500.com` 和500深层页中的竞彩官方行：竞彩后备源及比赛ID发现。
4. 500欧赔、亚盘、大小球和交易页：分析层市场数据。
5. Nowscore 三合一页面：补充多公司标准盘、让球盘和大小球；必须通过主客队同向与开赛时间校验，保留来源公司ID并映射项目统一公司ID。
6. 球队、赛事官方消息与可靠统计源：确认首发、伤停、天气、场地和高级数据的核验源。
7. Polymarket公开市场：只作为市场共识、分歧、流动性和价格轨迹证据；不是用户执行赔率，不连接账户，不直接进入概率、EV或仓位。

抓取脚本无法替代用户实际成交价格，也不能把预计阵容当成确认首发。无法核到的字段必须标记“未核到”。

## 目录职责

- `skills/500com-football-scraper/`：抓取规则与解析规范。
- `scripts/`：可执行抓取脚本。
- `data/source_cache/`：可覆盖的原始页和解析缓存。
- `data/fetch_runs/YYYYMMDD_HHMMSS/`：每次抓取的不可变快照和清单。
- `data/postmatch_reviews/`：赛后复盘工作簿，与抓取数据隔离。

所有批次和输出文件使用日期时间命名，不使用 `v13`、`v14` 等递增文件版本号。

## 状态与锁单隔离

抓取结果一律是分析输入。抓取脚本不读取或修改账户余额、未结算注单和锁单字段。只有用户明确说“锁单”或“已下单”后，才允许按投注SOP更新运行状态和工作簿。

## 已知限制

- 500页面结构变化时可能出现局部解析为空，必须检查抓取清单和各页计数。
- 500赛前基本面页在赛后可能清空部分历史内容，不适合作为完整回测真源。
- xG、射门、射正、Big Chances、PSxG等高级指标需要另外联网核验。
- 最终首发、临场伤停、天气和场地必须在对应时间窗重新核验。

## 用户渠道滚球赔率桥接

用户已登录页面中的实时赔率不走公开赛前抓取入口，改用 `11_LIVE_ODDS_BRIDGE_滚球只读桥接.md` 定义的本地桥接：

- Chrome扩展只捕获目标站点的 Worker/WebSocket 比赛消息，不读取页面DOM；
- 本地服务固定监听 `127.0.0.1:8765`，二次脱敏、校验、去重并落盘；
- 每次运行写入 `data/live_odds_bridge/captures/YYYYMMDD_HHMMSS/`；
- `GET http://127.0.0.1:8765/v1/latest?match_id=<比赛ID>` 提供当前批次的最新开放报价与新鲜度，供模型轮询；
- 捕获价格必须记录页面、采集时间、接收时间、比赛状态、玩法、盘口线、赔率格式和销售状态；字段映射不完整时只能作为数据审计输入；
- `read_only_shadow` 模式绝不提交订单、改变余额或更新锁单；正式赛中执行仍为关闭状态。

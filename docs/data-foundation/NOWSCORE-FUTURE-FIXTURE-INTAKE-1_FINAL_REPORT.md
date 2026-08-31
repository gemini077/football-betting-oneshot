# NOWSCORE-FUTURE-FIXTURE-INTAKE-1 — Future Fixture Intake

状态：`READY_FOR_ACCEPTANCE`

## 1. 范围

本轮只处理竞彩 schedule intake 时的 Nowscore future surface。保留
`bf1.js` 为 live schedule，未修改 500/Sporttery canonical schedule、现有
exact resolver、provider registry、Champion、frozen history 或三个 identity
gap。

## 2. Bounded live probe

探针日期：`2026-08-31`，时区：`Asia/Shanghai`。

| surface | raw rows | accepted rows | 观察 |
| --- | ---: | ---: | --- |
| `bf1.js` | 367 | 367 | 含 match ID、home/away team ID、队名、完整日期时间；当前响应覆盖 `2026-08-31` 与 `2026-09-01` |
| `sc1.js` | 204 | 71 (`expected_date=2026-09-01`) | 含 match ID、home/away team ID、队名、`HH:MM`；另有 133 行 `09-02` 被严格拒绝 |

`sc1.js` 使用官方页面同样的数字毫秒 cache-buster；探针确认当前 URL、字段
形态和跨日行为。`MM-DD` 行没有 expected date 时不解析，年份只来自调用方
传入的 expected date。探针过程中观察到上游偶发连接关闭，代码保留
`bf1` fallback 和 future surface error provenance。

## 3. 实现

- `fetch_schedule_bundle()` 从竞彩 payload 的真实 `matchDate` 收集日期。
- 以 `Asia/Shanghai` 当前日期计算 offset，只请求需要的 `sc1`–`sc7`。
- `bf1` 与成功的 future rows 按 `nowscore_id` union 去重，保留 bf1 首行。
- source date 与 expected date 不一致时丢弃该行；没有猜测年份或比赛。
- future fetch 失败返回 `DEGRADED`，但仍返回 bf1 rows，并在 `future_surface`
  和顶层 `errors` 保留错误。
- 绑定仍由原 `team verification / kickoff verification / confidence gate /
  provider_match_registry` 路径完成。

## 4. 2026-08-31 bounded replay

回放读取现有 `data/schedule_updates/20260831_060247/` 的 12 场 cohort，
只读调用 `bf1 + required sc1` union，不调用 `prebind_match`，因此没有写入
production registry。

- unique schedule rows：`438`
- duplicate `nowscore_id`：`0`
- exact-compatible rows：`8/12`
- 与已知同一 Nowscore ID：`8/8`
- kickoff difference：`0`（8/8）
- wrong binding：`0`
- 用户指定的三个 identity gap 未修改：国际图尔库 vs 库奥皮奥、赫尔辛基火花 vs TPS图尔库、奥萨苏纳 vs 赫塔费

本次回放发生在 `sc1` 早场行已经随 rolling feed 变化之后，因此当前 sc1
本身不再保存这批早场的 8 个 row；同一 ID 结论来自当前 bf1 union 与已持久化
cohort。focused tests 另外覆盖了“bf1 没有目标行、sc1 future row 提前命中”
的 future-only 路径，作为早上 intake 的可重复证据。

## 5. 验证与边界

- focused：`python -m pytest -q tests/test_nowscore_markets.py tests/test_base_prediction_jobs.py` → `33 passed`
- syntax：`python -m py_compile scripts/nowscore_markets.py scripts/daily_schedule_workspace.py tests/test_nowscore_markets.py` → 通过
- full suite：被既有 `tests/test_live_ev_profile.py` 导入错误阻断：`build_public_site` 当前没有 `PUBLIC_DATA_DIRS`；本轮未触碰该文件
- production mutation：回放不写 registry、frozen、ledger 或 Champion；意外测试写入的 registry timestamp 已恢复，最终 diff 不含 durable production data

下一步只做独立验收；本 milestone 停在 `READY_FOR_ACCEPTANCE`。

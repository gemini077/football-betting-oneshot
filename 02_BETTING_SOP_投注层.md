# Betting Decision Layer — DOWNSTREAM / GATED

最后更新：2026-09-04

本文件原为 Football Betting OneShot 早期“投注层标准作业程序”。当前产品路线已经演进，因此旧版固定本金、修复期、分层仓位和逐场投注执行规则**不再是当前项目主线或默认产品行为**。

历史 SOP 可从 Git history 完整恢复。

---

## 当前定位

Football Betting OneShot 当前首先是：

> 足球信息 + 市场信息 + 赛前概率 + 可审计验证的决策支持产品。

Betting Decision Layer 只属于 downstream capability。

只有同时满足：

`Prediction Trust + Calibration + Executable Market Price + Data Rights + Compliance`

之后，EV、value、stake sizing、串关相关性、portfolio 等才允许重新进入主要 Roadmap。

因此当前：

- 不要求每场给投注建议；
- 不要求每场给唯一执行方向；
- 不要求维持旧“100元本金/修复期”账户逻辑；
- 不因存在概率输出就自动生成 stake；
- 不把所谓“保本层”解释为本金保证；
- 不做自动下注、代购、出票、充值或交易执行。

---

## 未来恢复本层时仍必须遵守的 Durable Rules

1. **方向与价格分离**：预测方向正确不等于存在可执行 value。
2. **概率先可信**：未经 prospective 验证/校准的概率不能支持正式 EV 或仓位。
3. **使用真实同时间价格**：不得用联赛平均赔率、整场返还率或错误方向价格计算 EV。
4. **禁止追损**：不使用 Martingale / 倍投 / “跟到底”等机制。
5. **风险透明**：任何资金分层都只是风险角色，不表示本金或收益保证。
6. **不可篡改**：若未来记录实际/模拟执行，赛前方向、价格、时间与金额一经锁定不得赛后改写。
7. **真实账户与研究/模拟严格隔离**。
8. **中国市场边界独立过 Gate**：分析服务不得滑向彩票交易、代购、出票、充值或自动下注。

---

## 当前 authority

- 产品北极星：`14_PRODUCT_BLUEPRINT_产品全貌.md`
- 当前路线：`16_ROADMAP_项目路线图.md`
- 当前工作：`17_NEXT_WORK_后续工作.md`
- 当前验收：`18_ACCEPTANCE_验收标准.md`
- Durable Decisions：`19_DECISIONS_关键决策.md`
- 长期 Canonical：`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`

**禁止旧 Betting SOP 反向覆盖当前 Roadmap。**

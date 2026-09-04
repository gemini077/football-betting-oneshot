# DEPRECATED — 不再作为当前项目指令

最后更新：2026-09-04

本文件是 Football Betting OneShot 早期“逐场投注执行”阶段留下的历史项目指令。

**禁止把本文件作为当前项目 authority、Roadmap、产品定义或执行契约。**

早期版本中的以下要求已经失效，不能覆盖当前产品真相：

- “每场必须输出唯一首推比分”；
- “每场必须进入投注价值/最终投注层”；
- 固定本金/修复期/仓位作为项目主线；
- 把产品主要定义为投注执行系统；
- 因旧模型版本或旧任务口径限制当前 Roadmap。

历史正文仍可从 Git history 完整恢复，因此不在当前文件重复保存。

## 当前 authority

长期 Canonical Source of Truth：

`gemini077/Memory-Hub / PROJECTS/Football-Betting-OneShot/CANONICAL.md`

主仓库当前控制面：

1. `AGENTS.md` — repo 内 agent 边界；
2. `14_PRODUCT_BLUEPRINT_产品全貌.md` — 长期产品北极星；
3. `15_PROJECT_STATUS_项目状态.md` — 当前状态投影；
4. `16_ROADMAP_项目路线图.md` — 当前产品路线；
5. `17_NEXT_WORK_后续工作.md` — 当前工作；
6. `18_ACCEPTANCE_验收标准.md` — durable gates；
7. `19_DECISIONS_关键决策.md` — 当前 durable decisions / anti-rollback；
8. GitHub Issue — 每个 bounded 执行任务的唯一具体契约。

若旧文档、旧聊天、旧 milestone 与最新可复现事实或 Canonical 冲突，执行：

`latest facts → Canonical Evolution Gate → current best route`

而不是恢复旧路线。

## 当前产品边界

Football Betting OneShot 是面向中国用户的足球信息 + 市场信息 + 赛前概率 + 可审计验证的决策支持产品。

核心输出包括：`1X2 / Exact Score / O-U / BTTS`。

- Exact Score 是一级能力，但允许以 score scenarios / distribution 表达不确定性；
- 数据不足或预测不可信时允许 degraded / abstain，不强行给“唯一答案”；
- Betting Decision Layer 是 downstream，并非当前所有比赛的强制输出；
- 产品不是彩票交易、代购、出票、充值、自动下注或官方彩票服务。

**任何 agent 若仍需要早期投注执行规则，必须明确按 Git history 作为 historical research 读取，不能把它重新提升为 current authority。**

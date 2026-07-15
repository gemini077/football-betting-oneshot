# DeepSeek 自动分析

当前版本：`v0.13.2`

## 用户操作

1. 在主页未分析赛事中点击“分析这场”。
2. 页面会打开一个已预填比赛编号、业务日和对阵的 GitHub Issue。
3. 仓库所有者提交 Issue 后，GitHub Actions 自动抓取该场数据、调用 DeepSeek、生成报告、运行测试并更新 GitHub Pages。

静态网页不能安全地保存 API Key，因此保留一次“提交 Issue”的确认动作。公开访客创建的 Issue 不会触发分析，只有仓库所有者提交的 `[自动分析]` Issue 或手动运行工作流才会调用 API。

## GitHub 配置

- Repository Secret：`DEEPSEEK_API_KEY`
- 工作流：`.github/workflows/analyze-selected.yml`
- 默认模型：`deepseek-v4-pro`

## 安全边界

- DeepSeek 只作为结构化证据的辅助综合层，缺失数据必须披露，不得补造。
- 自动输出不会建立真实注单、不会锁单、不会修改账户余额。
- 只有用户明确说“锁单/已下单”，真实投注层状态才允许变化。
- API 调用失败、输出不是合法 JSON 或模型校验失败时，工作流失败并保留上一版网页，不发布半成品。

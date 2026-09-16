# Implementation acceptance status

> Historical full-milestone report for source d99e5795. The 2026-09-06 user-requested editable AI service settings change supersedes the source freeze. This report does not certify that newer source. See `notes/ai-service-settings-20260906.md` for the new implementation and focused validation; real Provider gates remain unfulfilled.

Generated from actual execution evidence by `harness/acceptance.py report`.

Source tree: `d99e5795269d6638306f897d964ba3e9d048af712796ec2390850a0f2041b7a6`. Git: `3c74d769b785644bee39e8224bb3197bbeac0646`; dirty: True.

Design/prototype checks and file presence do not prove product completion. A stale result never completes the current tree.

AT: {'passed': 126, 'blocked': 4}. Gates: {'passed': 21, 'blocked': 2, 'not_run': 1}. Stale records: 138.

| Gate | Status | Missing proof kinds |
|---|---|---|
| M0-G01 范围与无身份契约 | passed | - |
| M0-G02 PDF库与IR基础 | passed | - |
| M0-G03 完整静态出版 | passed | - |
| M0-G04 真实产品闭环 | passed | - |
| M0-G05 无身份边界及PDF内容安全 | passed | - |
| M0-G06 Compose依赖与恢复 | passed | - |
| M0-G07 部署和恢复 | passed | - |
| M1-G01 安全本地输入 | passed | - |
| M1-G02 真实源结构完整 | passed | - |
| M1-G03 真实Provider与授权 | blocked | live_provider |
| M1-G04 对齐和缓存 | passed | - |
| M1-G05 任务恢复与未知状态 | passed | - |
| M1-G06 预算和操作竞态 | passed | - |
| M1-G07 质量与真实发布 | passed | - |
| M1-G08 任务中心与库 | passed | - |
| M1-G09 隐私、删除与恢复 | passed | - |
| M2-G01 来源与编辑完整性 | passed | - |
| M2-G02 术语与局部重译 | passed | - |
| M2-G03 质量报告有效性 | passed | - |
| M2-G04 多语言版本 | not_run | live_provider |
| M2-G05 冲突、历史与回滚 | passed | - |
| M2-G06 零模型重建和精确导出 | passed | - |
| M2-G07 检索及生命周期 | passed | - |
| M2-G08 累计产品交付 | blocked | browser, live_provider |

The table above answers whether the current source has all required registered proof. `not_run` does not mean that the feature is absent: source changes invalidate earlier certificates, and partial behavior checks cannot complete a literal scenario.

Historical scoped observations: 130/130 scenarios mapped; 119 have at least one agent's literal-coverage assertion for its recorded version. These assertions do not change the gate table.

Read the [scenario observation map](evidence/observed-scenario-map.json) for commands, evidence paths, exact scope and missing behavior. Real Provider execution remains unauthorized; authored M0 fixtures and simulated Provider responses do not replace real parsed-paper or translation review.

Details and current certificates: [acceptance-report.json](evidence/acceptance-report.json).

File-based handoff: [harness/memory/current.md](harness/memory/current.md).

Completion claim allowed: false.

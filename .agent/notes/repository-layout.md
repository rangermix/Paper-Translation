# 项目目录迁移交接 · 2026-09-07

项目已提升至 `C:/workspaces-local/Paper-Translation`，原 `bilingual-library-personal-pdf-v3/` 目录已移除。应用、测试、产品文档、fixtures、部署配置和工具保留原相对层级。

## 资料位置

- `.agent/harness/`：可复用 agent 工具。
- `.agent/memory/`、`.agent/notes/`：工作记忆和交接记录。
- `.agent/tmp/`：中间产物、历史证据、报告、日志、截图、验证缓存和旧 Python 环境。
- `.agent/local-data/`：持久运行资料和 WSL 验证环境磁盘。

详细映射见 [relocation.json](../relocation.json)，使用说明见 [README.md](../README.md)。历史记录中的旧路径保留，由迁移映射辅助查找。

根 `.gitignore` 忽略临时产物、持久私有数据、依赖、构建缓存和密钥；harness、记忆、笔记及产品资源保持可纳入版本控制。`.dockerignore` 排除整个 `.agent/`，保留产品离线 HTML。未暂存或提交文件。

## 实现与验证

Python 和浏览器辅助工具已修正根目录定位、历史输入映射及新输出位置；新输出集中到 `.agent/tmp/`。重建了根 `.venv`，pytest 和 mypy 缓存也改到 `.agent/tmp/cache/`。文档生成、Compose 挂载和静态检查路径已更新。

- Python 定向测试 48 项通过，165 个文件语法检查及 6 个 CLI 检查通过。
- 新 `.venv` 激活和 pytest 启动器正常，收集到 730 个用例；此次未执行全部用例。
- 前端 13 项单测和构建通过；96 个浏览器用例仅完成收集。
- 设计包检查 51 项通过；Git 忽略规则 27 个正反例通过。
- 独立 agent 完成迁移审查，30 项检查通过，无遗留迁移问题。见 [独立审查](repository-layout-independent-review.md)。

本次未启动应用容器或重跑完整功能验收，未调用真实模型。历史验收结果保留原适用范围。初始失败的移动尝试及检查日志保存在 `.agent/tmp/repository-layout/`。

## WSL 磁盘

`BiblioCleanD99` 是此前用于独立宿主验收的 WSL 环境，其 `ext4.vhdx` 存放该 Linux 环境的数据。它已迁到 `.agent/local-data/wsl-hosts/BiblioCleanD99/`。

用户明确允许停止 Ubuntu 并迁移后，已停止 Ubuntu、关闭 WSL、使用 `wsl --manage BiblioCleanD99 --move` 完成迁移并重新启动 Ubuntu。最终检查确认新登记路径有效、旧目录不存在、Ubuntu 运行中、BiblioCleanD99 停止。Ubuntu 重启的 shell 保留运行。

用户随后明确表示不需要逐字节认证；不再进行此类检查，也不将其作为完成条件。迁移以官方命令成功、路径和登记正确、Ubuntu 恢复为完成依据。

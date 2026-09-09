# 新 OS 宿主验收准备 · 2026-09-06

这是最终 d99 冻结后的额外环境验收准备；未修改生产、tests、harness、fixture 或原最终报告。原 124 passed / 6 blocked 记录仍原样保留。新的可行路径由 root 负责：导入独立 Linux rootfs，独立 Docker daemon/socket/data-root，明确共享物理机器与 WSL2 内核。不能把旧 daemon 新卷充当新宿主，也不能只凭 Docker-only PATH 推断操作系统隔离。

本 agent 准备 `evidence/new-host-bundle/stable-d99-20260906-with-cold-parse.tar`，280576 bytes，SHA256 `5b62ae782d44b7ed6e3c9958b631489883a2837009008b986ea436631b2bbb91`。更早基础包 `stable-d99-20260906.tar` 保留，SHA `bc1ff767fd6de3d4caf27150f88fb59d8b61233851c35f45e8bcd32a0b00b606`。新宿主不安装 Python/Node/qpdf/PostgreSQL；Shell 只调 Docker/Compose，Python 和数据库 CLI 均运行于精确镜像内。

原 Desktop backup：`schema5-upgrade-a2dec645_backups` 中 `backup_68130fac70464ae796a2ef80d9f1c953`。原卷只读挂载，当前 app 镜像 `network none` 内完整 verify → copy → verify，保留 11 内容文件、数据库 dump、显式模拟 unknown 80000 micro、尚未执行的本地索引任务。它不是实际供应商收费，也不是已发布 M1 版本的备份。`expected/browser-restored.json` 给 web 原 PDF、旧 Artifact、完整文件 SHA 和任务 ID；原 artifact manifest 不对 HTTP 开放，由 backend helper 核 bytes，browser 应核其 404。

实际预传输检查：Shell `sh -n`、Linux source env、`sha256sum -c`、app 90 文件/parser 25 文件检查均通过。修正了宿主生成 env 的 CRLF；这些只是准备检查，不是新宿主通过证据。

阶段：doctor → m0-start（真正空库）→ web initial → m0-populate（native PDF upload、seed 2+0、4 导出、app recreate）→ 新增 `new_host_cold_parse.py`（真实离线 Docling 四段）→ web legacy → m0-backup → m0-restore（新 PG/data 卷）→ web restored_m0 → m0-stop → migration-start（原 Desktop backup 转入新 daemon）→ held 原任务/账目核对 → migration-resume（仅 maintenance-off）→ web restored → migration-stop。Named volumes 均保留。

HTTP bridge 为 Windows 浏览器入口，后端/provider networks internal，parser network none；root 仍须实际证明新宿主 namespace/路由阻断外网与模型仓库。旧 helper 的 “all internal” scope 文本不能代替这项检查。IR 已独立读审备份与未知账目链，指出的两项边界正是 HTTP 出口和 actual Docling，均已提前加入新验收计划。

执行仍等待 root 的独立 daemon 与镜像传输完成；这里没有宣称 M0-AT18A/M1-AT25A 已通过。

> 进行中更新：新独立 WSL Docker-only 宿主已创建并实际冷启动，空库浏览器已通过；完整离线/恢复验收正在由三个 agents 执行。下文的旧“新宿主不可用”和124/6是本轮新宿主执行前快照；请先读 `notes/new-host-progress-d99-20260906.md`，完整新结果入库后再更新计数。

# 当前实现交接 · 2026-09-06

本地实现与可执行验收已完成；完整 M0/M1/M2 退出门尚未全部通过，不能宣称已完成认证或批准发行。

- 冻结源码：`d99e5795269d6638306f897d964ba3e9d048af712796ec2390850a0f2041b7a6`；候选镜像标签：`stable-20260906-050731`。
- 130 个场景中 124 passed、6 blocked；24 个退出门中 18 passed、5 blocked、1 not_run（M2-G04 缺真实 Provider 证据）。M2-G08 累计完整流程的 browser/live_provider 证明也随外部条件保留未完成。
- 当前完整 pytest：451 passed，0 failed/error/skipped，434.344s；前端交互合同：29 passed，0 skipped/flaky/unexpected。
- 20 个本地通过的 mixed 场景各有独立子 agent 审查；执行者、审查者、命令、输出、文件哈希与失败记录均已留存。其余 mixed 场景由外部条件阻塞，不伪造人工通过。
- 已真实执行当前镜像的四组 PDF 解析、原文校对、完整浏览器流程、预算/并发/未知付费结果、发布中止、schema5→10、3/10断点恢复、离线导出、损坏文件与备份拒绝、删除与恢复流程。
- 两处末轮 UI 问题（legacy定位限制提示、语义源文/译文摘录）均在冻结前修复并通过新镜像原失败数据复验。

## 可信入口

- `IMPLEMENTATION_STATUS.md` 与 `evidence/acceptance-report.json`：当前状态，只以当前源码的实际完整证据判定。
- `evidence/release/stable-d99-final-local-audit.json`：最终本地证据审计。
- `evidence/release/stable-20260906-050731/request.json`：不可变 app/parser/db 镜像和实际容器源码核对。
- `notes/stable-freeze-20260906.md`：执行索引；各 agent 的 notes 和版本化 map 记录详细边界。
- `evidence/release/stable-d99e5795-security-summary-final.json`：实际漏洞扫描；OS Critical/High 与 native FFmpeg OpenSSL1.1.1k 残留已披露，未批准 release。

## 未完成的外部前置条件

1. 真实 OpenAI 验收需要固定 model/profile/价格、后端密钥文件绝对路径、全流程共用测试预算，以及受控 EN/ZH 两份 PDF 的8个文本块及相邻上下文外发授权。先前请求未获回复；不得读取密钥或执行真实调用。AGENTS.md 第6条继续适用。
2. 需要可用的独立干净/新 Docker-only 宿主机；同一主机的新 Compose 项目/新卷只能证明该局部恢复流程，不能替代新宿主机验收。此前 Hyper-V 探测被拒绝，无 QEMU/VirtualBox；既有 WSL/8080 未动。

阻塞场景：M0-AT18A，M1-AT08A/08B/25A/26A，M2-AT21A。不得用 FakeProvider、历史镜像、模型自评分或新卷冒充这些证据。

## 恢复工作规则

所有生产代码、测试、harness 与 fixtures 保持冻结。只有获得上述真实外部条件后，才执行对应已准备的验收，不重做已通过的本地矩阵。若确需修改 tracked 文件，先记录原因并重新建立对应当前源码证据；不得给旧记录换标签。所有人工/视觉/来源/语义复核继续分配独立 agents，使用项目文件传递上下文。

此批临时验收实例均已关闭，命名恢复卷保留；原 localhost8080 与测试 DB55439 保持原状态。历史交接保存在 `notes/history-before-final-stable-d99.md`，其中旧“当前”或“待修”文字均为历史。

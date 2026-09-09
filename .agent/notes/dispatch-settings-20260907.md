# 设置页控制外部 API 请求 · 2026-09-07

用户要求将“实例已暂停外部请求”对应的设置放进设置页，不使用 env。实际状态原本已在 PostgreSQL Settings.dispatch_disabled，但页面没有入口；Compose 的 DISPATCH_DISABLED 环境项没有被运行代码消费。

新增设置页 AI 服务区域的“外部 API 请求”面板，通过 GET/PATCH /api/v1/settings/dispatch 单独保存。默认/恢复仍暂停，重建保留数据库状态；删除 Compose 和 env 示例中的 DISPATCH_DISABLED。共享维护 CLI 的未知费用确认规则，风险确认写入 Attempt evidence，旧 unknown Permit/任务与在途记账保持。CAS 使用 Settings generation，幂等确认只记一次；自动超限暂停也递增 generation。Provider 配置/凭据不被开关修改。

证据目录：`.agent/tmp/dispatch-settings-20260907-8e8a0cbd`。

- 独立 PostgreSQL Compose（合成密码、tmpfs、55449）后端定向回归：72 passed，含新 API、双标签竞争、数据库初始化后的持久化、维护恢复、未知费用、在途结算、连接测试入队、旧迁移/成本控制。regression1.log/xml；green1.log 的 17 passed 与此重叠，不累加。既有 Starlette/httpx 两项弃用警告。
- 58 browser contracts passed：新面板 5 项，以及连接测试/AI 设置/原生协议/成本控制。browser2.log。browser1 的 3 项失败来自旧 fixture 未提供新 endpoint，补齐后全部通过；保留原失败截图与日志。桌面/手机截图人工检查，无溢出。
- 前端 16 unit passed；容器构建包含 tsc/vite 成功（docker-build.log）。最初 API 未实现的红测试保留 red.log/xml。
- 8080 app/worker 经 Compose 更新，同镜像 `sha256:229e22fc9b4f4918f2fde2c350c717bf69656ac97363f90fc6ffaf7101ab0609`，local 别名也更新；DB/parser 容器保持。health/ready 正常，四容器 healthy，app/worker 均无 DISPATCH_DISABLED 环境变量。
- production-before/after.json 对比公开 profile hash/config revision/credential revision/generation/key presence/dispatch flag 全部相同。当前 dispatch generation=8、paused=true、maintenance=false、unknown=0、inflight=0。没有读取真实 key，没有执行真实模型调用。
- live-ui.cjs 在真实 8080 页面验证桌面/390px 手机、勾选/取消草稿及刷新后仍暂停，阻止全部非 GET/HEAD 请求，实际写请求=0。live-ui.json 与 live-desktop/mobile.png。
- QA DB 容器/网络已删除，Vite 已停止，55449/5179 无监听；production 保持 ready。cleanup-verification.json。

代码未 commit；原有 M1/M2 真实 Provider/release 门结论不变。后续由用户在设置页开启外发，再独立执行连接测试或恢复已有任务。

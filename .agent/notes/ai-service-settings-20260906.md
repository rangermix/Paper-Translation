# AI服务设置实现交接 · 2026-09-06

用户新指令：`allow to setup ai service API endpoint, key, id, etc. 在设置里`。本次修改覆盖先前只读Provider设置和源码冻结约束。未提供真实key、预算或真实模型外发授权；仅用合成凭据和本地模拟服务验证，不把保存设置当作外发批准。

## 所有权

- acceptance_harness：后端版本化配置/secret文件、CAS与幂等、Settings API、配置测试。
- ir_publisher_parser：Responses / Chat Completions协议、endpoint/auth_mode、版本绑定派发、Provider测试。
- web_ui：设置表单、公开类型、确认目的地、前端契约测试。
- root：Compose卷权限/初始化、契约文档、集成与隔离运行环境、证据汇总。
- 实际人工/视觉验收由独立agent进行，不能由实现者自证。

## 已定合同

完整HTTP(S)请求endpoint；不自动补路径，拒绝userinfo/query/fragment，不跟随重定向。支持OpenAI兼容responses/chat_completions。用户模型ID原样保留，允许本地`:latest`；不自动选模型或回退供应商。Bearer为默认，免鉴权必须显式选择。

key仅输入时提交后端；GET不回显，不写浏览器持久存储、DB、日志、导出或标准备份。单独provider_config命名卷，app RW、worker RO、init初始化10001/0700，其他服务不挂载。完整不可变版本与secret绑定，原子切换当前指针。空key保留，clear明确，更换目的地/协议不能静默重绑旧key。清当前key不宣称撤销在途请求或历史secret版本。

允许保存未完成配置，但缺价格/限额时保持configured=false；不默认为免费。保存是本地操作，不主动连接模型服务。旧只读profile与worker-only secret保持fallback；app不能确认其key状态时返回unknown，不虚构缺失或存在。

## 验证与运行边界

旧localhost:8080四容器和BiblioCleanD99停止状态不动。新功能使用独立Compose project、空卷、合成key。原d99e5795源码、stable-20260906-050731镜像及126/130、21/24正式报告是历史证据；新增改动不得复贴旧认证标签。真实Provider缺口依旧存在。

## 已完成验证

- 完整后端：`python -m pytest -q --junitxml=evidence/ai-service-settings/backend-regression.xml`，专用PostgreSQL逐schema隔离；518 passed，0 failure/error/skip，421.01秒。两个既有TestClient依赖弃用警告保留，无升级依赖来掩盖警告。
- 前端：43 Playwright契约（14设置、24原UI、5实验语言/目的地）与13 Vitest通过，TypeScript/Vite构建通过。最后密钥缺失状态标签修复单独记录在作者证据内。
- 独立后端复核：IR agent发现A→B→幂等重放A的响应混合价格别名，作者真实复现后修复；独立2探针+44测试通过。见 `evidence/ai-service-settings/independent-backend-review.md`。
- 独立协议接线复核：acceptance agent执行30节点，通过；见 `independent-adapter-review.md`。
- 实际Compose：`harness.verify_provider_settings_runtime` 在专用18086实例保存draft/full、留空保留密钥、阻止目的地重绑、切换两协议与无鉴权、容器重建、422不回显。worker真实HTTP访问仅本机18187合成服务，共3次；这是一份adapter运行检查，0产品Job/Permit，不冒称完整真实Provider翻译。
- 实际备份：maintenance运行真实pg_dump/verify-backup，pg_restore转SQL后扫描无合成key，所有DB表亦无key；maintenance无配置卷。Compose实际检查app RW/worker RO、10001/0700；历史key文件仅检查metadata为0600，内容未读取。
- 独立实际浏览器：acceptance agent对真实18086（没有route mocks）完成6组保存/冲突/清除流程，桌面1440×1060和手机390×844实际截图逐张目视；无横向溢出、JS异常或浏览器外部请求。报告 `evidence/ai-service-settings/independent-ui-review.md`；最终只读截图单独绑定最终image与asset。

首次runtime脚本在Compose `up -d`后立刻访问触发启动时序错误，保留 `runtime-smoke-startup-failure.log`；增加有界readiness轮询后通过。UI作者首次过滤器无匹配、独审首次对未填价格对象作过严断言、IR重复注册pytest plugin等工具失败均保留，不冒充产品故障或测试通过。

## 交付与剩余边界

最新 `evidence/ai-service-settings/runtime-final-binding.json` 绑定源码、实际镜像、完整后端JUnit、runtime命令证据及reader-v1 CSS不变。`build-final.log`为容器内前端/后端构建。正式130场景/24退出门的旧d99报告仅历史保留，不能把本次局部证据写成全部M0/M1/M2重新认证。

最终源码 `68ec487ec8597c802e7ea06cfb7f8e40d7de754e38e0c472b77a6e178c990da8`，app/worker镜像 `sha256:84da6475f11fcef1537d9b01076f5d73b59a74563a411eabcb9be05907d12120`，前端 `index-DMpNvkVL.js`。最后密钥缺失提示修复后43契约再次全部通过（21.2秒）；独立实际页面以配置参数完整且仅缺key的分支核对“等待配置”。IR最终再次独核14个绑定文件hash、4容器、8份后端源码不变、518JUnit与当前预览状态，全通过：`evidence/ai-service-settings/independent-final-delivery-review.md`、`independent-final-runtime-verification.json`。无未关闭本功能发现。

隔离预览 `http://127.0.0.1:18086/#/settings` 保留运行。当前synthetic配置已清空为默认Responses地址、空model、无当前key、等待配置，`DISPATCH_DISABLED=true`保持。旧8080四容器和55439测试库的容器ID均未改变；原WSL环境未启动或修改。mock18187监听与临时浏览器上下文关闭，历史合成凭据版本/备份命名卷保留。

真实服务API key可由用户在设置页填写；这不自动授权我读取密钥或发起付费验收。完整M1/M2仍需真实Provider预算与指定受控文本外发授权。保存设置本身零模型请求。新host标准文库恢复不包含provider_config，需重新配置服务。

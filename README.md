# 对照文库 · 个人 PDF 版

[非阻断翻译、任务记录与 DOI 元数据](docs/milestones/nonblocking-workflow-plan.md)已实现；交付范围见[验收记录](.agent/notes/nonblocking-20260909-acceptance.md)。当前源码还包含[任务历史清理](docs/shared/task-history.md)与[学术元数据保留原文](docs/shared/original-only-content.md)，具体部署状态见各自记录。

译文人工核对和逐段确认均为可选。内容质量异常不阻止翻译、封存、发布和导出；自动检查、确定性恢复与原图对照继续执行，问题集中展示。执行故障、外发确认、版本检查和秘密保护继续生效。

**v3.0 · 产品实现与验收中 · 2026-09-16**

仓库已加入 M0–M2 的应用、后台任务、隔离解析器、数据库迁移、前端及验收 harness。**全部退出门尚未通过，不能称为完整认证的 M2 release。** 当前源码与验证入口见[工作交接](.agent/memory/current.md)。[原阶段报告](.agent/IMPLEMENTATION_STATUS.md)和[旧逐门审计](.agent/harness/GATE_GAPS.md)是历史证据，不代表当前源码或正在运行的实例。

产品边界：**仅 PDF、单实例、无用户/登录/团队/权限、仅 Docker Compose、无内置反代**。解析支持本地 OCR、公式和代码增强；无法完整恢复的内容保留原文或页图并显示提示，不承诺所有扫描件可完整翻译。设置页可配置AI服务的endpoint、协议、model ID与API key；密钥保存在后端专用卷且不回显。未配置 Provider 时仍可保存和阅读原件。

在「设置 → PDF 解析」可查看检测到的系统、CPU、内存上限及 GPU，选择当前模型支持的运行设备并保存默认方案，也可在文档详情的「本次 PDF 解析方案」单次切换：PaddleOCR-VL-1.6（新配置默认）、Docling 标准或 Granite Docling 258M（整页 VLM）。固定模型随 parser 镜像交付，CPU / NVIDIA CUDA 部署断网解析；Apple MLX 集成使用 Compose 管理的 Docker Model Runner，本机已使用本地构建的浮动标签后端镜像完成图像与受控 PDF 实测，并在设置页开放 MLX；新部署必须先完成图像验证。GPU 镜像统一打包各解析方案，详见[硬件加速与部署](docs/deployment/extraction-acceleration.md)。已保存的解析偏好保持不变；方案在入队时冻结，不修改已有来源或译文。VLM 的 CPU 速度取决于页面内容；每个任务限制 4 CPU、16 GiB；新解析默认超时为 120 分钟，可在「设置 → PDF 解析 → 解析超时（分钟）」保存 1–1440 整数分钟。超时按整份 PDF（含模型加载）计算，并在入队时冻结；已排队/运行任务保持原值，超时失败后需重新发起解析。公式 / 代码不参与翻译，并保留原 PDF 裁图；Paddle 表格支持结构化行列、合并单元格及空白格，非空单元格参与翻译，阅读页可展开原表裁图。结构不完整或包含不支持的嵌套内容时整表保留原图并警告；单元格漏字、新增文字或数字矛盾保留为非阻断提示。官方原始 HTML 保存在解析 JSON 中，不直接注入网页。单元格定位使用整表区域；跨页片段分别保留页码，不推测跨页合并关系。已有来源需要重新解析才使用新增能力，历史译文与发布版本保持原样。

设置页支持四种接口，服务类型随协议自动匹配。切换接口类型会将地址和模型 ID 填为该接口的默认值，随后仍可手动修改；打开或重新读取配置保留已保存的值。endpoint 填完整请求 URL，不自动追加路径。切换只更新待保存表单，不自动保存或调用模型。

| 接口协议 | 默认完整请求 URL | 默认模型 ID | 普通 API key 鉴权 |
|---|---|---|---|
| Responses（OpenAI 兼容） | `https://api.openai.com/v1/responses` | `gpt-5.4-mini` | `Authorization: Bearer` |
| Chat Completions（OpenAI 兼容） | `https://api.openai.com/v1/chat/completions` | `gpt-5.4-mini` | `Authorization: Bearer` |
| Gemini Interactions（原生） | `https://generativelanguage.googleapis.com/v1beta/interactions` | `gemini-3.8-flash` | `x-goog-api-key` |
| Claude Messages（原生） | `https://api.anthropic.com/v1/messages` | `claude-sonnet-5` | `x-api-key`，另发 `anthropic-version` |

上述表单默认模型 ID 于 2026-09-07 对照 [OpenAI 模型文档](https://developers.openai.com/api/docs/models/gpt-5.4-mini)、[Gemini Interactions 支持列表](https://ai.google.dev/gemini-api/docs/interactions-overview)、[Claude 模型文档](https://platform.claude.com/docs/en/models/overview)核对；只是可编辑的起点，不代表当前凭据可用或已通过真实翻译验收。

原生接口使用普通 API key，不包含 OAuth 或多 workspace 选择；四种协议均可明确选择无鉴权以连接无需密钥的本地服务。Claude 的 `api_version` 在高级选项设置，留空由后端使用 `2023-06-01`。Gemini 使用 Interactions，不转换为 generateContent。官方协议依据见本轮 [Gemini 核对](.agent/notes/gemini-claude-20260906.md)与 [Claude 独立核对](.agent/notes/gemini-claude-20260906.md)，这些记录不是真实模型调用。

容器内 `localhost` 指容器自身，本机服务须填写容器可达的地址。配置可先保存；缺少模型、地址或鉴权条件时仍显示等待配置。保存不会发送测试请求。API key 留空保留，明确清除才移除当前 key；改变地址、协议或鉴权须重新输入或明确清除旧 key。Gemini 和 Claude 两个原生协议的响应 model 必须与配置匹配，仅 Gemini 允许去除 `models/` 前缀；使用原生模型别名时应填写服务实际返回的模型 ID。服务配置不包含在标准文库备份中，新宿主恢复后需重新填写。

**预算与成本控制是可选项，新配置默认关闭。** 关闭时无需填写费率或作业金额预算，仍保存请求、用量和未知结果记录；无法确定的金额显示为未计价（`null`），不当作免费。开启后需完整费率，并执行作业与实例预算检查。旧完整配置未包含开关字段时继续开启，已有明确选择不会因旧客户端省略字段而改变。

设置显示当前三个应用上限：输入 **32768 tokens**、输出 **8192 tokens**、单元正文 **2000 字符**。新配置采用这些默认值；已有自定义值继续保留。“恢复默认”仅替换三个上限，经原有版本检查保存，不改地址、协议或密钥。这些是应用请求限制，不是模型能力声明。明确填写的免费费率 `0` 仍有效；关闭成本控制不等于供应商免费。

Gemini 请求显式 `store=false`；Claude Messages 没有该字段，也不主动启用缓存写入。两者均不承诺服务商不保留请求数据。Gemini 的输出与思考 token 合并计费；Claude 的输出计数已包含思考，不重复累加。开启成本控制时，缺失或矛盾用量、未定价维度（例如 Claude 缓存写入）或费用未确认会暂停核对。关闭时，已明确收到的合法译文可继续，金额保持未知；网络结果未知或返回模型不匹配仍停止自动派发，重试需明确承担风险。接口、故障服务和 UI 测试通过不等于真实模型兼容或语言质量认证。

启动实际产品候选版本：

先复制共享模板为本地配置（已有 `compose.yaml` 时保留现有文件）：

```sh
cp compose.example.yaml compose.yaml
docker compose build app parser db
docker compose up -d --wait
```

打开 `http://127.0.0.1:8080`。部署宿主只需 Docker Engine 与 Compose，解析模型和依赖在镜像构建期取得并校验。可选[本地翻译模型](docs/deployment/local-translation.md)仅在明确选择使用时按固定清单下载并校验，启动或读取设置不会下载。详见 [部署](docs/ops/deploy.md)、[备份与恢复](docs/ops/restore.md)、[保留与清理](docs/ops/retention.md)。已有旧基础镜像的实例升级须遵照恢复文档，不能用新数据库镜像直接覆盖原卷。

真实 Provider 验收仍需固定 model/profile/价格、后端密钥文件、测试预算及受控文本外发确认。FakeProvider 测试只验证任务、预算、版本隔离等行为，不证明真实模型兼容性或翻译质量。两篇原论文的完整来源对应复核也必须独立通过。

所有语言均可直接选择，名称使用各自语言显示；配置确认仍绑定完整公开 profile hash，详细协议见[语言与配置确认](docs/ops/languages.md)。

## 1. 从哪里开始

当前入口是上方 Compose 启动的实际应用。产品基线、六份阶段文档、共享契约与运维说明均以仓库中的 Markdown 为准。

实现产品前按顺序读取：[基线](docs/product-baseline.md) → [数据架构](docs/shared/architecture-data.md) → [任务与质量](docs/shared/workflow-quality-security.md) → [API](docs/shared/api-contract.md) → [Compose交付](docs/deployment/compose-contract.md) → 各阶段Spec/Plan。

| 阶段 | 产品Spec | 实施Plan |
|---|---|---|
| M0 PDF库与静态出版底座 | [M0 Spec](docs/milestones/M0-spec.md) | [M0 Plan](docs/milestones/M0-plan.md) |
| M1 真实PDF翻译 | [M1 Spec](docs/milestones/M1-spec.md) | [M1 Plan](docs/milestones/M1-plan.md) |
| M2 个人校对与版本管理 | [M2 Spec](docs/milestones/M2-spec.md) | [M2 Plan](docs/milestones/M2-plan.md) |

## 2. 使用应用

在应用中上传 PDF，查看真实接收、解析与任务状态；未配置翻译模型时仍可保存和阅读原件。在设置页保存模型配置，确认本次内容处理后开始翻译。文档详情提供原 PDF、已发布阅读版本和离线导出；新任务不覆盖历史产物。

根目录 `compose.yaml` 是 Git 忽略的本地部署配置，从 `compose.example.yaml` 复制后选择 CPU/CUDA/MLX；机器设置不会提交。显式的 `-f deployment/compose.production.yaml` 是共享生产配置入口。硬件与本地翻译覆盖文件沿用[部署说明](docs/ops/deploy.md)。旧的独立演示应用、静态服务器与生成的设计 HTML 已移除。

## 3. Compose 契约

[deployment/compose.production.yaml](deployment/compose.production.yaml)现在运行实际 `apps.api`、`workers.main` 和隔离 parser，包含 app/worker/parser/db 及 init/migrate/maintenance 服务。`deployment/images/` 提供源代码构建，`uv.lock`、前端 lock 和 parser model lock 固定依赖。真实镜像、离线新卷冷启动、原件完整性损坏检测和另一组新卷备份恢复已有执行记录；最终 release 仍须绑定稳定源码和实际镜像 digest 完成所有验收。

正式发行必须提供已构建镜像或完整可构建源码与锁文件；全部本地运行依赖、原生PDF库、前端产物、阅读模板及启用的Docling模型随镜像交付。用户不另装这些依赖。外部翻译服务和用户API凭据不能打包，未配置模型时文库/阅读仍应启动。依赖锁与实际镜像清单的范围见[依赖证据](docs/ops/dependencies.md)。

不包含反代容器、TLS证书、用户管理、身份中间件或ACL服务。任何可达客户端都能操作实例；默认回环绑定不是登录替代品。

## 4. 验证和状态

[包检查报告](.agent/notes/package-review.md)保留原设计包的历史检查结果。65 条需求、42 个工作包、130 个场景、24 个退出门的原始契约位于 `contracts/`；实际实现执行状态由 [harness](.agent/harness/README.md) 的追加式证据生成，历史汇总见 [IMPLEMENTATION_STATUS.md](.agent/IMPLEMENTATION_STATUS.md)，当前交接见 [.agent/memory/current.md](.agent/memory/current.md)。缺少当前源码绑定记录既不能算通过，也不表示已有实现不存在。

harness 默认将独立子任务与来源/视觉/语义复核分配给 agent，以项目文件保存所有权、发现、失败、命令和下一步。标为人工或混合验证的场景必须有独立 agent 的实际复核，不能用同一实现者的自述、模拟数据或静态文件计数代替。

可选的检查工具也通过Compose运行：

```sh
docker compose -f deployment/compose.verify.yaml run --build --rm verify
```

开发测试的 PostgreSQL、Linux parser 子进程及浏览器运行方式见 [测试说明](tests/README.md)。

工具镜像在**构建期** 安装固定版本的文档检查依赖，运行时无外网；不会付费调用模型。这只检查本包，不是M0/M1/M2应用验收。检查输出在终端；容器中的JSON不被当成产品测试证据。

本次环境若没有Docker daemon，检查报告会写明未执行镜像构建/Compose启动，不能以YAML静态解析替代这项验收。

## 5. 目录和后续实施

项目文件直接位于 Git 仓库根目录，不再需要进入 `bilingual-library-personal-pdf-v3/` 子目录。`apps/`、`packages/`、`workers/`、`tests/`、`contracts/` 与部署文件保持原相对结构。

Agent 工作资料统一位于 [`.agent/`](.agent/README.md)：可复用验收代码在 `.agent/harness/`，工作记忆和笔记在 `.agent/memory/`、`.agent/notes/`，中间产物在 `.agent/tmp/`。持久本地环境与凭据相关状态在 `.agent/local-data/`。Git 忽略后两类本地数据，保留验收代码和长期文件记忆；Docker 镜像排除整个 `.agent/`。历史证据保留原字节，旧路径通过 `.agent/relocation.json` 映射。

`apps/`、`packages/` 和 `workers/` 为产品代码；`docs/milestones/` 为阶段文档；`docs/shared/` 为共享契约；`contracts/` 为 Schema 与追踪数据；`fixtures/` 为人工测试资料；`deployment/` 为 Compose 与依赖定义；`tools/` 为契约检查与维护工具；`reference/` 保存固定阅读样式、两篇受控种子论文与字节校验记录。

[AGENTS.md](AGENTS.md)给出编码Agent执行入口。产品状态以实际 API、数据库和执行证据为准。旧包中冲突的多格式/身份/权限要求已被本版本取代，不与旧Spec叠加实施。

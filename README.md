# 对照文库 · 个人 PDF 版

**下一轮计划 · 2026-09-09（待实施）**：[非阻断翻译、任务记录与 DOI 元数据](milestones/nonblocking-workflow-plan.md)。已登记 12 个工作包，覆盖质量异常不阻断、自动恢复与原图对照、完整任务历史、UI 文案和 DOI 书目信息。以下介绍仍反映现有行为，不能据此判断新计划已落地。

译文人工核对和逐段确认均为可选；通过完整性检查即可封存、发布和导出。语义/术语提示会保留。已有草稿若显示旧质量报告，重新运行一次质量检查即可，无需重新翻译。

**v3.0 · 产品实现与验收中 · 2026-09-07**

仓库已加入 M0–M2 的应用、后台任务、隔离解析器、数据库迁移、前端及验收 harness。**全部退出门尚未通过，不能称为完整认证的 M2 release。** 当前证据与缺口分别见 [IMPLEMENTATION_STATUS.md](.agent/IMPLEMENTATION_STATUS.md) 和 [逐门审计](.agent/harness/GATE_GAPS.md)。

产品边界：**仅 PDF、单实例、无用户/登录/团队/权限、仅 Docker Compose、无内置反代**。解析默认开启本地 CPU OCR、公式和代码增强；扫描件仍须通过来源完整性预检，不承诺所有扫描件可自动翻译。设置页可配置AI服务的endpoint、协议、model ID与API key；密钥保存在后端专用卷且不回显。未配置 Provider 时仍可保存和阅读原件。

在「设置 → PDF 解析」可保存默认方案，也可在文档详情的「本次 PDF 解析方案」单次切换：Docling 标准（默认）、Granite Docling 258M（整页 VLM）或 PaddleOCR-VL-1.6（官方 PaddleOCR 套件，本地 native 后端）。三方案均 CPU only，固定模型随 parser 镜像交付，断网运行；方案在入队时冻结，不修改已有来源或译文。VLM 的 CPU 速度取决于页面内容；每个任务限制 4 CPU、16 GiB；新解析默认超时为 120 分钟，可在「设置 → PDF 解析 → 解析超时（分钟）」保存 1–1440 整数分钟。超时按整份 PDF（含模型加载）计算，并在入队时冻结；已排队/运行任务保持原值，超时失败后需重新发起解析。公式 / 代码不参与翻译，并保留原 PDF 裁图；Paddle 表格支持结构化行列、合并单元格及空白格，非空单元格参与翻译，阅读页可展开原表裁图。结构不完整或包含不支持的嵌套内容时整表保留原图并警告；单元格漏字、新增文字或数字矛盾阻断来源预检。官方原始 HTML 保存在解析 JSON 中，不直接注入网页。单元格定位使用整表区域；跨页片段分别保留页码，不推测跨页合并关系。已有来源需要重新解析才使用新增能力，历史译文与发布版本保持原样。

设置页支持四种接口，服务类型随协议自动匹配。切换接口类型会将地址和模型 ID 填为该接口的默认值，随后仍可手动修改；打开或重新读取配置保留已保存的值。endpoint 填完整请求 URL，不自动追加路径。切换只更新待保存表单，不自动保存或调用模型。

| 接口协议 | 默认完整请求 URL | 默认模型 ID | 普通 API key 鉴权 |
|---|---|---|---|
| Responses（OpenAI 兼容） | `https://api.openai.com/v1/responses` | `gpt-5.4-mini` | `Authorization: Bearer` |
| Chat Completions（OpenAI 兼容） | `https://api.openai.com/v1/chat/completions` | `gpt-5.4-mini` | `Authorization: Bearer` |
| Gemini Interactions（原生） | `https://generativelanguage.googleapis.com/v1beta/interactions` | `gemini-3.8-flash` | `x-goog-api-key` |
| Claude Messages（原生） | `https://api.anthropic.com/v1/messages` | `claude-sonnet-5` | `x-api-key`，另发 `anthropic-version` |

上述表单默认模型 ID 于 2026-09-07 对照 [OpenAI 模型文档](https://developers.openai.com/api/docs/models/gpt-5.4-mini)、[Gemini Interactions 支持列表](https://ai.google.dev/gemini-api/docs/interactions-overview)、[Claude 模型文档](https://platform.claude.com/docs/en/models/overview)核对；只是可编辑的起点，不代表当前凭据可用或已通过真实翻译验收。

原生接口使用普通 API key，不包含 OAuth 或多 workspace 选择；四种协议均可明确选择无鉴权以连接无需密钥的本地服务。Claude 的 `api_version` 在高级选项设置，留空由后端使用 `2023-06-01`。Gemini 使用 Interactions，不转换为 generateContent。官方协议依据见本轮 [Gemini 核对](.agent/tmp/evidence/gemini-claude/gemini-official-contract-review.md)与 [Claude 独立核对](.agent/tmp/evidence/gemini-claude/independent-claude-review.md)，这些记录不是真实模型调用。

容器内 `localhost` 指容器自身，本机服务须填写容器可达的地址。配置可先保存；缺少模型、地址或鉴权条件时仍显示等待配置。保存不会发送测试请求。API key 留空保留，明确清除才移除当前 key；改变地址、协议或鉴权须重新输入或明确清除旧 key。Gemini 和 Claude 两个原生协议的响应 model 必须与配置匹配，仅 Gemini 允许去除 `models/` 前缀；使用原生模型别名时应填写服务实际返回的模型 ID。服务配置不包含在标准文库备份中，新宿主恢复后需重新填写。

**预算与成本控制是可选项，新配置默认关闭。** 关闭时无需填写费率或作业金额预算，仍保存请求、用量和未知结果记录；无法确定的金额显示为未计价（`null`），不当作免费。开启后需完整费率，并执行作业与实例预算检查。旧完整配置未包含开关字段时继续开启，已有明确选择不会因旧客户端省略字段而改变。

设置显示当前三个应用上限：输入 **32768 tokens**、输出 **8192 tokens**、单元正文 **2000 字符**。新配置采用这些默认值；已有自定义值继续保留。“恢复默认”仅替换三个上限，经原有版本检查保存，不改地址、协议或密钥。这些是应用请求限制，不是模型能力声明。明确填写的免费费率 `0` 仍有效；关闭成本控制不等于供应商免费。

Gemini 请求显式 `store=false`；Claude Messages 没有该字段，也不主动启用缓存写入。两者均不承诺服务商不保留请求数据。Gemini 的输出与思考 token 合并计费；Claude 的输出计数已包含思考，不重复累加。开启成本控制时，缺失或矛盾用量、未定价维度（例如 Claude 缓存写入）或费用未确认会暂停核对。关闭时，已明确收到的合法译文可继续，金额保持未知；网络结果未知或返回模型不匹配仍停止自动派发，重试需明确承担风险。接口、故障服务和 UI 测试通过不等于真实模型兼容或语言质量认证。

启动实际产品候选版本：

```powershell
docker compose -f deployment/compose.production.yaml build app parser db
docker compose -f deployment/compose.production.yaml up -d --wait
```

打开 `http://127.0.0.1:8080`。部署宿主只需 Docker Engine 与 Compose，模型和依赖在镜像构建期取得并校验；运行期不下载。详见 [部署](ops/deploy.md)、[备份与恢复](ops/restore.md)、[保留与清理](ops/retention.md)。已有旧基础镜像的实例升级须遵照恢复文档，不能用新数据库镜像直接覆盖原卷。

真实 Provider 验收仍需固定 model/profile/价格、后端密钥文件、测试预算及受控文本外发确认。FakeProvider 测试只验证任务、预算、版本隔离等行为，不证明真实模型兼容性或翻译质量。两篇原论文的完整来源对应复核也必须独立通过。

所有语言均可直接选择，名称使用各自语言显示；配置确认仍绑定完整公开 profile hash，详细协议见[语言与配置确认](ops/languages.md)。

## 1. 从哪里开始

打开[文档与原型总目录](index.html)。[交互原型](prototype/index.html)可直接离线打开；纸色、侧栏和阅读器沿用上一版。六份阶段文档与共享契约均提供Markdown和本地HTML。

实现产品前按顺序读取：[基线](00-product-baseline.md) → [数据架构](shared/architecture-data.md) → [任务与质量](shared/workflow-quality-security.md) → [API](shared/api-contract.md) → [Compose交付](deployment/compose-contract.md) → 各阶段Spec/Plan。

| 阶段 | 产品Spec | 实施Plan |
|---|---|---|
| M0 PDF库与静态出版底座 | [M0 Spec](milestones/M0-spec.md) | [M0 Plan](milestones/M0-plan.md) |
| M1 真实PDF翻译 | [M1 Spec](milestones/M1-spec.md) | [M1 Plan](milestones/M1-plan.md) |
| M2 个人校对与版本管理 | [M2 Spec](milestones/M2-spec.md) | [M2 Plan](milestones/M2-plan.md) |

## 2. 运行本次交付的原型

在解压目录执行：

```sh
docker compose up --build -d
```

打开 `http://localhost:8080`。停止用 `docker compose down`。可从`.env.example`创建`.env`调整绑定地址与端口；默认仅回环地址。无需安装Python、Node、数据库或反代。镜像首次构建需要取得Python基础镜像；**运行阶段不下载依赖** 。

根目录`compose.yaml`运行的是**设计原型静态服务器** ，不是正式产品API。不会往服务器上传PDF、调用模型或写入产品数据库。它也不会启动并伪装一组没有实现的worker/db服务。原型服务器没有登录，仅供本地可信环境体验。

原型真正可用：PDF选择的扩展名/大小/文件头初检、浏览器内条目管理、收藏与搜索、已有两篇静态论文阅读/单文件导出、演示草稿修改、候选冲突、历史回滚、术语和偏好保存。原型文件头检查不是完整PDF合法性检查。

原型明确模拟：PDF解析、段落数量、费用估计、翻译、质量检查与发布状态。手动推进的流程样例固定为三段，**与选择的PDF正文无关** ，产物醒目标识“流程样例”。原件条目不会被样例译文悄悄替换。

原型的浏览器 localStorage 仅保存演示状态；选中文件的 Object URL 与文件字节不持久，刷新后需重新选择原件。不要输入任何模型密钥。上方生产 Compose 入口使用 PostgreSQL 与命名卷保存实际产品状态，两者的数据互不替代。

## 3. 体验路径

进入“PDF上传”，选择[人工合成测试PDF](fixtures/sample.pdf)或自己的PDF；非PDF被拒绝。加入原型文库后可查看原件。选择“演示翻译流程”进入任务，逐阶段推进，预检确认后继续；有质量异常的演示需要在校对中修正数字再发表样例。

已发布流程样例可以编辑、产生重译候选、比较并接受、发布新版本、回滚、导出静态HTML。原有两篇论文始终独立保留，不会被演示改写。

## 4. 正式产品的 Compose 契约

[deployment/compose.production.yaml](deployment/compose.production.yaml)现在运行实际 `apps.api`、`workers.main` 和隔离 parser，包含 app/worker/parser/db 及 init/migrate/maintenance 服务。`images/` 提供源代码构建，`uv.lock`、前端 lock 和 parser model lock 固定依赖。真实镜像、离线新卷冷启动、原件完整性损坏检测和另一组新卷备份恢复已有执行记录；最终 release 仍须绑定稳定源码和实际镜像 digest 完成所有验收。

正式发行必须提供已构建镜像或完整可构建源码与锁文件；全部本地运行依赖、原生PDF库、前端产物、阅读模板及启用的Docling模型随镜像交付。用户不另装这些依赖。外部翻译服务和用户API凭据不能打包，未配置模型时文库/阅读仍应启动。查看[依赖设计清单](deployment/dependency-inventory.json)；其中待定版本不是完成的release lock。

不包含反代容器、TLS证书、用户管理、身份中间件或ACL服务。任何可达客户端都能操作实例；默认回环绑定不是登录替代品。

## 5. 验证和状态

[包检查报告](.agent/notes/package-review.md)保留原设计包的历史检查结果。65 条需求、42 个工作包、130 个场景、24 个退出门的原始契约位于 `contracts/`；实际实现执行状态由 [harness](.agent/harness/README.md) 的追加式证据生成，见 [IMPLEMENTATION_STATUS.md](.agent/IMPLEMENTATION_STATUS.md)。缺少当前源码绑定记录既不能算通过，也不表示已有实现不存在。

harness 默认将独立子任务与来源/视觉/语义复核分配给 agent，以项目文件保存所有权、发现、失败、命令和下一步。标为人工或混合验证的场景必须有独立 agent 的实际复核，不能用同一实现者的自述、模拟数据或静态文件计数代替。

可选的检查工具也通过Compose运行：

```sh
docker compose --profile tools run --build --rm verify
```

工具镜像在**构建期** 安装固定版本的文档检查依赖，运行时无外网；不会付费调用模型。这只检查本包，不是M0/M1/M2应用验收。检查输出在终端；容器中的JSON不被当成产品测试证据。

本次环境若没有Docker daemon，检查报告会写明未执行镜像构建/Compose启动，不能以YAML静态解析替代这项验收。

## 6. 目录和后续实施

项目文件直接位于 Git 仓库根目录，不再需要进入 `bilingual-library-personal-pdf-v3/` 子目录。`apps/`、`packages/`、`workers/`、`tests/`、`contracts/` 与部署文件保持原相对结构。

Agent 工作资料统一位于 [`.agent/`](.agent/README.md)：可复用验收代码在 `.agent/harness/`，工作记忆和笔记在 `.agent/memory/`、`.agent/notes/`，中间产物在 `.agent/tmp/`。持久本地环境与凭据相关状态在 `.agent/local-data/`。Git 忽略后两类本地数据，保留验收代码和长期文件记忆；Docker 镜像排除整个 `.agent/`。历史证据保留原字节，旧路径通过 `.agent/relocation.json` 映射。

`prototype/`为可操作UI与原有静态阅读资料；`milestones/`为六份主文档；`shared/`为共享契约；`contracts/`为Schema与追踪数据；`fixtures/`为人工测试资料；`deployment/`为目标Compose与依赖边界；`tools/`为本包构建与检查工具；`reference/`固定阅读样式及字节校验记录。

[AGENTS.md](AGENTS.md)给出编码Agent执行入口。不要把本次原型的localStorage、手动推进或固定段落当成正式API实现。旧包中冲突的多格式/身份/权限要求已被本版本取代，不与旧Spec叠加实施。

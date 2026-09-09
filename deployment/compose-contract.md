# Docker Compose 交付与依赖打包契约

**2026-09-09 下一轮部署计划（待实施）。** NB 工作流保留离线 CPU parser；DOI/Crossref 请求由后端 metadata_lookup 任务执行，不给 parser 联网或挂载 Provider 密钥。新增任务日志与元数据需持久化、备份和增量迁移演练，完成后同步交付 app/worker/parser。参见 [执行计划](../milestones/nonblocking-workflow-plan.md)，当前 Compose 尚未因此更改。

**2026-09-08 可配置超时。** 新解析默认 120 分钟，设置页支持 1–1440 整数分钟，随任务冻结。worker deadline、等待循环、parser 墙钟和子进程 CPU 秒限制统一使用该任务值；上传检查及无超时字段的旧任务仍限 15 分钟。此补充覆盖下文固定 15 分钟解析限制。部署需同步更新 app / worker / parser；无需模型更新或数据库 schema 迁移，保留 4 CPU / 16 GiB / 256 PID 与 network_mode:none。

**2026-09-08 解析方案扩展。** 同一 parser 镜像提供 Docling 标准、Granite Docling 258M 和官方 PaddleOCR-VL-1.6。新增权重及 PP-DocLayoutV3 按 `parser-models.lock.json` 的固定 HF commit 与逐文件 SHA-256 在构建期下载；PaddleOCR 3.7.0 / PaddleX 3.7.2 / PaddlePaddle CPU 3.3.1 由 uv.lock 固定。运行显式 CPU，Paddle 使用 native 后端、单页/区域 batch=1，关闭改变 PDF 坐标的旋转和展平预处理；无服务器地址或 API key。继续使用原 Compose 的网络隔离、只读根、资源和超时界限。

PaddleOCR native CPU 的 FP32 权重加载在 8 GiB 容器中触发换页，当前共享 parser 上限提升至 16 GiB；保留 4 CPU / 15 分钟。OpenCV 使用官方套件要求的 opencv-contrib-python 4.10.0.84（单一 cv2 分发），镜像包含所需系统库，避免并存 headless 与 contrib。


2026-09-08 CPU 解析增强：parser 默认开启 RapidOCR（ONNX Runtime CPU）、CodeFormulaV2 公式/代码识别和现有 TableFormer Accurate。所有模型固定版本及逐文件 SHA-256，构建时下载；CPU PyTorch、ONNX Runtime 与模型随镜像提供。运行仍为 network_mode:none、只读根目录、无 Provider 凭据；资源改为 4 CPU / 8 GiB / 256 PID，墙钟上限 15 分钟。扫描页先运行 OCR，再依据独立覆盖证据决定来源预检是否阻断，不能将 OCR 非空视作全文认证。

**本章定义正式产品的部署验收。** 包根的`compose.yaml`只运行本次交互原型和设计文档；它不是生产翻译服务。`compose.production.yaml`是与Spec一致的目标部署模板，镜像/应用命令由M0/M1实施后提供，缺失镜像变量时应失败而非悄悄运行mock。

## 1. 唯一部署路径

正式发布只支持Docker Engine + Compose v2的Linux containers。宿主不安装Python、Node、qpdf、PostgreSQL、Docling、CUDA或OCR。本轮linux/amd64为必验平台，CPU即可；ARM64不承诺直到独立构建/验收。

长期运行4个容器：app、worker、parser、db。一次性init/migrate使用相同应用镜像完成空卷初始化和schema迁移；这两个是运维步骤，不是新外部依赖。只有app的8080端口被映射到宿主，默认loopback。没有反代、登录服务、Redis、MinIO或外部数据库配置方案。

## 2. 什么必须随镜像打包

| 依赖类别 | 打包位置 | 验收 |
|---|---|---|
| 管理前端与静态资产 | app镜像，由多阶段Node build输出 | 浏览器不依赖CDN、外部字体、在线npm |
| Python/FastAPI/ORM/迁移/队列/模板 | app/worker镜像，锁定依赖及hash | 冷启动不pip install |
| PostgreSQL server与备份client | db镜像及maintenance镜像工具 | 用户不另装数据库；备份client主版本兼容 |
| PDF检查、图像解码、页图与Docling | parser镜像 | 原生.so/系统库齐全；无宿主路径依赖 |
| Docling layout/table等实际启用模型 | parser镜像固定artifacts_path | build时获取固定revision并记录逐文件hash；runtime零下载 |
| 公式构建与阅读资源 | worker中构建工具与app已渲染资源 | JS关闭正文可读；KaTeX所需资产随镜像/产物依法打包 |
| 依赖元数据 | release manifest / SBOM / THIRD_PARTY_NOTICES | 镜像digest、软件锁、模型hash与许可证一致 |

Docling默认可能在首次使用下载模型，因此必须显式预取并设置本地资产目录，不只是设置离线环境变量。[S2] 不启用的OCR模型无需为了“所有依赖”盲目包含；启用的每条能力必须足够自包含。这里不分发本容器的字体文件；真正产品镜像所需字体由实现阶段按许可证从依赖包构建并验收。

“打包依赖”不包含Docker引擎、宿主内核和外部翻译供应商服务。用户仍需有效API凭据与已选模型访问；没有密钥时系统能启动和读库，仅翻译处于waiting_config。M0不需要外部模型调用。

## 3. 构建期与运行期

源码分发允许在`docker compose build`过程中联网获取锁定依赖/模型；所有动作在Dockerfile里完成，不要求手动装宿主工具。可部署release还应提供预构建镜像及digest；完全离线安装需预先`docker image save/load`对应镜像。本交接包不包含尚未实现应用的镜像tar，不承诺离线首次安装。

**运行期禁止** pip/npm/apt安装、模型自动下载、拉取任意最新模型、下载网页资源。parser的`network_mode:none`通过Compose独立网络栈执行；worker经显式配置访问Provider。Compose网络本身不是按域名的出站防火墙，不在文档中虚构这种保证。

## 4. 初始化、健康和启动顺序

init在data/uploads/internal/parser_inputs/parser_outputs/backups/provider_config命名卷内创建目录并设置固定运行UID/GID，不访问宿主根目录；provider_config为10001:10001、0700，密钥文件0600。root仅限这次卷初始化，常驻服务非root、drop ALL capabilities、no-new-privileges、read_only rootfs。tmp/缓存明确挂tmpfs或工作卷，不依赖可写镜像层。

db使用健康检查；migrate等db healthy并成功执行迁移；app/worker等migrate successful；parser等init成功。Compose短depends_on只保证启动顺序、不保证服务就绪，因此使用长条件加健康检查。[S1] db重启后的重连、任务重领仍由应用实现，不能误以为Compose自动处理事务恢复。

app `/health/live`只证明进程存活；`/health/ready`验证schema/卷可读，不把外部Provider可用性当阅读服务就绪条件。worker heartbeat/队列检查；parser heartbeat文件和本地模型清单检查；模型缺失必须readiness失败。

## 5. 配置界面

| 配置 | 位置 | 默认/语义 |
|---|---|---|
| BIND_ADDRESS / PORT | Compose .env | 127.0.0.1 / 8080 |
| ALLOWED_HOSTS / APP_ORIGINS | app配置文件 | localhost/loopback；自行接入其他域名时修改允许列表 |
| DB connection | 内部生成连接配置/secret | 只有app/worker/migrate需要，parser不需要 |
| Provider endpoint/协议/model/profile/价格 | 设置页写入版本化配置文件；旧部署profile文件作为fallback | 保存不调用模型；新派发绑定配置hash |
| Provider API key | 设置页一次性输入，后端provider_config卷保存secret文件；旧worker-only secret作为fallback | app RW、worker RO，parser/db/maintenance零访问；不写镜像、不回显、不写浏览器存储 |
| PDF限额/并发/预算 | app配置+单实例偏好 | 基线值可调，变更记录版本 |
| READ_ONLY | 运维开关 | 只读维护保护，不是用户权限 |

外部请求是否暂停由 PostgreSQL `Settings.dispatch_disabled` 持久化，不使用环境变量。设置页 AI 服务区域提供“允许外部 API 请求”开关；单独保存后即时生效，容器重建不覆盖。新实例默认暂停，保存 Provider 配置不自动允许外发。恢复/维护仍可将其设为暂停，维护结束后须在设置页明确开启；未知费用需要确认并保留原账本，不自动重试未知任务。

Compose secrets是向特定容器挂载文件的方式，不应宣传为宿主磁盘加密；文件来源的uid/gid/mode需要结合实际bind挂载和容器UID测试，不依靠被忽略的重映射字段。[S3] 初始化命令在容器内生成数据库连接秘密；Provider secret可为空，使无模型配置也能启动。

设置页支持用户指定的四种完整请求 URL：OpenAI 兼容 Responses / Chat Completions（`provider=openai`、Bearer）、原生 Gemini Interactions（`provider=gemini`、`x-goog-api-key`）、原生 Claude Messages（`provider=anthropic`、`x-api-key`）。原生使用普通 API key，不包括 OAuth 或多 workspace；本地免鉴权服务必须显式选择 `none`。Claude 另发 `anthropic-version`，不可变 profile 中的 `api_version` 默认 `2023-06-01`，非 Claude 不携带该字段。Gemini 使用完整 Interactions URL，不转换成 generateContent；示例与官方字段依据见 [Gemini 核对](../.agent/tmp/evidence/gemini-claude/gemini-official-contract-review.md)与 [Claude 核对](../.agent/tmp/evidence/gemini-claude/independent-claude-review.md)。

配置可未填完就保存；公开参数不完整或缺少必需密钥时派发等待配置，不影响原件保存与阅读。配置卷不属于标准备份，容器重建保留该命名卷；跨宿主恢复需重新配置。原 worker secret 不自动迁移到设置卷。更换目的地、协议或鉴权不能把旧 key 静默用于新配置；清除当前 key 不删除已绑定在途请求的历史版本。worker 使用固定 profile hash；Gemini 和 Claude 两个原生协议另校验响应模型匹配（仅 Gemini 正规化 `models/` 前缀）。不自动换模型、跟随重定向或回退协议。

Gemini 请求显式 `store=false`；Claude 无此字段且不主动启用缓存写入，数据保留仍以供应商政策为准。Gemini 输出与思考 token 合并，Claude 输出已含思考；开启金额控制时，必需计数缺失/矛盾与未定价用量（包括意外缓存写入）保留未知成本并暂停，不补零费用。关闭时，已完成的合法输出可继续，但未知金额仍为 `null`；网络未知结果不自动重试。镜像、配置、原生请求格式和本地故障服务验证不能冒充真实供应商兼容、硬计费上限或翻译质量认证。

2026-09-07 补充：金额控制开关和三个请求上限保存在同一不可变 Provider profile 中，不增加服务、容器或环境依赖。新配置默认关闭金额控制，应用默认输入/输出/正文单元上限为 `32768/8192/2000`；旧完整配置缺开关字段按开启解释，读取不改旧 hash。schema 11 仅允许 Job 预算和 Permit 预留金额为 NULL，不清零旧金额、不删除历史 unknown。备份继续包含账本与任务状态，恢复后仍保持维护/派发禁用；重新配置或关闭金额控制都不自动解除这些状态。真实调用验收的测试预算授权不因产品开关取消。

反代、TLS、域名、远程登录由用户自行安排。本产品不提供任何反代配置示例或认证头解析，只保证直接HTTP的相对路径和正常上传/Range/SSE接口可用。子路径部署不列为本轮必验，使用根路径部署。

## 6. 备份、升级与恢复

正式CLI全部通过`docker compose run --rm maintenance ...`执行，备份到挂载卷；包含PG一致快照、全部被引用原件/IR/产物、模板版本、删除账本和预算/未知请求状态。不包含API密钥。

备份前进入维护模式、停止新派发、等待安全检查点；在途远端请求若不能确认完成，按unknown保留预算和证据。复制文件时不能同时清理被备份引用资产；维护锁覆盖备份窗口。失败备份不标可恢复。

升级先备份、校验镜像摘要、迁移schema，再恢复读取；expand/migrate/contract避免删字段导致旧artifact不可读。正式回退需要兼容schema或恢复备份，不承诺任何downgrade都自动安全。

恢复先将数据库派发状态设为暂停，验证文件manifest/DB引用、展示所有outcome_unknown，由维护者核对后在设置页允许外发。旧文章与PDF在无Provider时继续可读。用户已下载的离线文件无法远程撤回。

## 7. Release gate：全部依赖的可证明性

M0/M1必须在只有Docker+Compose的干净主机上启动、上传受控PDF、读取/导出，重建容器验证数据仍在。M1进一步清空runtime缓存、阻断模型仓库网络，再解析冻结语料；任何运行时下载失败都不能被mock结果掩盖。

记录每镜像架构、digest、构建源码commit、锁文件hash、模型文件清单、SBOM、许可证、漏洞检查和验收结果。`dependency-inventory.json`目前为实现前的责任清单，version/digest为空代表待填，**不能作为已完成release锁文件** 。正式release校验必须拒绝待填值。

本包的Compose配置语法结构与边界可静态检查；当前环境没有Docker引擎，不能宣称镜像构建、Compose冷启或生产备份已实测。

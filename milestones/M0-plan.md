# M0 实施 Plan · PDF 原件库与静态出版底座

**版本3.0 · 对应[M0 Spec](M0-spec.md) · 所有工作包not_started**

## 1. 进入条件与实施策略

本v3约束和参考样式已经确认；能够在Docker+Compose干净环境运行测试；不得从旧原型的配对文本入口开始实现。

沿用既有设计和领域模型，先写退出测试，再按依赖实施。前端原型只提供交互参考，不将localStorage、固定译文或手动推进移植为正式后端。

## 2. 工作包依赖总表

| 工作包 | 工作内容 | 前置依赖 | 工程人日估算 |
|---|---|---|---|
| M0-P01 | 冻结个人 PDF 范围与阅读参考 | 无 | 1–2 |
| M0-P02 | 仓库与 Compose-only 运行框架 | M0-P01 | 2–3 |
| M0-P03 | Schema与语义不变量 | M0-P01 | 3–4 |
| M0-P04 | 单库数据、存储与直接文件服务 | M0-P02, M0-P03 | 3–4 |
| M0-P05 | 静态Renderer与结构支持 | M0-P03 | 3–5 |
| M0-P06 | 最小耐久任务与Publisher | M0-P04, M0-P05 | 3–4 |
| M0-P07 | PDF保存与个人文档库 UI | M0-P04, M0-P06 | 2–4 |
| M0-P08 | 受控内置旧页与示例迁移 | M0-P04, M0-P06 | 1–2 |
| M0-P09 | 离线导出与直接静态读取 | M0-P05, M0-P06 | 2–3 |
| M0-P10 | UI和视觉回归 | M0-P07, M0-P08, M0-P09 | 2–3 |
| M0-P11 | 文件安全、 Compose依赖与恢复演练 | M0-P08, M0-P09 | 2–3 |
| M0-P12 | M0退出评审与交接 | M0-P10, M0-P11 | 1–2 |

顺序相加估算为25–39工程人日，是包括测试/修复的规划量级，不是AI运行时间、日历工期或承诺。可并行工作按依赖图安排；原文核对、真实Provider、镜像构建与环境限制会影响实际时间。需求中的职责可由同一维护者/编码Agent执行，不要求建立多人团队。

## 3. 逐包实施与完成检查

### M0-P01 · 冻结个人 PDF 范围与阅读参考

**前置：** 无。 **需求：** M0-R01, M0-R02, M0-R11。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `docs/decision-records.md`
- `reference/reader-v1.css`
- `tests/contracts/test_scope.py`

**步骤：**

1. 以用户最新五条要求覆盖旧版；列明PDF-only/no identity/Compose-only/no proxy负约束。
2. 验证两个旧页与reader-v1样式hash，保留旧译读说明。
3. 冻结PDF样本、语义IR和验收证据格式；此时先写退出测试。

**完成检查：** 规格、负约束和参考hash可机读检查，旧要求有迁移记录。

**回归范围：** M0-AT01A, M0-AT01B, M0-AT02A, M0-AT02B, M0-AT11A, M0-AT11B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P02 · 仓库与 Compose-only 运行框架

**前置：** M0-P01。 **需求：** M0-R18。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/web/`
- `apps/api/`
- `workers/`
- `compose.yaml`
- `images/`
- `tests/compose/`

**步骤：**

1. 建立React/TypeScript前端和Python模块化后端；前端build结果在app镜像。
2. app/worker/parser/db/migrate Compose服务，只有app发布一个HTTP端口，绝不加入反代或登录服务。
3. 提供健康检查/命令/自动初始化空卷与依赖锁定；宿主不运行pip/npm。

**完成检查：** 干净Docker宿主可启动M0骨架，失败健康检查可见；交付镜像digest清单。

**回归范围：** M0-AT18A, M0-AT18B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P03 · Schema与语义不变量

**前置：** M0-P01。 **需求：** M0-R04, M0-R05, M0-R06, M0-R17。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/contracts/`
- `packages/ir/validator.py`
- `tests/unit/test_ir_semantics.py`

**步骤：**

1. 实施v3 Schema和受限inline；原PDF/normalized映射、title、容器归属和哈希规范。
2. 构造重复文本不同ID、跨页provenance、table子块等正负fixture。
3. 旧版数据只能受控迁移；普通客户端不能导入v1/v2/原型JSON；新来源唯一入口为PDF。

**完成检查：** Schema和语义校验分层，错误路径可定位，修改不会改变历史hash。

**回归范围：** M0-AT04A, M0-AT04B, M0-AT05A, M0-AT05B, M0-AT06A, M0-AT06B, M0-AT17A, M0-AT17B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P04 · 单库数据、存储与直接文件服务

**前置：** M0-P02, M0-P03。 **需求：** M0-R12, M0-R13, M0-R17。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `migrations/001_core.sql`
- `packages/storage/`
- `apps/api/documents/`
- `apps/api/files/`

**步骤：**

1. 建Document/SourceAsset/Draft/Artifact等表，无users/workspaces/ACL/FK。
2. 持久卷使用生成的安全存储键；app通过manifest解析文件，不暴露任意目录。
3. 服务UI/API/reader直接HTTP，设置Host/Origin请求保护和loopback默认；不读反代身份头。

**完成检查：** 无登录首启、库重启不丢、路径穿越负例、删除资源读取拒绝。

**回归范围：** M0-AT12A, M0-AT12B, M0-AT13A, M0-AT13B, M0-AT17A, M0-AT17B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P05 · 静态Renderer与结构支持

**前置：** M0-P03。 **需求：** M0-R02, M0-R06, M0-R07, M0-R08, M0-R10, M0-R16。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/reader/renderer.py`
- `packages/reader/reader.js`
- `tests/unit/test_render_all_kinds.py`

**步骤：**

1. 复用冻结CSS，全部启用block类型明确渲染，不复用旧文本子集当全功能。
2. 实现table/caption 容器归属、脚注回链、title只一次、保护原子和公式原式/原图。
3. 把时间元数据排除正文，关闭网络并测试重建字节稳定和内容转义。

**完成检查：** 正负结构fixture通过；禁用JS全内容可读；非法URL/资产/HTML被阻断。

**回归范围：** M0-AT02A, M0-AT02B, M0-AT06A, M0-AT06B, M0-AT07A, M0-AT07B, M0-AT08A, M0-AT08B, M0-AT10A, M0-AT10B, M0-AT16A, M0-AT16B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P06 · 最小耐久任务与Publisher

**前置：** M0-P04, M0-P05。 **需求：** M0-R14, M0-R15, M0-R17。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/jobs/`
- `packages/publisher/`
- `migrations/002_jobs.sql`
- `tests/faults/test_publish_crash.py`

**步骤：**

1. 实现短事务claim、lease、heartbeat、fencing与持久render/export任务。
2. 冻结输入→临时构建→manifest验证→不可变asset→CAS发布。
3. 注入文件写半截、写完未切指针、CAS冲突、旧worker迟到和GC竞态。

**完成检查：** 任何注入点当前页面始终完整，旧worker不能写当前结果。

**回归范围：** M0-AT14A, M0-AT14B, M0-AT15A, M0-AT15B, M0-AT17A, M0-AT17B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P07 · PDF保存与个人文档库 UI

**前置：** M0-P04, M0-P06。 **需求：** M0-R03, M0-R12, M0-R15。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/web/features/upload-pdf/`
- `apps/api/uploads/`
- `packages/ingestion/pdf_intake.py`
- `workers/parser/inspect.py`

**步骤：**

1. 仅PDF拖拽/选择，流式上传、真实字节上限/hash/finalize。
2. 隔离inspector检查有效性、加密、页数，建source_only条目；疑似扫描可保存但不假装可译。
3. 标题/标签/收藏/归档/原件预览及查重，M0机器翻译入口显示阶段不可用。

**完成检查：** PDF持久入库与重传幂等；非PDF/伪装/加密负例；不引入双语文本或IR导入。

**回归范围：** M0-AT03A, M0-AT03B, M0-AT12A, M0-AT12B, M0-AT15A, M0-AT15B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P08 · 受控内置旧页与示例迁移

**前置：** M0-P04, M0-P06。 **需求：** M0-R11。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/seed/legacy.py`
- `reference/legacy-manifest.json`
- `tests/integration/test_legacy_seed.py`

**步骤：**

1. 只迁移随release提供的两份旧页和PDF，验证允许的文件hash。
2. 通过Compose CLI显式seed，重跑幂等；普通API不支持HTML输入。
3. 原文整理说明和未知来源状态保留；导航变更限定在清单中。

**完成检查：** 原文/CSS不改写、原PDF可打开、同一示例不重复入库。

**回归范围：** M0-AT11A, M0-AT11B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P09 · 离线导出与直接静态读取

**前置：** M0-P05, M0-P06。 **需求：** M0-R09, M0-R13, M0-R16。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/exporter/`
- `apps/api/artifacts/`
- `tests/browser/offline-reader.spec.ts`

**步骤：**

1. 目录包本地相对资源；单文件HTML嵌入资源；按选项包含/不含原PDF。
2. 正文预写完整，无API/模型/外部CDN运行时依赖，核心无JS可读。
3. 下载与预览检查manifest及删除状态，不做用户鉴权/签名分享。

**完成检查：** 无网络/无JS有完整正文；导出不留必坏PDF按钮或秘密。

**回归范围：** M0-AT09A, M0-AT09B, M0-AT13A, M0-AT13B, M0-AT16A, M0-AT16B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P10 · UI和视觉回归

**前置：** M0-P07, M0-P08, M0-P09。 **需求：** M0-R02, M0-R10, M0-R12。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `tests/browser/reader.spec.ts`
- `tests/visual/baselines/`
- `.agent/tmp/reports/m0-ui.md`

**步骤：**

1. 固定OS/浏览器/DPR与字体环境，对照参考页抽样首中末。
2. 测试320/390/1440px、放大字体、键盘焦点、长表和文章目录。
3. 新产生差异必须解释或修复，不自动更新approved截图。

**完成检查：** 无裁切与丢内容，阅读器变动仅在记录的允许区域。

**回归范围：** M0-AT02A, M0-AT02B, M0-AT10A, M0-AT10B, M0-AT12A, M0-AT12B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P11 · 文件安全、 Compose依赖与恢复演练

**前置：** M0-P08, M0-P09。 **需求：** M0-R13, M0-R14, M0-R16, M0-R18。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `ops/restore.md`
- `ops/dependencies.md`
- `tests/security/`
- `tests/compose/test_clean_host.py`

**步骤：**

1. 校验PDF动作不执行、资产路径/HTML转义、坏文件资源限额。
2. 同一Compose运维服务执行备份/恢复；测试DB与文件卷一致性、磁盘满/容器重启。
3. 证明宿主仅Docker+Compose且启动无依赖安装；核对镜像SBOM和licenses，禁打包容器字体文件到交接ZIP。

**完成检查：** 读取、导出、原件hash和pointer恢复正确，无外部服务栈先决条件。

**回归范围：** M0-AT13A, M0-AT13B, M0-AT14A, M0-AT14B, M0-AT16A, M0-AT16B, M0-AT18A, M0-AT18B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M0-P12 · M0退出评审与交接

**前置：** M0-P10, M0-P11。 **需求：** M0-R01, M0-R02, M0-R03, M0-R04, M0-R05, M0-R06, M0-R07, M0-R08, M0-R09, M0-R10, M0-R11, M0-R12, M0-R13, M0-R14, M0-R15, M0-R16, M0-R17, M0-R18。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `.agent/tmp/reports/M0-exit.md`
- `.agent/tmp/reports/M0-evidence.json`
- `docs/M1-handoff.md`

**步骤：**

1. 复跑所有M0 AT、无身份/仅PDF/API负例和Compose干净宿主测试。
2. 逐项登记退出证据；未执行标blocked，不用原型结果代替产品。
3. 生成M0发布镜像锁、SBOM、恢复说明和M1数据fixture。

**完成检查：** 所有M0-G gate有证据与批准；任何blocked均不能写完成。

**回归范围：** M0-AT01A, M0-AT01B, M0-AT02A, M0-AT02B, M0-AT03A, M0-AT03B, M0-AT04A, M0-AT04B, M0-AT05A, M0-AT05B, M0-AT06A, M0-AT06B, M0-AT07A, M0-AT07B, M0-AT08A, M0-AT08B, M0-AT09A, M0-AT09B, M0-AT10A, M0-AT10B, M0-AT11A, M0-AT11B, M0-AT12A, M0-AT12B, M0-AT13A, M0-AT13B, M0-AT14A, M0-AT14B, M0-AT15A, M0-AT15B, M0-AT16A, M0-AT16B, M0-AT17A, M0-AT17B, M0-AT18A, M0-AT18B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

## 4. 数据迁移、故障与发布检查

M0从空库初始化，不创建Users或Workspace；受控旧资料只seed一次。迁移先测试空卷/已有卷/中断后重启，应用与数据库schema版本不匹配时readiness失败。

每次正式候选发布需要所有本地依赖镜像就绪，Docker-only冷启成功、parser无运行期下载、单端口无反代、无身份页面/接口/数据表。环境缺失的Docker或真实模型测试标blocked，不能以YAML解析或FakeProvider代替。

## 5. 退出演示脚本

从空卷Compose启动，不创建账户；上传一份受控PDF并收藏，重建app后仍存在；原PDF字节不变。选择内置旧资料，离线导出且断网/禁JS可读。故障注入半写产物，当前版本不变；检测非PDF及文件路径攻击。

对每个gate提供：关联需求/AT、运行环境、实际结果、证据路径、已知限制、决定。角色标签是实施职责，不是产品账号。保持不支持功能的测试为明确拒绝，而非悄悄接受。

## 6. 编码 Agent 开始提示

```text
实施对照文库 v3 的 M0。先完整读取 00-product-baseline.md、shared/*、deployment/compose-contract.md、milestones/M0-spec.md 和本Plan；以最新五条用户约束为最高优先级。
检查实际代码和上阶段证据，先为 M0 的退出规格写自动化测试。按 contracts/implementation-backlog.json 的依赖领取工作包。
只允许PDF来源；不要增加双语/IR/HTML导入，不创建用户/工作区/角色/登录，不交付反代。只支持Docker Compose且运行依赖随镜像提供。
保留reader-v1样式和确定性出版；模型只能返回受限译文数据。失败/缺块不能假成功，外部付费调用先通过预算与外发确认。
原型功能不等于生产实现。所有报告区分已运行、未运行和环境阻塞；禁止将mock测试当真实模型/Compose验收。
完成一个工作包后保存代码、测试与证据再更新状态；跨包条件未满足不标完成。需要密钥或测试预算时报告精确阻塞，不跳过退出门。
```

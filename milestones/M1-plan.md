# M1 实施 Plan · 真实 PDF 解析、翻译与发布

**2026-09-08 超时配置补全。** 先建立 parser 时间推进和 PostgreSQL 入队/设置回归，再同步更新偏好 API、任务快照、spool、worker 等待和 parser 进程限制。浏览器验证分钟输入、保存持久化和过期版本草稿保留；最终 CPU Docker 镜像核验 Linux RLIMIT_CPU 与健康状态，记录生产配置保留证据。

**2026-09-08 P04/P05 表格补全。** 先建立 tests/unit/test_paddle_tables.py 和 tests/integration/test_paddle_table_publication.py，补齐受限 HTML 解码、共享 IR 空白格语义、Paddle 原图对照及来源差异检查。使用保存的真实官方推理输出验证适配，并在最终断网 CPU 镜像中运行受控表格 PDF；隔离 PostgreSQL 验证单元格 QA、发布与导出。新增证据独立记录，不重新标记历史验收门。

**2026-09-08 解析方案实施补充。** 先建立 profile 校验、设置 CAS 和排队冻结测试，再实现共享 profile 注册、离线模型锁及 CPU 适配。设置页与文档详情接入选择，浏览器验证保存/刷新/覆盖/过期版本与手机布局。使用隔离 PostgreSQL 和受控 PDF，在无网络无凭据的 Compose 容器内分别实测三方案，保存耗时与质量门结果；最后部署已验证镜像并对比公开配置绑定。

2026-09-08 P03–P05 增补：启用 CPU RapidOCR 和默认 CodeFormulaV2，补齐构建期锁定模型、ONNX Runtime CPU、来源结果映射与模型配置指纹，更新资源为 4 CPU / 8 GiB。以 tests/unit/test_docling_enrichments.py 检查识别文本、原始证据、失败裁图和扫描预检，再在断网容器执行真实 OCR/公式/代码推理。现有来源覆盖/出版回归仍需通过，本次证据独立保存，不重标历史退出门。

**2026-09-07 用户补充：取消译文强制人工核对/确认。** 段落确认、语义和术语问题核对均为可选；未确认或未处置的高风险提示不阻止封存、手动发布、自动发布或导出，提示及实际核对状态仍保留。缺段、数字/保护原子不一致、资源损坏等硬完整性问题和过期 QA 仍阻断。修改后只需重跑本地质量检查，不要求再次人工确认。此补充覆盖下文旧的强制核对表述；外发授权、未知请求风险处理及来源修正证据规则不变。

**版本3.0 · 对应[M1 Spec](M1-spec.md) · 所有工作包not_started**

## 1. 进入条件与实施策略

M0全部退出门完成，库/IR/Publisher/Compose迁移可复用；准备可控FakeProvider和有上限的真实调用测试预算。

沿用既有设计和领域模型，先写退出测试，再按依赖实施。前端原型只提供交互参考，不将localStorage、固定译文或手动推进移植为正式后端。

## 2. 工作包依赖总表

| 工作包 | 工作内容 | 前置依赖 | 工程人日估算 |
|---|---|---|---|
| M1-P01 | M0继承和接口能力基线 | M0-P12 | 1–2 |
| M1-P02 | 升级 PDF 接收与批量入库 | M1-P01 | 2–4 |
| M1-P03 | 离线Parser sandbox与制品 | M1-P01 | 2–3 |
| M1-P04 | PDF适配器和覆盖预检 | M1-P02, M1-P03 | 4–6 |
| M1-P05 | PDF图表、公式与失败页 | M1-P02, M1-P03 | 3–4 |
| M1-P06 | 预检UI与授权快照 | M1-P04, M1-P05 | 3–4 |
| M1-P07 | 翻译单元规划与精确缓存 | M1-P01, M1-P04 | 3–5 |
| M1-P08 | 真实Provider与模拟故障服务 | M1-P01, M1-P07 | 3–4 |
| M1-P09 | 预算账本与派发许可 | M1-P07, M1-P08 | 3–5 |
| M1-P10 | 可恢复翻译工作流 | M1-P06, M1-P08, M1-P09 | 4–6 |
| M1-P11 | 质量门禁与基本校对 | M1-P07, M1-P08, M1-P10 | 3–5 |
| M1-P12 | 任务中心与库的生产交互 | M1-P06, M1-P10, M1-P11 | 2–4 |
| M1-P13 | 删除与隐私审计 | M1-P10, M1-P11 | 2–4 |
| M1-P14 | 部署与故障演练 | M1-P12, M1-P13 | 2–4 |
| M1-P15 | 真实语料/模型与性能验收 | M1-P11, M1-P12, M1-P14 | 3–5 |
| M1-P16 | M1退出评审与M2交接 | M1-P15 | 1–2 |

顺序相加估算为41–67工程人日，是包括测试/修复的规划量级，不是AI运行时间、日历工期或承诺。可并行工作按依赖图安排；原文核对、真实Provider、镜像构建与环境限制会影响实际时间。需求中的职责可由同一维护者/编码Agent执行，不要求建立多人团队。

## 3. 逐包实施与完成检查

### M1-P01 · M0继承和接口能力基线

**前置：** M0-P12。 **需求：** M1-R02, M1-R07, M1-R08, M1-R26。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `docs/M1-capabilities.md`
- `packages/providers/protocol.py`
- `tests/contracts/`

**步骤：**

1. 复核M0退出和仅PDF接口；固定M1文件/语言矩阵与限制。
2. 确定实际OpenAI model_id和价格快照的部署填充方式；不写入默认密钥。
3. 提前冻结真实语料与模型预算授权，安排人工核对人员。

**完成检查：** 外部配置待填不阻止mock工程，但阻止M1真实验收。

**回归范围：** M1-AT02A, M1-AT02B, M1-AT07A, M1-AT07B, M1-AT08A, M1-AT08B, M1-AT26A, M1-AT26B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P02 · 升级 PDF 接收与批量入库

**前置：** M1-P01。 **需求：** M1-R01, M1-R02, M1-R21, M1-R24。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/api/uploads/`
- `packages/ingestion/`
- `tests/security/test_uploads.py`

**步骤：**

1. 复用M0上传、PDF检查和hash，不另造多格式管道。
2. 10份PDF独立import/job；服务端检验不可被浏览器accept绕过。
3. 按全库SHA提示复用或新文档；同名不同字节不覆盖。

**完成检查：** 重传/超限/伪装PDF/多文档独立失败测试通过。

**回归范围：** M1-AT01A, M1-AT01B, M1-AT02A, M1-AT02B, M1-AT21A, M1-AT21B, M1-AT24A, M1-AT24B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P03 · 离线Parser sandbox与制品

**前置：** M1-P01。 **需求：** M1-R03, M1-R25。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `workers/parser/`
- `images/parser.Dockerfile`
- `ops/egress-policy.md`
- `tests/security/test_parser_isolation.py`

**步骤：**

1. 锁定Docling依赖和本地权重hash，构建时获取、运行时断网。
2. 非特权进程、只读root、tmp/CPU/memory/timeout和文件descriptor限额。
3. Provider worker网络允许列表与parser零网络分离，禁止继承秘密。

**完成检查：** 网络探针、OOM/超时仅影响本任务，容器未挂Docker socket。

**回归范围：** M1-AT03A, M1-AT03B, M1-AT25A, M1-AT25B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P04 · PDF适配器和覆盖预检

**前置：** M1-P02, M1-P03。 **需求：** M1-R04, M1-R06。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/parsers/pdf_docling.py`
- `packages/ir/coverage.py`
- `tests/corpus/pdf/`

**步骤：**

1. 将读取顺序、页码、box、图表、公式保留表示映射v3。
2. 保存parser原输出及区域覆盖账本，区分页眉排除与未解正文。
3. 双栏/跨页/缺页/扫描页全部测试，检测到OCR需求明确停下。

**完成检查：** 冻结语料完整性达标；不以人工旧译文作为解析gold。

**回归范围：** M1-AT04A, M1-AT04B, M1-AT06A, M1-AT06B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P05 · PDF图表、公式与失败页

**前置：** M1-P02, M1-P03。 **需求：** M1-R02, M1-R05。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/parsers/pdf_assets.py`
- `packages/ir/pdf_coverage.py`
- `tests/corpus/pdf_assets/`

**步骤：**

1. 资源只来自PDF本地内容，记录页码bbox/哈希/裁剪变换。
2. 表格结构不可靠时保留原图并警告；正文页失败和扫描页仍硬阻断。
3. 禁止PDF动作/嵌入文件/外部资源加载；无HTML/文本/附件适配器。

**完成检查：** 图题/脚注/跨页资源可核验，外部探针零请求，失败正文不可原图绕过。

**回归范围：** M1-AT02A, M1-AT02B, M1-AT05A, M1-AT05B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P06 · 预检UI与授权快照

**前置：** M1-P04, M1-P05。 **需求：** M1-R06, M1-R07, M1-R19, M1-R21, M1-R24。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/web/features/preflight/`
- `apps/api/imports/confirm.py`
- `tests/browser/preflight.spec.ts`

**步骤：**

1. 展示真实页数/块数/问题/费用估算/来源预览。
2. 绑定source/范围/profile/privacy revision和用户确认；拒绝过期预检。
3. 实现最小页图定位与受限译文修正入口，适配后端草稿。

**完成检查：** 未解正文/未同意外部发送无法开始，批量失败不影响其他文档。

**回归范围：** M1-AT06A, M1-AT06B, M1-AT07A, M1-AT07B, M1-AT19A, M1-AT19B, M1-AT21A, M1-AT21B, M1-AT24A, M1-AT24B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P07 · 翻译单元规划与精确缓存

**前置：** M1-P01, M1-P04。 **需求：** M1-R09, M1-R10, M1-R11。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/translation/planner.py`
- `packages/translation/cache.py`
- `tests/unit/test_alignment.py`

**步骤：**

1. 基于AST拆分长块、批次token/输出上限、记录单元归属和重组规则。
2. 上下文和保护原子映射进入hash；按ID校验，输出顺序无关。
3. 精确缓存按全库上下文及版本敏感；跨文档ID重绑定复核，不复用近似译文。

**完成检查：** 极长段/保护原子/重排响应/重复ID/语境变化回归全过。

**回归范围：** M1-AT09A, M1-AT09B, M1-AT10A, M1-AT10B, M1-AT11A, M1-AT11B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P08 · 真实Provider与模拟故障服务

**前置：** M1-P01, M1-P07。 **需求：** M1-R08, M1-R10, M1-R13, M1-R14, M1-R22。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/providers/openai_responses.py`
- `packages/providers/gemini_interactions.py`
- `packages/providers/claude_messages.py`
- `tests/fakes/provider_server.py`
- `tests/contracts/test_provider.py`

**步骤：**

1. 实现request/response边界、结构化schema编译和finish/refusal处理。
2. 禁用SDK隐式重试与工具；OpenAI兼容和Gemini Interactions显式`store=false`，Claude Messages无此字段，不主动启用缓存写入或覆盖默认思考。记录可用requestID和计量信息，不宣传供应商零保留。
3. FakeProvider提供429/401/断流/迟到/已计费超时/截断/错ID脚本。
4. 按2026-09-06用户补充实现四协议设置与不可变配置绑定：协议确定provider与Bearer/native API-key头，`none`须明确；Claude `api_version`默认`2023-06-01`且仅原生Claude携带。保存零请求，配置缺失仍可落盘但不可派发，密钥不回显、无浏览器存储，按2026-09-07用户要求，切换接口类型填入默认endpoint/model ID，仍可手动覆盖；加载保留已保存值，切换不自动保存或调用模型，并要求旧key明确重新绑定。
5. 验证Gemini和Claude两个原生协议的响应model与配置严格一致（仅Gemini去除`models/`前缀），不猜模型别名。Gemini输出加思考、Claude输出已含思考；缓存写入等未定价用量及必需计数缺失/矛盾进入未知成本核对，不补零或自动重发。官方依据使用本轮[Gemini核对](../.agent/tmp/evidence/gemini-claude/gemini-official-contract-review.md)与[Claude独立核对](../.agent/tmp/evidence/gemini-claude/independent-claude-review.md)，适配器/本地HTTP/UI证据不能替代真实Provider认证。

**完成检查：** 此工作包只做Fake/契约验证；真实付费验收延至M1-P15并经过预算/授权/恢复就绪门。Fake和真实输出走同一验证器。

**回归范围：** M1-AT08A, M1-AT08B, M1-AT10A, M1-AT10B, M1-AT13A, M1-AT13B, M1-AT14A, M1-AT14B, M1-AT22A, M1-AT22B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P09 · 预算账本与派发许可

2026-09-07 设置页派发开关增补：通过 GET/PATCH `/settings/dispatch` 读写数据库状态，移除 Compose 的 `DISPATCH_DISABLED` 环境项；开启/暂停与 Provider 配置分别保存，复用 CAS、幂等、维护锁和未知费用确认。以 `tests/integration/test_dispatch_settings.py` 验证持久化、双标签竞争、旧版本拒绝、未知费用保留、在途结算和连接测试入队；`tests/browser/dispatch-settings.spec.ts` 验证实际设置交互与移动布局。新实例与恢复仍保持默认暂停，产品开关不授权 agent 执行真实模型调用。

2026-09-07 增补：实现可选 `cost_control_enabled`，新配置默认关闭，旧完整配置/快照缺字段维持开启。开启模式保留下述预算预留；关闭模式保留请求/用量/unknown 审计和并发许可，未定金额使用 null。新增 schema 11 只放宽两列为 nullable，不改旧值。四种外发入口分别验证可省略预算、外发确认仍必需、未知请求仍须风险确认。另验证输入/输出/正文单元默认 `32768/8192/2000`、当前值回读与只重置三项的 CAS/key 保持。

本增补的实际回归位于 `tests/unit/test_optional_cost_controls.py`、`tests/integration/test_optional_cost_ledger.py`、`tests/integration/test_optional_cost_workflow.py`；独立测试与失败证据另外保存。不得修改历史退出门结果，亦不得把取消产品中的金额控制当成取消真实 Provider 验收预算授权。

**前置：** M1-P07, M1-P08。 **需求：** M1-R14, M1-R15, M1-R16。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/billing/`
- `migrations/003_usage.sql`
- `tests/concurrency/test_budget.py`

**步骤：**

1. 实现price/profile不可变快照和整数金额，输入/输出/推理计费上界。
2. 原子job/instance额度检查与reservation，成功/失败/unknown结算幂等。
3. 控制epoch+dispatch permit，取消后无新授权；已授权请求按在途记账。

**完成检查：** 并发额度、未知成本、重复用量、取消竞态不会超授权逻辑上界或负余额。

**回归范围：** M1-AT14A, M1-AT14B, M1-AT15A, M1-AT15B, M1-AT16A, M1-AT16B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P10 · 可恢复翻译工作流

**前置：** M1-P06, M1-P08, M1-P09。 **需求：** M1-R12, M1-R13, M1-R14, M1-R16, M1-R17。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `workers/translation/`
- `packages/jobs/orchestrator.py`
- `tests/faults/test_translation_recovery.py`

**步骤：**

1. 扩展耐久任务为parse/translate/check/render/publish阶段，成功单元检查点。
2. 网络请求期间不持锁；租约过期已派发转unknown而非立即重发。
3. 实现有界重试、暂停恢复/取消、快照轮询和SSE。

**完成检查：** 在所有提交窗口杀进程后内容不丢、成功单元不重复发布/翻译。

**回归范围：** M1-AT12A, M1-AT12B, M1-AT13A, M1-AT13B, M1-AT14A, M1-AT14B, M1-AT16A, M1-AT16B, M1-AT17A, M1-AT17B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P11 · 质量门禁与基本校对

**前置：** M1-P07, M1-P08, M1-P10。 **需求：** M1-R18, M1-R19, M1-R20。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/quality/`
- `apps/web/features/review-basic/`
- `tests/corpus/translation/`

**步骤：**

1. 覆盖/原子/数字单位/资产/xref检查及高风险提示，明确语义局限。
2. 修正目标草稿后指纹变化使QA过期，不能修源绕过。
3. 实现manual/auto publication policy，始终复用M0 immutable publisher。

**完成检查：** 缺块/错数字/缺图不可发布；源定位修正后能完成真实闭环。

**回归范围：** M1-AT18A, M1-AT18B, M1-AT19A, M1-AT19B, M1-AT20A, M1-AT20B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P12 · 任务中心与库的生产交互

**前置：** M1-P06, M1-P10, M1-P11。 **需求：** M1-R17, M1-R20, M1-R21, M1-R24。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/web/features/tasks/`
- `apps/web/features/library/`
- `tests/browser/workflow.spec.ts`

**步骤：**

1. 真实进度、当前发表版+新任务分离、费用/未知请求提示。
2. 用户重连快照一致、参数变更重新授权、多文件独立管理。
3. 删除演示推进按钮和固定三段样本产物的生产引用。

**完成检查：** 关闭浏览器后任务继续，UI不能显示伪百分比与假完成。

**回归范围：** M1-AT17A, M1-AT17B, M1-AT20A, M1-AT20B, M1-AT21A, M1-AT21B, M1-AT24A, M1-AT24B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P13 · 删除与隐私审计

**前置：** M1-P10, M1-P11。 **需求：** M1-R22, M1-R23。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/privacy/`
- `ops/retention.md`
- `tests/security/test_delete_races.py`

**步骤：**

1. 实现archive/unpublish/delete三种语义及tombstone阻止复活。
2. 清理各内容缓存/制品/临时导出并检查引用；备份保留通知明确。
3. 统一日志脱敏/原始响应默认不存/诊断TTL；测试所有文件类型的路径与删除状态。

**完成检查：** 删除后迟到结果和索引不能复活文档，日志及导出不含密钥。

**回归范围：** M1-AT22A, M1-AT22B, M1-AT23A, M1-AT23B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P14 · 部署与故障演练

**前置：** M1-P12, M1-P13。 **需求：** M1-R03, M1-R12, M1-R14, M1-R15, M1-R23, M1-R25。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `ops/deploy.md`
- `ops/restore.md`
- `tests/faults/`
- `.agent/tmp/reports/M1-recovery.md`

**步骤：**

1. Compose生产配置、health/readiness和持久卷备份。
2. 演练Provider outage、DB断联、parser OOM、磁盘满、worker kill与恢复。
3. 恢复先禁止外部派发，unknown需要人工/供应商核对。

**完成检查：** 恢复后的发布指针、用量账本、任务状态一致。

**回归范围：** M1-AT03A, M1-AT03B, M1-AT12A, M1-AT12B, M1-AT14A, M1-AT14B, M1-AT15A, M1-AT15B, M1-AT23A, M1-AT23B, M1-AT25A, M1-AT25B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P15 · 真实语料/模型与性能验收

**前置：** M1-P11, M1-P12, M1-P14。 **需求：** M1-R04, M1-R05, M1-R07, M1-R08, M1-R18, M1-R26。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `.agent/tmp/reports/M1-corpus.md`
- `.agent/tmp/reports/M1-live-provider.md`
- `.agent/tmp/reports/M1-performance.md`

**步骤：**

1. 跑固定语料并核对页/块覆盖、图表和高风险语义。
2. 执行授权真实模型的en↔zh-Hans样本，保存用量和人工判定。
3. 性能分阶段测量，不把供应商时间纳入内部API SLO。

**完成检查：** 真实与模拟证据分离；未执行项标blocked，不填通过。

**回归范围：** M1-AT04A, M1-AT04B, M1-AT05A, M1-AT05B, M1-AT07A, M1-AT07B, M1-AT08A, M1-AT08B, M1-AT18A, M1-AT18B, M1-AT26A, M1-AT26B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M1-P16 · M1退出评审与M2交接

**前置：** M1-P15。 **需求：** M1-R01, M1-R02, M1-R03, M1-R04, M1-R05, M1-R06, M1-R07, M1-R08, M1-R09, M1-R10, M1-R11, M1-R12, M1-R13, M1-R14, M1-R15, M1-R16, M1-R17, M1-R18, M1-R19, M1-R20, M1-R21, M1-R22, M1-R23, M1-R24, M1-R25, M1-R26。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `.agent/tmp/reports/M1-exit.md`
- `.agent/tmp/reports/M1-evidence.json`
- `docs/M2-handoff.md`

**步骤：**

1. 复跑M0与M1全部AT、Compose clean-host、预算/unknown/取消/PDF安全硬门。
2. 审查生产是否仍依赖mock，确认能力/格式/语言限制对用户可见。
3. 导出迁移测试数据库与冻结契约供M2使用。

**完成检查：** M1-G全部通过且批准后进入M2。

**回归范围：** M1-AT01A, M1-AT01B, M1-AT02A, M1-AT02B, M1-AT03A, M1-AT03B, M1-AT04A, M1-AT04B, M1-AT05A, M1-AT05B, M1-AT06A, M1-AT06B, M1-AT07A, M1-AT07B, M1-AT08A, M1-AT08B, M1-AT09A, M1-AT09B, M1-AT10A, M1-AT10B, M1-AT11A, M1-AT11B, M1-AT12A, M1-AT12B, M1-AT13A, M1-AT13B, M1-AT14A, M1-AT14B, M1-AT15A, M1-AT15B, M1-AT16A, M1-AT16B, M1-AT17A, M1-AT17B, M1-AT18A, M1-AT18B, M1-AT19A, M1-AT19B, M1-AT20A, M1-AT20B, M1-AT21A, M1-AT21B, M1-AT22A, M1-AT22B, M1-AT23A, M1-AT23B, M1-AT24A, M1-AT24B, M1-AT25A, M1-AT25B, M1-AT26A, M1-AT26B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

## 4. 数据迁移、故障与发布检查

M1先在上阶段快照上演练升级：保留原件/封存IR/产物hash，增加表而不改写历史版本。恢复先暂停外发，outcome_unknown不能当pending重发。

每次正式候选发布需要所有本地依赖镜像就绪，Docker-only冷启成功、parser无运行期下载、单端口无反代、无身份页面/接口/数据表。环境缺失的Docker或真实模型测试标blocked，不能以YAML解析或FakeProvider代替。

## 5. 退出演示脚本

上传真实双栏PDF，确认全文覆盖与外发成本；使用已批准真实Provider完成小样本。中途重启worker和关闭浏览器，成功块不重复翻译；模拟已收费超时进入unknown且不自动重试；64→32错误被阻断、修复后生成新静态版。

对每个gate提供：关联需求/AT、运行环境、实际结果、证据路径、已知限制、决定。角色标签是实施职责，不是产品账号。保持不支持功能的测试为明确拒绝，而非悄悄接受。

## 6. 编码 Agent 开始提示

```text
实施对照文库 v3 的 M1。先完整读取 00-product-baseline.md、shared/*、deployment/compose-contract.md、milestones/M1-spec.md 和本Plan；以最新五条用户约束为最高优先级。
检查实际代码和上阶段证据，先为 M1 的退出规格写自动化测试。按 contracts/implementation-backlog.json 的依赖领取工作包。
只允许PDF来源；不要增加双语/IR/HTML导入，不创建用户/工作区/角色/登录，不交付反代。只支持Docker Compose且运行依赖随镜像提供。
保留reader-v1样式和确定性出版；模型只能返回受限译文数据。失败/缺块不能假成功，外部付费调用先通过预算与外发确认。
原型功能不等于生产实现。所有报告区分已运行、未运行和环境阻塞；禁止将mock测试当真实模型/Compose验收。
完成一个工作包后保存代码、测试与证据再更新状态；跨包条件未满足不标完成。需要密钥或测试预算时报告精确阻塞，不跳过退出门。
```

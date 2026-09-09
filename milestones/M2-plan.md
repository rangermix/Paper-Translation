# M2 实施 Plan · 个人校对、多语言和版本管理

**2026-09-08 用户补充：质量问题与段落定位。** 校对工作台将阻断与风险提示分组，并提供全部/仅阻断/仅风险筛选及对应段落跳转。阻断段落明确标为必须处理，不能显示可选核对；人工确认不能代替修正和重验。段落可独立折叠，非阻断段落默认折叠，跳转自动展开，折叠和筛选必须保留未保存文字与修改理由。数字检查仅作机械等价比较，不改写原文或已保存译文：统一千分位、PDF提取的小数间隔、数位宽度和明确的中英文数量单位（如 11 billion = 110 亿、3 billion = 30 亿）；仍检查精确数值、正负号、百分号和出现次数，并展示差异证据。规则版本改变使旧 QA 过期，重验后才可封存。

**2026-09-07 用户补充：取消译文强制人工核对/确认。** 段落确认、语义和术语问题核对均为可选；未确认或未处置的高风险提示不阻止封存、手动发布、自动发布或导出，提示及实际核对状态仍保留。缺段、数字/保护原子不一致、资源损坏等硬完整性问题和过期 QA 仍阻断。修改后只需重跑本地质量检查，不要求再次人工确认。此补充覆盖下文旧的强制核对表述；外发授权、未知请求风险处理及来源修正证据规则不变。

**版本3.0 · 对应[M2 Spec](M2-spec.md) · 所有工作包not_started**

## 1. 进入条件与实施策略

M0/M1全部退出证据有效；使用带未完成任务、旧artifact和费用预留的M1数据库快照测试升级；没有新增多人协作范围。

沿用既有设计和领域模型，先写退出测试，再按依赖实施。前端原型只提供交互参考，不将localStorage、固定译文或手动推进移植为正式后端。

## 2. 工作包依赖总表

| 工作包 | 工作内容 | 前置依赖 | 工程人日估算 |
|---|---|---|---|
| M2-P01 | 迁移设计与M1数据基线 | M1-P16 | 2–3 |
| M2-P02 | PDF来源对照与来源修订 | M2-P01 | 4–6 |
| M2-P03 | 审校草稿与冲突控制 | M2-P01 | 3–5 |
| M2-P04 | 术语表与影响分析 | M2-P01 | 3–4 |
| M2-P05 | 局部重译候选与接受 | M2-P02, M2-P03, M2-P04 | 3–5 |
| M2-P06 | 质量中心与辅助评审 | M2-P03, M2-P04 | 3–5 |
| M2-P07 | 多语言edition与能力验收 | M2-P01, M2-P04, M2-P05 | 3–5 |
| M2-P08 | 发布历史与回滚 | M2-P03, M2-P06, M2-P07 | 2–4 |
| M2-P09 | 模板注册与批量零模型重建 | M2-P08 | 2–3 |
| M2-P10 | 个人翻译记忆与删除语义 | M2-P03, M2-P04, M2-P05 | 2–4 |
| M2-P11 | 全文检索和阅读定位 | M2-P08 | 3–4 |
| M2-P12 | 版本导出与全生命周期 | M2-P09, M2-P10, M2-P11 | 3–4 |
| M2-P13 | 端到端/性能/安全评审 | M2-P02, M2-P05, M2-P06, M2-P07, M2-P12 | 3–5 |
| M2-P14 | M2退出门与交付 | M2-P13 | 1–2 |

顺序相加估算为37–59工程人日，是包括测试/修复的规划量级，不是AI运行时间、日历工期或承诺。可并行工作按依赖图安排；原文核对、真实Provider、镜像构建与环境限制会影响实际时间。需求中的职责可由同一维护者/编码Agent执行，不要求建立多人团队。

## 3. 逐包实施与完成检查

### M2-P01 · 迁移设计与M1数据基线

**前置：** M1-P16。 **需求：** M2-R02, M2-R09, M2-R20。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `migrations/004_editorial.sql`
- `docs/M2-migration.md`
- `tests/fixtures/m1_snapshot/`

**步骤：**

1. 清点M1 source/draft/artifact/usage与未完成作业。
2. 为segment history、candidate、glossary、TM、index设计增量表，复用既有版本键。
3. 先扩展后切换，定义回滚与读取旧artifact不变。

**完成检查：** M1快照可升级/恢复，未执行Provider任务不会自动重发。

**回归范围：** M2-AT02A, M2-AT02B, M2-AT09A, M2-AT09B, M2-AT20A, M2-AT20B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P02 · PDF来源对照与来源修订

**前置：** M2-P01。 **需求：** M2-R01, M2-R11, M2-R12。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/web/features/source-review/`
- `packages/source_revisions/`
- `tests/browser/pdf-locator.spec.ts`

**步骤：**

1. 实现本地PDF页图、高亮、旋转cropbox和跨页locator。
2. 有原件证据的拆并/顺序/机械提取修正生成新来源修订。
3. explicit映射exact/moved/changed/split/merged与上下文失效，不支持DOM/TXT locator。

**完成检查：** 来源坐标真实、旧快照不变，无虚构证据。

**回归范围：** M2-AT01A, M2-AT01B, M2-AT11A, M2-AT11B, M2-AT12A, M2-AT12B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P03 · 审校草稿与冲突控制

**前置：** M2-P01。 **需求：** M2-R02, M2-R06, M2-R13, M2-R14。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/web/features/editor/`
- `packages/editorial/drafts.py`
- `tests/concurrency/test_edit_conflicts.py`

**步骤：**

1. 逐段版本、If-Match、撤销为新版本，明确保存与人工确认不同。
2. 审校记录绑定source/target版本，任何修改使对应确认失效。
3. 版本diff区分源与译变化，冲突保留两方供手工处理。

**完成检查：** 多标签页/迟到自动结果不能覆盖手工编辑。

**回归范围：** M2-AT02A, M2-AT02B, M2-AT06A, M2-AT06B, M2-AT13A, M2-AT13B, M2-AT14A, M2-AT14B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P04 · 术语表与影响分析

**前置：** M2-P01。 **需求：** M2-R03, M2-R04。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/glossaries/`
- `apps/web/features/glossary/`
- `tests/unit/test_term_matching.py`

**步骤：**

1. 固定源/目标语言、词项变体、must/preferred/forbidden语义与优先级。
2. 产生不可变glossary revision，匹配规则包含英文边界和CJK子串。
3. 影响预览只挑选相关块，人工锁定块仅提示。

**完成检查：** 冲突可定位；术语更新不静默重写旧版本。

**回归范围：** M2-AT03A, M2-AT03B, M2-AT04A, M2-AT04B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P05 · 局部重译候选与接受

**前置：** M2-P02, M2-P03, M2-P04。 **需求：** M2-R05, M2-R06, M2-R12, M2-R14。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/editorial/candidates.py`
- `apps/web/features/retranslation/`
- `tests/concurrency/test_candidate_merge.py`

**步骤：**

1. 选择块/章节生成候选，不直接更改草稿，复用M1预算/Provider/任务。
2. 接受检查base target/source/context/glossary版本，保持reviewed块锁。
3. 源变化重用必须有映射证据，changed需重译。

**完成检查：** 100段重译2段时其余98段字节和审校状态不动。

**回归范围：** M2-AT05A, M2-AT05B, M2-AT06A, M2-AT06B, M2-AT12A, M2-AT12B, M2-AT14A, M2-AT14B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P06 · 质量中心与辅助评审

**前置：** M2-P03, M2-P04。 **需求：** M2-R07, M2-R08。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/quality/issues.py`
- `packages/review_provider/`
- `apps/web/features/quality/`

**步骤：**

1. issues绑定QA指纹和证据，硬阻断无ignore，warnings有理由接受。
2. 可选独立语义评审采用同一外发确认和预算管线，不直接写译文。
3. 评审失败/未跑明确显示，检验否定/限定词/比较关系fixture。

**完成检查：** 改变草稿后QA必过期；模型评分不会变人工通过。

**回归范围：** M2-AT07A, M2-AT07B, M2-AT08A, M2-AT08B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P07 · 多语言edition与能力验收

**前置：** M2-P01, M2-P04, M2-P05。 **需求：** M2-R09, M2-R10。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `apps/web/features/editions/`
- `packages/locales/`
- `.agent/tmp/reports/M2-language-matrix.md`

**步骤：**

1. 规范化locale保留脚本差异，新增版复用source。
2. 按locale绑定current artifact和任务，所有语言组合均可直接选择，名称使用各自语言。
3. 对ja/de/zh-Hant准备人工审校样本，未知质量不保证。

**完成检查：** 新增日文版不重新解析或覆盖中文；任意语言不受能力矩阵限制，仍执行普通外发确认与质量检查。

**回归范围：** M2-AT09A, M2-AT09B, M2-AT10A, M2-AT10B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P08 · 发布历史与回滚

**前置：** M2-P03, M2-P06, M2-P07。 **需求：** M2-R13, M2-R15。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/publisher/history.py`
- `apps/web/features/history/`
- `tests/concurrency/test_publish_rollback.py`

**步骤：**

1. 封存特定draft/QA/template并使用单调generation CAS。
2. 实现版本对比、同locale完整artifact回滚和事件历史。
3. 增加ABA/回滚与删除并发/QA过期/跨语言负测试。

**完成检查：** A→B→A回滚不复用旧generation，不修改A/B任何字节。

**回归范围：** M2-AT13A, M2-AT13B, M2-AT15A, M2-AT15B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P09 · 模板注册与批量零模型重建

**前置：** M2-P08。 **需求：** M2-R16。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/templates/registry.py`
- `packages/publisher/rebuild.py`
- `tests/integration/test_zero_model_rebuild.py`

**步骤：**

1. 模板安全审查与内容能力声明，CSS hash版本化。
2. 预览单篇再队列批量；每篇独立CAS/错误，不隐式切换全部。
3. 加Provider调用计数拦截和旧制品hash断言。

**完成检查：** 仅改模板20篇重建的模型调用严格为零。

**回归范围：** M2-AT16A, M2-AT16B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P10 · 个人翻译记忆与删除语义

**前置：** M2-P03, M2-P04, M2-P05。 **需求：** M2-R17。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/translation_memory/`
- `apps/web/features/memory/`
- `tests/integration/test_memory_lifecycle.py`

**步骤：**

1. 人工核对结果显式另存，记录来源/语境/审校证据；无用户字段。
2. 近似推荐显示差异而非自动发布；机器精确缓存独立。
3. 默认随来源删除，明确选择独立保留的个人条目例外并可再次删除。

**完成检查：** 语境变化不误复用，删除及旧候选不能复活内容。

**回归范围：** M2-AT17A, M2-AT17B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P11 · 全文检索和阅读定位

**前置：** M2-P08。 **需求：** M2-R18。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/search/`
- `apps/web/features/search/`
- `tests/security/test_search_generations.py`

**步骤：**

1. 索引仅当前已发布源/译块，按字面子串语义实现CJK与英文。
2. 发布outbox驱动generation索引，返回前核对当前指针/删除状态；无ACL或用户条件。
3. 命中锚定artifact+block，阅读进度按版本存储和可解释迁移。

**完成检查：** 没有过期/删除内容泄露，读者不会被带到另一个语义段落。

**回归范围：** M2-AT18A, M2-AT18B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P12 · 版本导出与全生命周期

**前置：** M2-P09, M2-P10, M2-P11。 **需求：** M2-R19, M2-R20。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `packages/exporter/project_backup.py`
- `ops/M2-retention.md`
- `tests/integration/test_m2_restore.py`

**步骤：**

1. 精确artifact导出与Compose实例备份分开，验证manifest；无Web ZIP/JSON恢复入口。
2. 扩展tombstone/GC到candidate/glossary引用/TM/index/export。
3. 升级/恢复与删除竞态再演练，处理未知账单。

**完成检查：** 旧版可离线读；被删文档在线所有派生资源不可访问。

**回归范围：** M2-AT19A, M2-AT19B, M2-AT20A, M2-AT20B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P13 · 端到端/性能/安全评审

**前置：** M2-P02, M2-P05, M2-P06, M2-P07, M2-P12。 **需求：** M2-R01, M2-R05, M2-R07, M2-R08, M2-R09, M2-R14, M2-R15, M2-R16, M2-R18, M2-R20, M2-R21。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `.agent/tmp/reports/M2-editorial-e2e.md`
- `.agent/tmp/reports/M2-security.md`
- `.agent/tmp/reports/M2-performance.md`

**步骤：**

1. 执行真实源修正→局部重译→人工确认→多语言→模板重建→回滚→导出。
2. 故障注入及跨文档引用、过期索引、删除、多标签页冲突回归；无跨账户测试。
3. 独立核查质量评分和状态没有伪通过，补充桌面/手机视觉证据。

**完成检查：** 全部M0/M1/M2回归都有证据，不以演示替代真实流水。

**回归范围：** M2-AT01A, M2-AT01B, M2-AT05A, M2-AT05B, M2-AT07A, M2-AT07B, M2-AT08A, M2-AT08B, M2-AT09A, M2-AT09B, M2-AT14A, M2-AT14B, M2-AT15A, M2-AT15B, M2-AT16A, M2-AT16B, M2-AT18A, M2-AT18B, M2-AT20A, M2-AT20B, M2-AT21A, M2-AT21B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

### M2-P14 · M2退出门与交付

**前置：** M2-P13。 **需求：** M2-R01, M2-R02, M2-R03, M2-R04, M2-R05, M2-R06, M2-R07, M2-R08, M2-R09, M2-R10, M2-R11, M2-R12, M2-R13, M2-R14, M2-R15, M2-R16, M2-R17, M2-R18, M2-R19, M2-R20, M2-R21。

**产出代码/文件位置（待实现，不是本包已提供模块）：**

- `.agent/tmp/reports/M2-exit.md`
- `.agent/tmp/reports/M2-evidence.json`
- `ops/release.md`

**步骤：**

1. 对照每条需求、AT、任务和gate检查无遗漏。
2. 确认OCR/其他格式/登录/团队/反代部署没有重新进入范围。
3. 冻结release manifest和恢复手册，说明限制与后续独立决策。

**完成检查：** 所有硬门通过且review sign-off可追溯，未执行一律不冒充完成。

**回归范围：** M2-AT01A, M2-AT01B, M2-AT02A, M2-AT02B, M2-AT03A, M2-AT03B, M2-AT04A, M2-AT04B, M2-AT05A, M2-AT05B, M2-AT06A, M2-AT06B, M2-AT07A, M2-AT07B, M2-AT08A, M2-AT08B, M2-AT09A, M2-AT09B, M2-AT10A, M2-AT10B, M2-AT11A, M2-AT11B, M2-AT12A, M2-AT12B, M2-AT13A, M2-AT13B, M2-AT14A, M2-AT14B, M2-AT15A, M2-AT15B, M2-AT16A, M2-AT16B, M2-AT17A, M2-AT17B, M2-AT18A, M2-AT18B, M2-AT19A, M2-AT19B, M2-AT20A, M2-AT20B, M2-AT21A, M2-AT21B。保存命令、commit、测试输出、必要截图/日志与失败记录；成功声明必须关联证据路径。

## 4. 数据迁移、故障与发布检查

M2先在上阶段快照上演练升级：保留原件/封存IR/产物hash，增加表而不改写历史版本。恢复先暂停外发，outcome_unknown不能当pending重发。

每次正式候选发布需要所有本地依赖镜像就绪，Docker-only冷启成功、parser无运行期下载、单端口无反代、无身份页面/接口/数据表。环境缺失的Docker或真实模型测试标blocked，不能以YAML解析或FakeProvider代替。

## 5. 退出演示脚本

在100段fixture仅重译2段，其余98段内容/确认记录不变；在候选运行时修改一段触发冲突。增加日语版不重解析；20篇换模板Provider调用0；A→B→A回滚generation递增；旧版离线导出和M1→M2恢复通过。

对每个gate提供：关联需求/AT、运行环境、实际结果、证据路径、已知限制、决定。角色标签是实施职责，不是产品账号。保持不支持功能的测试为明确拒绝，而非悄悄接受。

## 6. 编码 Agent 开始提示

```text
实施对照文库 v3 的 M2。先完整读取 00-product-baseline.md、shared/*、deployment/compose-contract.md、milestones/M2-spec.md 和本Plan；以最新五条用户约束为最高优先级。
检查实际代码和上阶段证据，先为 M2 的退出规格写自动化测试。按 contracts/implementation-backlog.json 的依赖领取工作包。
只允许PDF来源；不要增加双语/IR/HTML导入，不创建用户/工作区/角色/登录，不交付反代。只支持Docker Compose且运行依赖随镜像提供。
保留reader-v1样式和确定性出版；模型只能返回受限译文数据。失败/缺块不能假成功，外部付费调用先通过预算与外发确认。
原型功能不等于生产实现。所有报告区分已运行、未运行和环境阻塞；禁止将mock测试当真实模型/Compose验收。
完成一个工作包后保存代码、测试与证据再更新状态；跨包条件未满足不标完成。需要密钥或测试预算时报告精确阻塞，不跳过退出门。
```

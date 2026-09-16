# M0 产品 Spec · PDF 原件库与静态出版底座

> 原 M0–M2 阶段设计与验收追踪。当前行为以[产品基线](../00-product-baseline.md)及后续专项契约为准；旧质量阻断、实验语言、强制预算、CPU-only 等被覆盖的条款不再作为当前产品要求。保留场景编号和历史证据，不据此宣称当前 release 通过。

**版本3.0 · 个人PDF版 · 待实现**

## 1. 产品目标与前提

把PDF安全保存到单实例个人库，提供原件阅读与管理，并固定后续所有译文的静态出版契约。M0不调用翻译模型；出版能力用内部IR夹具和已知旧版种子证明。

**进入条件：** 本v3约束和参考样式已经确认；能够在Docker+Compose干净环境运行测试；不得从旧原型的配对文本入口开始实现。

本阶段只有一个使用者，不引入用户实体。规格依赖[产品基线](../00-product-baseline.md)、[共享数据契约](../shared/architecture-data.md)、[工作流和质量](../shared/workflow-quality-security.md)、[API](../shared/api-contract.md)、[Compose契约](../deployment/compose-contract.md)。

## 2. 核心流程与明确排除

上传PDF → 隔离有效性检查 → source_only原件条目 → 标签/收藏/预览；另外由受控内置种子/内部fixture → 校验 → 渲染 → 静态发布 → 导出。

**排除范围：** 没有自动翻译、完整PDF语义解析、双语/JSON/HTML输入、账户/权限或反代。M0的新PDF不能被伪造译文标记为published。

## 3. 页面及状态规格

| 页面 | 必需信息与操作 | 边界 |
|---|---|---|
| 文档库 | 题名、原PDF、source_only/既有发布版、标签和收藏 | 不展示所有者、团队、访问权限 |
| PDF上传 | 最多10个文件、大小、接收状态和明确错误 | 仅PDF；机器翻译尚未实现时必须可见 |
| 原件详情 | 真实页数、SHA、原文件、查重候选 | 浏览器刷新不丢服务端数据 |
| 静态阅读 | 原文后接译文、目录、字号、主题、PDF入口 | 内容在HTML中，无JS也可读 |
| 设置/运维 | 个人偏好、系统就绪、Compose说明 | 无登录设置、认证选项或反代配置 |

输入错误留在当前页并保留有效选择；耗时操作返回job而不是锁住界面。操作完成显示真实已完成范围，失败给对应资源/错误码；不以人工按“继续演示”的结果作为正式成功。

## 4. 编号需求与验收场景

以下每个MUST是退出门的一部分；AT均为待执行产品测试，不是本包自检结果。

### M0-R01 · 仅 PDF 的产品入口

**MUST：** 用户创建来源只能上传 application/pdf 字节，服务器签名和受限 PDF 解码共同验证；不提供 URL、HTML、TXT、Markdown、DOCX、EPUB、ZIP、双语粘贴或 IR 导入 API/UI。原文中的普通引用超链接可保留但不自动获取。IR 样例和既有阅读页只作受控内置资料。

**M0-AT01A** （自动化，planned）

Given 首次打开界面，When 检查上传页和创建来源接口，Then 仅一个 PDF 入口，只有 PDF 文件能进入接收/验证流程。

**M0-AT01B** （自动化，planned）

Given URL 字段、bilingual/text 来源、附件数组、HTML/DOCX/JSON 或伪装 PDF，When 直接请求导入，Then 415/422；不存在隐藏兼容路由。

### M0-R02 · 冻结现有阅读样式

**MUST：** reader-v1.css 字节和 SHA-256 必须等于参考清单；阅读正文沿用原纸色、英蓝／译棕侧线、衬线、目录和工具条。为多语言使用原文／译文标签，保留现有 CSS 类兼容。管理 UI 可以迭代但不能改变既有制品。

**M0-AT02A** （自动化＋人工/环境验证，planned）

Given 两篇 legacy 基准和固定浏览器环境，When 打开桌面／手机截图，Then CSS 哈希相等、正文配对顺序相等，视觉差异在明确的导航允许区之外须审核。

**M0-AT02B** （自动化＋人工/环境验证，planned）

Given 开发者悄悄修改 reader-v1.css 一个颜色值，When 跑模板验证，Then 失败；不允许自动接受新快照。

### M0-R03 · PDF 原件入库与阶段边界

**MUST：** M0 接收并流式保存 PDF，经隔离 inspector 进行有效性/加密/页数检查、SHA-256 查重后建立 source asset 与文档；能预览/下载原件、编辑题名/标签、收藏/归档。M0 不执行机器翻译和语义版面解析，新上传文件显示“原件已保存，翻译在 M1 启用”，不生成伪译文。内部 fixture 验证静态出版。

**M0-AT03A** （自动化，planned）

Given 有效未加密 PDF，When 上传完成，Then 原始字节hash不变、真实页数可见，刷新/服务重启后文档仍存在且状态为source_only。

**M0-AT03B** （自动化，planned）

Given M0新上传PDF点击翻译，Then 功能尚未实现时明确不可用；不得把内置示例文本挂在该文件名下冒充译文。

### M0-R04 · 自有 RenderInput v3 与内部契约

**MUST：** IR v3 仅 PDF 来源，无实例/用户/角色字段。source_revision.kind 固定 pdf_upload；每个源码 locator 都是 PDF 页码及 top-left-points bbox。保留全部块类型与不可变源/译快照。JSON Schema 是语法层，语义校验独立实现；IR 仅内部处理/备份格式，不作为新增文档入口。

**M0-AT04A** （自动化，planned）

Given 内部全结构PDF来源fixture，When Schema和语义校验，Then 通过并能渲染；普通客户端只能上传PDF，不能POST该IR建文档。

**M0-AT04B** （自动化，planned）

Given unknown field、非PDF来源locator、重复block、环引用或workspace_id，Then 严格拒绝，不自动忽略兼容。

### M0-R05 · 原件与机械清理可追溯

**MUST：** 原 PDF 字节与哈希永久绑定来源资产；原解析输出、raw_text、normalized_text与编辑映射分开保存。只允许有证据的连字/断行等机械恢复；M0样例由人工核实，M1由解析器产生。源文修正产生新 SourceRevision，不通过译文编辑改原文。

**M0-AT05A** （自动化，planned）

Given 原PDF中跨行单词和连字，When 记录机械清理，Then 可回到真实页图与raw区间，原资产hash始终不变。

**M0-AT05B** （自动化，planned）

Given 模型尝试重写英文或将source字段放入翻译响应，Then 响应被拒，原件及来源快照未修改。

### M0-R06 · 一对一阅读与保留策略

**MUST：** 每个必译内容块有且仅有一个可用结果；标题在 hero 中只出现一次；图／表内部子块由 owner_id 管理，不再出现在根阅读流中。代码、公式、参考文献和原图可按明确策略 retained，不可把缺译正文标成保留。

**M0-AT06A** （自动化，planned）

Given 1 个标题、2 段、1 张 2×2 表、1 个图题和1段参考文献，When 渲染，Then 每个语义对象只渲染一次，所有必译文本紧邻译文。

**M0-AT06B** （自动化，planned）

Given 正文缺失结果、结果引用未知块或将正文伪标 retained，When 校验，Then 阻断发布。

### M0-R07 · 结构渲染完整而不猜测

**MUST：** M0 renderer 必须支持 Schema 中全部已启用种类：标题、段落、列表、代码、数学、图片、图题、表格、表格单元、脚注、参考文献。长表横向滚动；不可靠公式只能显示已提供的原图／原式并声明。解析支持不等于渲染支持。

**M0-AT07A** （自动化，planned）

Given 包含合并单元格、脚注回链、原图和数学表示的人工 IR，When 生成，Then 所有资源及锚点有效、单元格覆盖不重叠。

**M0-AT07B** （自动化，planned）

Given 未实现 block kind 或无可靠公式表示，When 构建，Then 明确失败／待处理，不静默跳过、不编造 LaTeX。

### M0-R08 · 确定性静态渲染

**MUST：** 渲染仅接受冻结 SourceRevision、TranslationRevision、模板与构建配置，绝不调用 LLM。固定输入和构建环境产生相同正文及资源字节；构建时间放 manifest、不进入正文。ZIP 文件时间和排序规范化，确定性比较排除审计时间。

**M0-AT08A** （自动化，planned）

Given 同一冻结输入，在干净环境连续构建两次，Then index.html、CSS、JS、资产及 content_digest 相同。

**M0-AT08B** （自动化，planned）

Given 断开全部网络并关闭模型配置，When 构建已有双语，Then 仍成功；任何网络依赖测试判失败。

### M0-R09 · 三种独立消费方式

**MUST：** 在线静态页面（由app做请求与路径安全检查）、离线目录 ZIP、单文件 HTML 均包含完整正文。单文件内嵌 CSS/JS/图片；PDF 默认不嵌入，没有附带 PDF 时不显示必坏按钮。离线导出不包含凭据、私有管理 URL 或正文 fetch。

**M0-AT09A** （自动化＋人工/环境验证，planned）

Given 已发布 fixture，When 导出 ZIP 和单 HTML 后在断网 file:// 下打开，Then 正文、图表、样式均可读且没有自动外网请求。

**M0-AT09B** （自动化＋人工/环境验证，planned）

Given include_source=false 或来源原件不可提供，When 导出，Then 原始 PDF 控件隐藏／说明另附，不出现 404 链接。

### M0-R10 · 无脚本可读与可访问控件

**MUST：** 禁用 JavaScript 默认显示全部双语内容；设置脚本只切换显示、字号、主题、阅读位置。键盘可访问目录与控件；320px 视口除表格／代码内部外不横向溢出；存储不可用时降级提示但正文仍可读。

**M0-AT10A** （自动化＋人工/环境验证，planned）

Given JS 被禁用或 localStorage 抛错，When 阅读文章，Then 原文、译文、图表和链接仍存在，不能被默认 CSS 隐藏。

**M0-AT10B** （自动化＋人工/环境验证，planned）

Given 长标题、代码与移动视口，When tab 导航和放大字号，Then 无被遮挡主操作，焦点可见，正文不被裁切。

### M0-R11 · 两篇旧阅读页的受控保留

**MUST：** 已提供两篇论文作为可选内置示例包；迁移只接受release清单已知hash，通过compose内CLI执行，不提供任意HTML上传。保留原阅读样式、原文曾整理的legacy说明及PDF入口，不伪造逐块来源、精确译文或人工审校状态。

**M0-AT11A** （自动化，planned）

Given 内置示例包与匹配manifest，When 运行seed-legacy两次，Then 每篇只建立一次旧版记录，正文/CSS与参考一致。

**M0-AT11B** （自动化，planned）

Given 未知HTML/hash变更或请求通过普通API上传旧网页，Then 拒绝；无精确bbox只显示原PDF入口。

### M0-R12 · 单实例持久文档库

**MUST：** PostgreSQL保存单份个人文档库及目录状态；文件卷保存原件和不可变产物。文档不关联 User、Workspace、Tenant、Owner 或 ACL；收藏/偏好为全实例数据。浏览器缓存不能成为服务端事实源。

**M0-AT12A** （自动化，planned）

Given 上传PDF并收藏/标记标签，When 换浏览器访问同实例或重建app容器，Then 读取相同库状态，无需登录。

**M0-AT12B** （自动化，planned）

Given 清空浏览器storage，Then 文档未丢失；数据库迁移与API不得要求虚拟用户/默认workspace。

### M0-R13 · 无身份系统与直接访问边界

**MUST：** 没有登录/注册/用户/组织/角色/会话/分享权限/鉴权网关。任何可访问实例端口的客户端具有同等完整能力。默认只绑定127.0.0.1:8080，应用直接服务UI/API/已发布静态文件；生产保留Host/Origin与不跨域请求保护、内容转义和安全路径检查，这些不是登录。反代、TLS、远程接入由用户自行处理，不交付配置。

**M0-AT13A** （自动化，planned）

Given 空数据库Compose首次启动，When 打开应用及静态阅读页，Then 直接可用，没有owner创建、账号cookie、auth header或重定向登录。

**M0-AT13B** （自动化，planned）

Given 未允许Host/跨站写请求或路径穿越，Then 请求安全策略拒绝；不存在login/workspace/role路由，db端口不对主机发布。

### M0-R14 · 幂等构建与原子发布底座

**MUST：** 渲染／导出作为持久任务运行；短事务领取租约与 fencing token，提交检查 token。先生成完整不可变 artifact，再用 edition generation CAS 更新当前指针。进程崩溃最多留下未引用文件。

**M0-AT14A** （自动化，planned）

Given 构建后写指针前杀死 worker，When 恢复并重试，Then 旧指针有效且至多一个新当前制品；不出现半页。

**M0-AT14B** （自动化，planned）

Given 过期 worker 和新 worker 同时提交，Then 过期写被拒；两个相同期望 generation 的发布仅一个成功。

### M0-R15 · 未完成不伪装完成

**MUST：** 草稿可保存和显式导出，但须醒目标识 DRAFT／缺失块数；缺块、未知引用、资产缺失和哈希异常不可被人工“忽略”后正常发布。当前发布指针只引用 verified artifact。

**M0-AT15A** （自动化，planned）

Given 缺译草稿，When 用户选择“导出未完成草稿”并确认，Then 输出含具体缺失标记且不进入已发布列表。

**M0-AT15B** （自动化，planned）

Given 绕过前端直接请求 publish，When 有硬性问题，Then 409 QUALITY_BLOCKED，零 publication event。

### M0-R16 · 安全内容和本地资产

**MUST：** 只从受限 IR 生成 DOM；文本转义，不接受模型／导入者 raw HTML、JS、任意存储路径。图片按允许类型解码复核；CSP 限制脚本和网络；所有资产绑定本实例；已知样式模板允许列表。

**M0-AT16A** （自动化，planned）

Given 文本含 <script> 和事件属性字样，When 在阅读器显示，Then 只显示文字；合法 PNG 本地显示。

**M0-AT16B** （自动化，planned）

Given javascript: 链接、带外链 SVG、CSS @import、指向其他 instance 的资产，Then 导入／构建拒绝或按明确规则移除，并无出站请求。

### M0-R17 · 版本边界与不可变快照

**MUST：** SourceRevision 和已封存 TranslationRevision 不可变；编辑发生于 TranslationDraft，保存段落版本并使用 If-Match。ArtifactVersion 固定绑定三轴。M0 可限定每个 document 一个当前目标语言，但数据库必须容纳多语言 edition。

**M0-AT17A** （自动化，planned）

Given 草稿封存后修改译文，When 保存，Then 产生新草稿／段落版本，原 sealed snapshot 和旧 HTML 哈希不变。

**M0-AT17B** （自动化，planned）

Given 同一草稿两个旧 ETag 保存，Then 首次成功、第二次 412；不能 last-write-wins。

### M0-R18 · 仅 Compose、完整运行依赖与恢复

**MUST：** 正式运行只支持Docker Compose：app直接提供HTTP、worker执行耐久任务、隔离parser检查PDF、PostgreSQL和migrate均容器化。所有运行时、原生PDF库、构建输出、模板、所需模型资产在镜像/随release卷中；启动不执行pip/npm/模型下载。宿主只需Docker+Compose；密钥和外部翻译服务不是可打包库。M0具备版本清单与一致备份恢复。

**M0-AT18A** （自动化＋人工/环境验证，planned）

Given 仅安装Docker+Compose且无Python/Node/qpdf/PostgreSQL的干净宿主，When 使用已构建release启动并断开下载源，Then 能入库、内置样例阅读/导出，健康检查正确，卷重建后可恢复。

**M0-AT18B** （自动化＋人工/环境验证，planned）

Given 数据卷损坏、必需运行依赖或镜像模型资产缺失，Then readiness明确失败，不运行时自动安装；不能将原型容器启动算正式M0验收。

## 5. 非功能、边界与失败要求

真实用户路径与内部fixture严格隔离。静态正文和资源字节确定，app容器重启不丢目录；失败的PDF检查不会建立成功source。

没有登录不代表可以执行上传内容；PDF解析无网络/秘密且资源受限。仅支持Compose，不安排替代部署。阅读静态化不取消资源存在性和删除状态检查。配置、容量、完整性与无JS阅读要求继承产品基线。

## 6. 退出门与可演示交付

从空卷Compose启动，不创建账户；上传一份受控PDF并收藏，重建app后仍存在；原PDF字节不变。选择内置旧资料，离线导出且断网/禁JS可读。故障注入半写产物，当前版本不变；检测非PDF及文件路径攻击。

| Gate | 名称 | 必需证据 |
|---|---|---|
| M0-G01 | 范围与无身份契约 | PDF唯一入口；无用户/角色/会话/工作区表或接口；无反代服务；CSS/hash符合参考。 |
| M0-G02 | PDF库与IR基础 | 真实PDF存储/检查/原件预览及内部全结构IR语义测试；没有双语粘贴或IR导入入口。 |
| M0-G03 | 完整静态出版 | 各结构渲染、断网file://、无JS、无存储、确定性hash。 |
| M0-G04 | 真实产品闭环 | 上传PDF→验证→持久原件条目→收藏/归档→重开浏览器读取；内部fixture出版及静态导出独立验证，无公开IR入口。 |
| M0-G05 | 无身份边界及PDF内容安全 | 无账号/会话/ACL对象；同实例不同浏览器直接访问；XSS、路径穿越、PDF动作及Host/Origin负例。 |
| M0-G06 | Compose依赖与恢复 | Docker-only干净宿主、离线运行依赖、内置样例静态导出、DB与卷备份恢复、坏PDF隔离。 |
| M0-G07 | 部署和恢复 | 全新安装与恢复演练，源件/模板/当前artifact hash一致。 |

全部gate初始状态not_evaluated。详见[M0 Plan](M0-plan.md)；没有已执行证据不得标completed。

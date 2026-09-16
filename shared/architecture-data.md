# 共享架构与数据契约 · v3

**2026-09-13 解析设备。** Settings.preferences 增加可选 parser_accelerator。parser 通过当前解释器和隔离的 Paddle CUDA 解释器探测可用设备，将脱敏能力报告写入模型验证心跳；API 只读挂载 parser_outputs。新任务把解析后的 cpu/cuda/mlx 写入 Task.payload 与配置快照，worker 转发为 spool.accelerator，独立 parser 子进程才应用该枚举值，不修改父进程环境。CPU/CUDA 使用同一 CUDA 镜像配方；Apple 的 Docker MLX 图像后端未满足条件时明确不可用，不能把 Linux 容器推断为可访问宿主 Metal。

**2026-09-09 非阻断数据扩展（已实现，schema 12）。** 增量扩展任务/尝试时间、实际模型快照与持久日志；统一页级质量异常和自动恢复证据；新增 DOI 发现、书目元数据、来源与标题优先级。内容质量失败不作为流水线许可条件，旧来源/发布快照保持不可变。详见 [NB Spec](../milestones/nonblocking-workflow-spec.md) 与 [NB-P01–12](../milestones/nonblocking-workflow-plan.md)。

**2026-09-08 解析时限。** Settings.preferences 持久化 `parser_timeout_seconds`，新任务缺省 7200 秒，Task.payload 冻结该值。worker 按快照创建 spool 的 `timeout_seconds` 和绝对 deadline，并只额外等待 10 秒结果落盘；parser 取绝对 deadline 剩余时间与请求时限的较小值，子进程 CPU 秒上限为时限 × 4。旧任务/请求无字段时保留 900 秒；检查任务仍为 900 秒。超时、取消和 fence 检查继续生效，不改变解析模型指纹或既有来源。

**2026-09-08 Paddle 表格补全。** 将官方表格 HTML 解码为内部行列和单元格数据，拒绝嵌套表格、危险标签、缺失/重叠网格及超限跨度，保留 rowspan/colspan 和显式空白格。只有 raw/normalized/inline 均无有效文字的 table_cell 可不翻译并标 empty_table_cell；非空单元格不能借此绕过必译约束。表格级原件裁图随结构化表示保留，单元格 locator 明确使用整表区域。原生文字覆盖及表格字符/数字校验独立于识别输出；差异进入来源问题。解析配置指纹绑定 table_adapter 版本，历史快照不改写。

2026-09-08 解析增强补充：Docling 默认 OCR、公式和代码识别在离线 CPU parser 内运行。公式/代码块的 raw_text/normalized_text 记录模型的解析输出，attributes.recognition 保存 model、revision 和增强前 original_text，原始 Docling JSON 与 PDF 裁图同时保留；这不是机械 normalization_edits。独立原生覆盖检查使用增强前文字。parser.config_hash 同时绑定模型锁、CPU 推理配置和请求 profile，重新解析产生新来源，不修改旧快照。

适用于 M0–M2。产品边界以[基线](../00-product-baseline.md)为准。本章定义架构契约；实现状态与验收范围以当前代码和执行证据为准。

## 1. 架构与服务边界

```text
浏览器
  │ 一个HTTP端口；无登录；相对API与阅读地址
  ▼
app（FastAPI + 已构建管理前端 + manifest限定的文件服务）
  ├── PostgreSQL：目录、版本、任务、检查点、预算账本
  ├── provider_config卷：设置页原子写配置/secret；worker只读；不进入内容备份
  └── data卷：上传隔离区、原PDF、封存IR/译文、静态制品
             ▲
worker ──────┘  领取任务 → 验证结果 → 翻译 → QA → 渲染/发布
  │                                  │
  │ 只读配置与secret                 └── 已确认的外部翻译API
  │
  ├── parser_inputs卷：PDF副本 + 有限请求描述
  └── parser_outputs卷：返回IR/页图/状态
             ▲
parser（CPU/CUDA network_mode:none；MLX 仅 Docker 推理网络；无DB和Provider凭据）
  inspector / PaddleOCR-VL / Docling / Granite，固定模型资产

migrate / init / maintenance：同一套Compose中的一次性运维命令
```

只有app发布端口；没有反向代理或身份服务。PostgreSQL是独立容器但不映射主机端口。app与worker为同仓库领域模块的不同进程，避免把耗时任务绑在HTTP请求上。工作队列使用PostgreSQL，不增加新中间件。

## 2. 单实例数据模型

| 实体 | 关键字段/唯一性 | 事实来源 |
|---|---|---|
| Document | id,title,tags,starred,lifecycle,generation | PostgreSQL；无owner/user/workspace |
| Upload | id,status,byte_count,sha256,expires_at | DB状态+隔离临时文件 |
| SourceAsset | id,sha256,byte_size,page_count,media_type=application/pdf | 原PDF不可变字节 |
| SourceDraft | id,asset_id,parser_output,edits,generation | 未确认结构可变 |
| SourceRevision | id,asset_id,snapshot_hash,parser/config/normalizer版本 | 已封存canonical JSON |
| TranslationEdition | UNIQUE(document_id,target_locale),current_artifact_id,generation | DB当前指针 |
| TranslationDraft | source_revision_id,base_revision_id,generation | DB当前草稿/segment版本 |
| SegmentVersion | draft_id,block_id,sequence,target_inline,origin | 追加记录，不修改旧版本 |
| TranslationRevision | id,source_revision_id,snapshot_hash,profile/glossary/QA | 封存canonical JSON |
| ArtifactVersion | id,source/translation/template绑定,manifest_hash,state | 文件只增不改，DB索引 |
| Job/Task/Attempt | 分别代表用户操作、可领取单元、一次执行 | DB，持久租约/fence |
| DispatchPermit/Usage | control_epoch,attempt_id,price_snapshot,reserved/actual | DB整数金额，幂等结算 |
| Issue/ReviewRecord | 指纹、来源证据、确认动作与时间 | DB，Issue可来自system；ReviewRecord仅origin=manual_ui |
| GlossaryRevision/Candidate/TM | 语言、规则、候选base、来源引用 | M2新增，不含身份字段 |
| ReadingPosition/Settings | document+locale+artifact；singleton设置 | DB，所有浏览器访问同一份 |

不创建“默认个人用户”或“唯一工作区”以兼容旧设计。`actor`不需要账号表：操作来源枚举 `manual_ui/system/migration` 与 request_id 足以解释历史；这不能作为谁执行了操作的身份审计。

### 草稿与封存

源/译草稿可变，更新携带If-Match generation。封存生成不可变快照，并记录父修订和输入hash。DB保存索引与元数据；大型封存JSON在文件卷作为canonical内容，DB中snapshot_hash必须与其一致。恢复校验两者，不允许两份内容同时可变且相互覆盖。

## 3. 三条独立版本轴

新PDF字节、重新解析或修正阅读顺序产生 SourceRevision；变更译文或语言产生 TranslationRevision；变更模板或封存译文产生 ArtifactVersion。新语言复用来源结构和图片；仅换模板不调用模型、不更新翻译缓存；旧文章始终固定到原版本。

Edition当前指针更新采用单调generation的CAS。回滚A→B→A也继续递增generation，旧客户端不能利用ABA误判版本未变。多标签页并发保护仍然需要，不是多人协作功能。

## 4. IR v3

[Schema](../contracts/document-ir-v3.schema.json)是内部RenderInput语法；普通用户没有上传它的入口。主字段为document、source_revision、translation_revision、render。document不含用户或工作区。source.kind恒为`pdf_upload`，原件media_type恒为PDF；资产列表允许从PDF提取的PNG/JPEG/WebP等产物，这不等于允许用户上传它们。

### 结构与单次渲染

支持heading、paragraph、list_item、code、math、figure、caption、table、table_cell、footnote、reference。每块有id、kind、顺序、父章节、owner_id、raw/normalized文字、source_inline、hash、locator和处置。根reading_order只列需要独立渲染的根块；table_cell归table、caption归figure/table，不再重复出现在根流。title_block_id在hero显示一次。

source_inline只接受text/受限marks/protected_ref/link/xref。模型输出只接受text/protected_ref；禁止任意HTML、CSS、href、文件路径或审校状态。链接/引用从源AST安全映射，不允许模型创造新地址。公式/代码/引用/数字可作为保护原子，按多重集合验证，不能把重复数字变成集合后漏检。

### 来源定位

PDF页码1-based；bbox=[x0,y0,x1,y1]为左上角原点的point坐标，page_size=[width,height]，坐标有效且边界不越页。记录MediaBox/CropBox/rotation变换；UI缩放乘比例，不能混用像素与points。跨页段落有多个locator，不能虚构一个跨页大框。legacy无可靠定位则只给原PDF入口。

raw_text保留抽取字符，normalized_text只做有记录的机械转换。编辑区间为Unicode code point、左闭右开；前端不能把JS UTF-16索引直接保存为该单位。source_inline展开后必须与normalized_text一致。

### 语义验证器的最小职责

校验ID唯一、标题存在、parent树无环、owner合法、表格网格不重叠且结构完整、xref存在、每块恰好被渲染一次、locator指向原PDF、asset文件hash匹配、源hash匹配、结果映射完整、非空译文及安全引用。nonblocking-v1 允许带明确原因的原文/页图 fallback，保护内容差异作为提示；旧 IR 仍按其版本验证。保留策略与学术元数据规则见 [original-only-content](original-only-content.md)，不能伪造已翻译或已核对。

## 5. 规范化与哈希

源文件SHA-256直接基于原始字节。JSON canonicalization固定UTF-8、sort_keys、无空白分隔、禁止NaN/Infinity和重复键，Unicode不额外NFKC归一化。raw与normalized的含义变化必须有显式记录。block hash至少包含kind、normalized文字、source_inline、保护原子值、结构属性。context_hash涵盖提供给模型的章节和邻文；排版坐标变化不自动改变语义文字hash，但结构修订hash会变化。

Artifact manifest记录每个输出文件相对路径、media_type、长度、sha256、源/译/模板/renderer版本及QA指纹。正文渲染不含当前时间或随机数；构建时间可放manifest非确定区。相同封存输入+模板+设置生成相同正文/资源字节。ZIP要定义排序、固定时间戳与压缩配置后才比较zip字节。

## 6. Parser与spool协议

worker把已确认的本地PDF复制到 `parser_inputs/{task_id}/{fence}/original.pdf`；写入request.tmp后原子rename request.json。描述包含task_id、fence、source_sha256、max_pages、deadline、parser版本，不含任意宿主路径或密钥。parser只读input卷，只写output卷；不访问DB和原件总库。

parser串行处理任务，在每个PDF的受限子进程工作；输出先临时目录再写result.json为完成标记。结果包含task/fence/source_hash、文件清单与摘要、page coverage和错误，不是DB成功状态。worker复核租约、来源hash、文件名/大小/文件实际hash、禁symlink和路径穿越，再复制到受信内容存储并事务提交。旧fence输出永不覆盖当前任务。

parser容器OOM重启后input仍在，但同一attempt不能无限重算；worker重试次数持久化，超限终止并隔离坏任务。parser只是一条隔离边界，不将Compose宣传成可抵御任意容器逃逸的安全沙箱。

## 7. 存储布局

```text
data/
  uploads/{upload_id}/...
  sources/{source_asset_id}/original.pdf
  documents/{docid}/sources/{source_revision}/document.json
  documents/{docid}/translations/{locale}/{revision}.json
  documents/{docid}/artifacts/{artifact_id}/
    index.html  reader.css  reader.js  assets/  manifest.json
  exports/{export_id}/...
  staging/{task_id}/{fence}/...
```

部署仅支持本地命名卷。所有存储键由系统生成，无用户目录前缀。资源存在性/manifest包含性/tombstone检查仍需保留，这不是ACL。不要把data根目录直接作为可浏览静态目录挂出；源件和制品通过app业务路径解析。

## 8. 依赖和模块划分

`apps/web`负责管理UI；`apps/api`负责短请求与直接文件响应；`packages/ir`负责模型外的结构事实；`packages/providers`负责有限输入输出；`packages/jobs`负责持久调度；`packages/publisher`负责不可变发布；`workers/parser`不持秘密。所有模块由同一仓库构建，镜像可按依赖大小拆分，不意味着需要微服务治理。

Docling的本地资产配置与Compose的健康依赖行为已核对官方文档，见[技术依据](../sources.md)。它们支持实现选项，不代表本产品的解析准确率或容器部署已经被验证。

# API、命令与 Worker 契约 · v3

**2026-09-09 已规划、待实现的接口扩展。** NB 计划统一非阻断 issues、执行/质量状态分离、部分结果、任务实际模型与起止/耗时/持久化日志，以及 DOI/元数据状态和书目信息。`unresolved`、`can_translate` 和旧 QA 阻断字段需同步兼容迁移，不能只解禁前端。新契约详见 [NB Spec](../milestones/nonblocking-workflow-spec.md)；现有端点尚未因文档登记改变。

**2026-09-08 解析超时设置。** `GET/PATCH /settings/preferences` 增加 `parser_timeout_seconds`：严格 JSON 整数，60–86400 且为 60 的倍数；缺省读取为 7200，不通过 GET 改写已有偏好。PATCH 沿用 generation / If-Match，null 与其他可选偏好一样表示不修改。解析入队事务读取当前偏好并将时限写入 Task payload；执行时不重新读取。spool 根字段 `timeout_seconds` 与 UTC `deadline` 对应，旧任务/旧请求缺字段时按 900 秒处理。上传检查固定 900 秒，设置不影响 Provider HTTP timeout。

**2026-09-08 解析选择扩展。** `GET /capabilities` 返回 `parser_profiles`。`GET/PATCH /settings/preferences` 支持 `parser_profile_revision`：`docling-v1`（默认）、`granite-docling-v1`、`paddleocr-vl-1.6-v1`；PATCH 沿用设置 generation 的 If-Match，保留其他偏好和 Provider 配置。`GET /settings/provider` 的同名便利字段来自偏好。`POST /documents/{id}/parse` 可显式选择，省略或 null 时在入队事务内读取默认值并写入任务 payload；未知 ID 返回 422。worker 按冻结 profile 设置解析器版本和 spool 描述符，不在执行时重新读取偏好，也不自动回退其他方案。

**2026-09-07 用户补充：取消译文强制人工核对/确认。** 段落确认、语义和术语问题核对均为可选；未确认或未处置的高风险提示不阻止封存、手动发布、自动发布或导出，提示及实际核对状态仍保留。缺段、数字/保护原子不一致、资源损坏等硬完整性问题和过期 QA 仍阻断。修改后只需重跑本地质量检查，不要求再次人工确认。此补充覆盖下文旧的强制核对表述；外发授权、未知请求风险处理及来源修正证据规则不变。

正式API尚待M0–M2实施。本原型没有这些服务端端点。所有端点位于同一个app origin，**没有身份令牌、登录Cookie或用户/工作区路径参数** 。资源检查指完整性、存在性与删除状态，不是权限系统。

## 1. 通用协议

基础路径`/api/v1`；时间UTC ISO-8601；ID为不透明字符串；locale按规范标签保存。JSON拒绝未知字段；金额使用整数微货币。分页以cursor+limit（默认30、最大100），排序键稳定。所有可修改实体返回ETag，写入要求If-Match；缺失返回428，过期412，业务冲突409。

创建类操作携带Idempotency-Key（1–128字符），保存(method,path,key,canonical_body_hash,response)；同键同体重放返回原结果，不同体409。默认保留7天；过期后不承诺旧请求去重。job/attempt/自然唯一键继续防止重复本地提交。服务器幂等不保证供应商去重或不重复收费。

错误结构：`{error:{code,message,retryable,resource_id,details},request_id}`。异常栈和密钥不返回。没有未登录401路径；供应商401映射为PROVIDER_CONFIG并在job中呈现，不误导为用户需要登录。

## 2. M0：上传与原件库

| 方法与路径 | 请求/结果 | 行为 |
|---|---|---|
| GET /capabilities | phase、source_mime_types、功能标志、限制、Provider configured | 固定pdf，无账号信息 |
| POST /uploads | filename、media_type=application/pdf、byte_size | 201 upload_id、chunk_limit=4MiB、expires_at |
| PUT /uploads/{id}/chunks/{index} | 原始bytes，Content-Range；每块SHA | 顺序索引、无重叠；相同索引相同内容幂等，变更409 |
| POST /uploads/{id}/finalize | expected_sha256、total_bytes | 202 inspector_job；完成后才verified，不能仅凭扩展名成功 |
| GET /uploads/{id} | status、received_bytes、hash、page_count/error | 按已接收字节进度，24h过期 |
| POST /imports | 见下方严格Schema | 201 Document source_only；只接受verified PDF upload_id |
| GET /documents | q、tag、starred、lifecycle、cursor | 单份个人库 |
| GET /documents/{id} | 元数据、源件、editions、当前job | 旧发布版和新任务分开 |
| PATCH /documents/{id} | title、tags、starred、archived；If-Match | 只改元数据，不改封存阅读内容 |
| GET /documents/{id}/original | PDF binary，Range/HEAD | 原PDF完整字节，不执行PDF动作 |
| DELETE /documents/{id} | If-Match、confirm=true | 202 tombstone+cleanup_job，之后410 |

同一文件的多个finalize请求只创建一次检查任务。上传失败或取消后重传新会话；超50MiB在接收过程中即停止，不能先落无限大文件再检查。多PDF由客户端逐份创建会话；一份失败不回滚其他。

```json
{
  "source": {"kind":"pdf_upload","upload_id":"upl_01"},
  "source_language":"auto",
  "target_language":"zh-Hans"
}
```

严格契约：[import-request.schema.json](../contracts/import-request.schema.json)。`document_id`可用于为已有文档提交新PDF来源，但必须显式指定且遵守generation；同名不自动覆盖。重复hash返回候选文档，用户选择复用来源或独立文档；唯一键确保资产不会重复写入。

**不存在** `/login`、`/users`、`/workspaces`、`/roles`、`/imports/url`、`/imports/text`、`/imports/bilingual`、`/imports/ir`或附件上传路由。上传schema之外的任意JSON不作为文档来源。原文中普通https链接不是导入API。

## 3. M0：静态资源与内部出版

| 路径/命令 | 契约 |
|---|---|
| GET /read/{document_id}/{locale} | 跳转到该edition的不可变artifact URL，不临时翻译 |
| GET /artifacts/{artifact_id}/{relative_path} | 仅manifest允许路径，先确认文档未删除；HTML正文在文件内 |
| POST /artifacts/{artifact_id}/exports | format=single_html/bundle；include_source显式 | 
| GET /exports/{id} | 状态与生成文件路径；不得接受任意filesystem路径 |
| GET /exports/{id}/download | 文件完整且所属文档存在才提供 |
| Compose run maintenance seed-legacy | 只导入release内hash允许的两个旧样例；非Web上传 |
| Compose run test render-fixtures | 内部IR→静态页面验收；绝不开放给普通创建来源端点 |

M0不提供用户可变译文来源；出版基础由种子/内部测试证明。M1具备真实译文后复用同一Publisher。

## 4. M1：解析、预检与翻译

| 方法与路径 | 输入与前提 | 输出 |
|---|---|---|
| POST /documents/{id}/parse | source_asset_id、parser_profile_revision、If-Match | 202 job_id |
| GET /jobs | q、group、status、document_id、cursor、limit | 按 created_at DESC / id DESC 稳定分页；q 搜索题名、上传文件名或任务编号；group=all/active/attention/completed/cancelled 在分页前过滤 |
| GET /jobs/{job_id} | 无登录；检查存在/删除 | stage、status、实际计数、费用、issues、control_epoch |
| GET /jobs/{id}/events | Last-Event-ID可选 | SSE；事件过期发snapshot_required，客户端GET快照 |
| GET /imports/{id}/preflight | 本次源revision | 页/块/区域覆盖、OCR_REQUIRED、图表、估算、hash |
| POST /imports/{id}/confirm | source_hash、preflight_generation、profile_revision、locale、budget_micro、external_processing_confirmed、publish_policy | 202翻译job；变更/正文未解409 |
| POST /jobs/{id}/pause | If-Match | control_epoch++，停止新许可 |
| POST /jobs/{id}/resume | If-Match，配置/预算有效 | 202，只恢复安全缺失单元 |
| POST /jobs/{id}/cancel | If-Match | cancel_requested/cancelled；在途仍记账 |
| POST /attempts/{id}/resolve | decision=record_.agent/tmp/evidence/retry_accept_risk/stop；reason、budget确认 | 不制造供应商证据；风险重试保留旧未知支出 |
| GET /settings/provider | configured、dispatch_configuration_ready、missing_fields、endpoint、api_protocol、auth_mode、Claude api_version、model/profile能力、费率/隐私版本、generation与密钥配置状态 | 返回ETag；不返回secret |
| PUT /settings/provider | profile、可选api_key、clear_api_key；If-Match及Idempotency-Key | 原子保存后端配置，不调用模型；密钥不进入DB或响应 |
| PATCH /settings/preferences | locale、manual/auto发布、界面偏好 | singleton配置 |
| GET /settings/dispatch | 无 | 数据库中的派发暂停/维护状态、generation、未知请求数量/金额、在途请求数量；返回 ETag |
| PATCH /settings/dispatch | dispatch_disabled、可选 accept_unknown_risk/reason；If-Match、Idempotency-Key | 单独保存实例外发开关，不修改 Provider 配置或密钥 |

2026-09-07 任务展示补充：列表、详情与事件快照公开 `title`、`filename`、`target_locale`、`created_at`。题名从当前文档目录读取，检查任务使用其上传文件名，缺失时显示“未命名 PDF”，操作名称在 UI 独立显示。既有任务无需迁移即可获得名称，文档重命名后同步生效。删除任务只显示“已删除文档”和清理回执，不返回或按删除前题名检索。列表用实际页/段计数显示进度，无总数时不推算百分比；完整任务编号保留在详情技术信息中。

2026-09-06用户新增要求覆盖原只读 Provider 设置：UI 可编辑完整请求 endpoint（不自动追加路径）、以下四种协议、model ID、鉴权与 API key，以及价格/限额。保存仅落本地文件，不自动探测或发起计费请求。

| api_protocol | provider（由协议确定） | auth_mode | 原生请求头 / 完整 URL 示例 |
|---|---|---|---|
| responses | openai | bearer / none | `Authorization: Bearer`；`https://api.openai.com/v1/responses` |
| chat_completions | openai | bearer / none | `Authorization: Bearer`；用户指定完整兼容服务 URL |
| gemini_interactions | gemini | api_key / none | `x-goog-api-key`；`https://generativelanguage.googleapis.com/v1beta/interactions` |
| claude_messages | anthropic | api_key / none | `x-api-key` 与 `anthropic-version`；`https://api.anthropic.com/v1/messages` |

`none` 必须明确选择，不发送上述鉴权头。普通原生 API key 是当前支持范围，不支持 OAuth 或多 workspace 路由。Claude `api_version` 默认为 `2023-06-01`，高级输入使用 `YYYY-MM-DD`；保存至不可变 profile 并纳入 hash。非 Claude 不发送该字段，公开 profile 拒绝多余的版本字段。协议与 provider/auth 的组合必须匹配；不要求用户手动选择两套相互冲突的服务类型。

PUT 使用 `{profile, api_key?, clear_api_key?}`，携带 `If-Match` 和 `Idempotency-Key`。空 key 保留，清除必须明确；改变 endpoint/协议/鉴权不能静默复用旧密钥。按2026-09-07用户要求，UI 切换接口类型将完整 URL 和 model ID 替换为该接口的默认值，并清空尚未提交的 key；字段仍可手动修改，打开或重新读取配置保留已保存的值，切换不自动保存或调用模型。默认值见 README 的接口表。endpoint 允许用户指定 HTTP(S) 服务，包括本地服务，拒绝 URL 内用户名密码、query、fragment；不允许文档内容指定目的地。派发不跟随重定向，不隐式重试或协议回退。

model 或所需价格未填可以先保存，未知价格不推断为 `0`；明确的零费率有效。请求上限采用下述应用默认值，已保存自定义值保持不变。`configured` 只表示公开参数完整，`dispatch_configuration_ready` 另外结合密钥/无鉴权状态，缺项通过 `missing_fields` 返回。密钥清除后即使公开参数仍完整，派发仍等待配置。服务端生成内部 profile/价格/提示词/隐私修订，UI 不回传 generation、profile_hash、config_revision、credential_revision、costs 或密钥状态等只读字段。外部 worker-only 密钥不可见时，`has_api_key=null`、`credential_status=external_unverified`，不假称已验证。

配置在独立provider_config卷中按不可变revision保存并原子切换当前指针。app可写，worker只读，parser/db/maintenance不挂载。密钥字段绕过通用DB幂等记录，专用文件幂等仅保存带独立secret的请求HMAC与公开响应；不保存明文请求正文。GET仅返回密钥是否配置，原外部secret文件只有worker可见时返回未知状态。修改配置使预检/profile hash过期，旧排队任务停止等待配置；已在途请求使用其已绑定版本，清除当前密钥不是撤销远端请求或删除历史版本。

旧部署profile文件与worker-only secret仍作为未使用设置页时的兼容来源。新保存的配置取代该来源，不把外部密钥复制到app。标准备份不包含provider_config卷；新宿主恢复后须重新配置服务，保存配置不解除数据库中的派发暂停状态。

### 2026-09-07 补充：设置页控制外部 API 请求

“设置 → AI 服务 → 外部 API 请求”提供“允许外部 API 请求”开关，单独保存后立即生效，重启/重建容器后保留。唯一状态源是 PostgreSQL `Settings.dispatch_disabled`，不读取或覆盖为 `DISPATCH_DISABLED` 环境变量；新实例与备份恢复仍默认暂停。外发开关与界面偏好共用 Settings generation，Provider 配置另用自己的版本；过期保存返回 412，幂等重放不重复记录确认。

关闭阻止新的连接测试、翻译与语义检查请求，已在途请求继续记账。开启允许已有确认且仍满足配置/预算条件的排队任务继续；不恢复暂停/结果未知任务，不更改凭据，也不代替各入口的外发确认。存在未知 Permit 时，开启必须明确勾选风险确认并填写非空说明；手工确认写入对应 Attempt 证据，未知金额和 Permit 均保留。维护模式继续阻止修改，`maintenance-off` 只恢复普通写入，外发仍须在设置页单独开启。

### 2026-09-07 补充：可选金额控制与默认上限

`profile.cost_control_enabled` 是严格 boolean。新设置默认 `false`；旧完整配置/已授权快照缺字段时沿用 `true`。已有设置 PUT 省略该字段时保持当前明确选择；旧未完成草稿缺字段可在下次保存时采用 `false`。GET 的有效显示不改旧 profile hash 或凭据绑定。

GET/PUT 设置响应公开三个当前上限及 `token_limits_defaults={max_input_tokens:32768,max_output_tokens:8192,max_unit_characters:2000}`。该 defaults 对象仅为只读元数据，不回传至 profile、不进入 profile hash。新保存的 revision 固化有效上限；字段省略时继承已有值，否则使用应用默认。前端“恢复默认”仅将三值替换为服务端 defaults 后发送正常 If-Match/Idempotency-Key PUT，不改变 endpoint、协议或 key；过期依然 412。

关闭金额控制时，来源确认、已有来源新增译本、候选翻译与语义检查四个入口的 `budget_micro` 可省略，保存为 `null`，价格可缺失/不完整。开启时必须有完整价格与正作业预算。服务仍执行外发确认、配置 hash、source/generation/fence 和请求并发检查。切换设置不会改写旧任务或旧 Permit 的控制模式；旧排队配置失效时必须重新确认。

Job 与 Attempt 视图带冻结的 `cost_control_enabled`，`budget_micro`、预留/实际/未知金额允许 `null`；聚合分类含不可确定金额时也为 `null`，不能显示成零费用。Permit 始终存在，关闭时 `reserved_micro=null`，可确定实费则记录，否则 `actual_micro=null`。HTTP 已完成且译文有效时，关闭金额控制可接受缺失用量并保留未计价状态；网络 `outcome_unknown` 和模型不匹配仍停止自动重发。风险重试仍需明确确认，关闭模式只免金额预算，不删除旧 unknown 记录。本文原有预算预留/价格必选规则适用于开启模式；正式真实 Provider 验收继续要求批准的测试预算。

### 连接与密钥测试

2026-09-07 连接测试补充：设置页“测试 API 连接 / 密钥”只测试已保存配置；未保存字段须先保存。确认展示完整 endpoint、协议、model ID、固定 `Hello.` 测试内容和结构化输出要求，不含文库内容。`POST /settings/provider/test` 携带 `If-Match`、`Idempotency-Key`、`profile_hash`、`external_processing_confirmed=true`；金额控制开启时另须正 `budget_micro`。返回 202 测试任务，`GET /settings/provider/test/{job_id}` 只读状态；设置 GET 的 `connection_test` 为当前 profile 最近一次测试，`connection_test_has_unknown` 保留该配置旧未知费用提示。

Worker 使用同一四协议适配器及后端绑定的 secret，固定一条合成测试单元，输入上限取已配置值与 8192 的较小值，输出上限取已配置值与 256 的较小值；不修改 profile、语言认证或文档。沿用 Permit/预算/维护与派发禁用/并发门；连接测试不自动重试，崩溃前后已发未知仍保留风险，已结算但丢失完成状态也不重新派发。测试返回成功、静态错误分类、耗时与费用，不返回模型原文或上游错误正文。已有未知测试再试须 `duplicate_charge_risk_confirmed=true`，不释放旧未知金额。测试只证明该次连接和结构化响应，不认证翻译质量、所有模型能力或供应商计费上限；真实 Provider 验收门不变。

### 2026-09-07 补充：所有语言开放

所有规范语言标签与组合均可直接使用；GET capabilities/provider 返回 `language_policy: all`，移除实验语言、语言能力矩阵和 `experimental_confirmed` 请求字段。旧 profile 的 enabled_pairs 不控制可用性；各入口继续校验完整 profile_hash、来源版本、外发确认与可选金额预算，自动发布继续执行全部质量门禁。界面以各语言自身名称显示，API保留规范代码、脚本和地区差异。详见[语言与配置确认](../ops/languages.md)。

## 5. M1/M2：校对、候选和版本

| 方法与路径 | 行为 |
|---|---|
| GET /drafts/{id} | 当前source与segment versions、QA指纹、问题 |
| PATCH /drafts/{id}/segments/{block_id} | target_inline、reason、base_segment_version；If-Match；新版本追加 |
| POST /drafts/{id}/validate | 冻结当前generation生成QA；返回后过期则不可用于发布 |
| POST /drafts/{id}/seal | 指定QA和generation，产生不可变translation revision |
| POST /editions/{id}/publish | translation_revision_id、template_id、expected_generation；202build job |
| POST /drafts/{id}/segments/{block_id}/confirm-review | 绑定source_hash、segment版本、context、glossary；明确人工点击 |
| POST /drafts/{id}/candidates | 选定block_ids、profile/glossary版本、预算外发确认；M2 |
| POST /candidates/{id}/accept | base_source/segment/context/glossary匹配；If-Match，不自动覆盖 |
| GET /documents/{id}/history | 源、译、artifact与publication事件，非用户审计 |
| POST /editions/{id}/rollback | artifact_id+expected_generation；同文档locale且完整；generation++ |
| POST /documents/{id}/editions | target_locale+source_revision；唯一(document,locale) |
| POST /sources/{revision}/corrections | 明确原件证据、拆并/排序/机械修正；生成新SourceDraft |
| POST /glossaries/revisions | 全库或document scope、词项和语言；新immutable revision |
| POST /glossaries/{id}/impact | 预览相关块；不调用模型 |
| POST /artifacts/{id}/rebuild | 新受控模板，仅封存源/译→产物；Provider计数0 |
| GET /search | q、source/target、locale；只返回当前发布generation匹配的块 |
| PUT /reading-position | document/locale/artifact/block/offset；实例级共享 |

批量接受候选不能用全局last-write-wins。候选返回时草稿变了只展示冲突；保存草稿不自动等于human_reviewed。不能忽略硬结构问题来发布。

## 6. Worker 边界

`PdfInspector.inspect(local_pdf, limits)`返回真实页数、加密/有效性与hash；`PdfParser.parse(task_manifest)`只消费本地PDF，输出IR与coverage。`TranslateProvider.translate(units, context, profile, glossary)`只返回unit_id及受限目标节点、finish/refusal、usage/request_id；无HTML生成、无工具、无用户身份输入。

原生协议仍使用同一目标 AST、单元 ID、保护引用与语义证据校验。Gemini 仅使用 Interactions，结构化结果从模型输出文本读取，思考内容不进入译文；显式 `store=false`，不发送历史 ID。Claude 使用 Messages 的原生结构化输出，不发送 `store`、工具或缓存控制，不覆盖模型默认思考设置。它们均不构成供应商不保留数据的承诺。官方字段依据见本轮 [Gemini 核对](../.agent/tmp/evidence/gemini-claude/gemini-official-contract-review.md)与 [Claude 核对](../.agent/tmp/evidence/gemini-claude/independent-claude-review.md)。

Gemini 和 Claude 两个原生协议的响应 model 必须与配置严格匹配；只有 Gemini 去除 `models/` 前缀后比较，不做别名推测。需要别名的服务应配置其实际返回的模型 ID，不一致结果不能写为成功译文。归一化输入/输出用量再进入原整数微货币账本：Gemini 缓存输入是总输入子集，输出为 `total_output_tokens + total_thought_tokens`，完整计数须一致；Claude 输入为未缓存输入、缓存读取、缓存写入之和，`output_tokens` 已含思考，不能再次加算。当前只配置输入、缓存读取、输出三种费率；未启用缓存控制也不能把意外 Claude 缓存写入当免费。开启金额控制时，必需计数缺失/矛盾、未定价维度或无法确认费用的响应（含 Claude 空内容拒绝）保留 `outcome_unknown` 并停止自动再派，等待证据核对与显式风险处理。关闭金额控制时，费用未知不阻止合法目标保存，金额保留 `null`；拒绝、模型不匹配和网络未知结果仍按各自安全规则处理。已知用量与可接受的翻译内容是两个独立判断。文档或本地契约测试不能证明远端 token 参数是已实测的硬计费上限。

`Publisher.build(sealed_source, sealed_translation, template)`只读取封存输入，生成manifest完整产物。`Publisher.commit(artifact_id, expected_edition_generation, control_epoch)`单独事务CAS。`Maintenance.backup/restore`只能在维护状态、完整hash验证后改变数据，没有Web ZIP导入。

## 7. 错误码最小集合

| HTTP/业务码 | 含义 | 自动重试 |
|---|---|---|
| 413 UPLOAD_TOO_LARGE | 实际字节超限 | 否 |
| 415 UNSUPPORTED_FORMAT | 非PDF，包括改扩展名 | 否 |
| 422 PDF_INVALID / PDF_ENCRYPTED | 解码失败或加密 | 否 |
| 409 UPLOAD_INCOMPLETE / SOURCE_PARSE_REVIEW | 上传未完成或正文未解 | 否 |
| OCR_REQUIRED | 当前无可靠文本层支持 | 否，保留原件 |
| 409 PREFLIGHT_STALE / QA_STALE | 确认/QA对应旧generation | 重新查看/确认 |
| 428/412 PRECONDITION_* | 并发前提条件缺失/过期 | 刷新并合并 |
| PROVIDER_CONFIG / PROVIDER_RATE_LIMIT | 配置错/可解释限流 | 只有后者按规则 |
| OUTCOME_UNKNOWN / BUDGET_PAUSED | 可能已收费/额度不足 | 默认不重试 |
| QUALITY_BLOCKED / ASSET_MISSING | 内容或资源不完整 | 修复后重验 |
| 410 DOCUMENT_DELETED | tombstone已提交 | 否，迟到结果不能复活 |

## 8. 验收前提

实际API应由类型生成OpenAPI并在CI检查没有认证securitySchemes和被删除路径。HTTP `Authorization`不用于本产品登录；无凭据GET/写端点行为由正常业务前提决定。供应商请求的 `Authorization`、`x-goog-api-key` 或 `x-api-key` 仅在 worker 到所选服务这一跳按协议生成，不用于文库身份认证。接口测试要区分两者。原生适配器与本地故障服务测试不解除任何需要真实 Provider 调用的 blocked 验收门。

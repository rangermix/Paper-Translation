# NB 执行、质量与历史契约

实施始于 2026-09-09。本页描述新增契约；各工作包运行验收以 NB backlog 为准。

执行状态描述实际操作。`completed_with_warnings` 和 `partially_completed` 是已完成终态，不进入等待处理或自动重试。`outcome_unknown` 保持付费结果未知，不能自动重发。质量状态独立为 `not_checked/checking/completed/stale/failed`，所有内容 issue 的 `blocking=false`，重要性不参与许可判断。

schema 12 只增加可空字段和两张技术数据表，不重写旧来源、译文、发布、Provider 配置或历史任务。Job 保存配置、运行时题名、实际模型和 UTC 起止时间；Task/Attempt 保存各次执行时间与实际模型。未知旧字段为 null，不能从当前设置猜值。日志在 PostgreSQL `task_logs`，使用稳定 sequence 游标和每 Job 唯一 event_key，不依赖临时 spool。备份包含新增表。

Document 的 original_filename 保留原始名称，title_user_edited/null 区分明确用户改名与历史未知；元数据绑定 SourceAsset，不改存储键。Upload/SourceAsset 保留 DOI 候选及证据。metadata_cache 按 DOI、服务、映射版本缓存并记录取得和过期时间。

新封存译文标记 `content_policy=nonblocking-v1`，新增 `fallback` 结果，target_inline 必须为空，reason 非空，fallback.mode 为 source_text 或 source_page，且不得声明已翻译/已核对。页替代必须有原 PDF 定位。旧 IR 仍按原版本读取；新工作流先构造可安全渲染的完整块映射，再封存。任意 HTML、未知保护引用、危险链接、非法路径、错源 hash、无效表格结构继续被拒绝，损坏内容应在进入渲染器前降级。

## 现有检查到新行为的映射

| 现有位置/检查 | 新行为 | 负责工作包 |
|---|---|---|
| workflow.preflight 的 can_translate/unresolved | issues 统一页聚合，兼容旧字段；可执行性只看有效来源及版本 | NB-P03/P05 |
| workflow.seal_source/confirm、sources.seal 的 SOURCE_PARSE_REVIEW | 自动恢复/原图替代后可封存；不要求全文人工确认 | NB-P04/P05 |
| parser coverage、VLM/native 数字和区域差异 | 保留证据并恢复，失败按页原图替代 | NB-P03/P04 |
| translation 单元缺失/保护原子差异 | 保存可用安全内容，失败单元明确 fallback；未知请求维持账本 | NB-P05 |
| editorial QA.valid、QUALITY_BLOCKED、QA_STALE | 自动补查/刷新；内容检查不阻止封存，CAS 仍有效 | NB-P05 |
| IR 必译双射/非空目标 | 下游完整结果映射包含有标签 fallback，不能伪造译文 | NB-P01/P05 |
| IR AST、path、hash、owner、table-grid | 渲染安全约束继续；不安全单元先转支持的原文/原图表示 | NB-P04/P05 |
| publish/rebuild/export 质量门 | 可导出部分结果及原图；不可变提交和资源验证继续 | NB-P05/P06 |
| UI 勾选来源核对、qa.valid 禁用按钮 | 移除质量许可，保留外发与运行条件；阅读优先 | NB-P06/P10 |
| job needs_review / ready 与错误原因 | 旧状态明确解释，新任务完成带提示；模型快照和日志真实显示 | NB-P02/P07 |

API 和 TypeScript 使用上述契约；UI 不以问题数量计算操作权限。规范 schema 位于 res/schemas/nonblocking-contract.schema.json。旧 M0–M2 验收记录不变，NB-AT01–24 独立登记。

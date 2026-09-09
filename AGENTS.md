# 编码 Agent 交接规则 · v3

本仓库已包含M0–M2实现；完整认证与release仍以最新验收证据为准。先读.agent/memory/current.md，不能把历史设计文本或旧镜像报告当作当前完成状态。

项目已提升到 Git 仓库根目录，所有命令从根目录执行。可复用 agent 验收工具在 `.agent/harness/`，工作记忆在 `.agent/memory/`、长期笔记在 `.agent/notes/`；日志、截图、临时脚本和运行报告只写 `.agent/tmp/`，每次运行使用独立目录，不覆盖历史证据。持久本地环境、授权记录和磁盘放 `.agent/local-data/`，不能按临时文件清理。这两个本地目录不提交 Git，整个 `.agent/` 不进入 Docker 镜像。路径映射见 `.agent/relocation.json`。

1. 完整读取 `00-product-baseline.md`、`shared/`、`deployment/compose-contract.md`及所执行阶段的Spec/Plan。最新五条用户约束优先，不恢复旧版本的输入、身份、权限或反代模块。
2. 从M0-P01开始，先盘点实际代码及测试，再建立退出门对应测试。内部IR夹具不是对外入口；原有两篇论文只能受控内置seed。
3. 只处理PDF。扫描/OCR仍在当前认证范围之外。原文由解析器和人工来源校对产生，翻译模型不能改写源文或生成网页。
4. 单实例无身份系统：不建users/workspaces/tenants/roles/sessions表，不设默认owner。多标签页/worker竞争仍需版本、generation、fence与幂等。
5. 部署只有Docker Compose，app直接提供HTTP，后端依赖全容器化，解析模型构建期下载固定版本并入镜像；无运行时pip/npm或模型自动下载，无内置反代。
6. 所有API密钥持久化到后端secret文件。按2026-09-06用户新增要求，设置页允许一次性输入API endpoint、key、model ID等，支持OpenAI Responses/Chat Completions、Gemini Interactions和Claude Messages；保存后不回显密钥，不写浏览器存储、PDF解析器、日志或导出。协议、供应商、鉴权和Claude API版本须一致，禁止失败后自动切换；原生响应模型必须与固定model ID匹配，Gemini仅允许models/前缀等价，不能猜测别名。真实模型调用必须先有测试预算与外发确认，不擅自切换供应商。
7. 旧reader-v1 CSS不可变。新模板单独注册，不重译既有内容。发布先完成不可变产物再切换指针；未知付费结果不能当作未发送直接重试。
8. `contracts/implementation-backlog.json`定义依赖，`requirements.json`和`exit-gates.json`定义验收。保存环境、命令、commit、输出和失败；FakeProvider不替代真实Provider测试，YAML解析不替代Compose冷启动。
9. 按2026-09-07用户要求，产品预算/成本控制为可选项；新配置默认关闭，旧完整配置保留已启用行为。关闭允许无价格/无金额预算派发，未知金额用null显示未计算，网络未知结果仍禁止自动重发。应用默认input/output token上限为32768/8192、单元字符2000，显示有效值并提供仅限额重置；保留用户endpoint/key/model与已有自定义值。此产品配置变更不等于授权agent自行读取真实key或执行真实模型验收。

10. 按2026-09-07用户要求，所有语言均可使用，移除实验语言、额外语言确认、语言能力矩阵限制和强制手动发布。语言名称以各自语言显示，规范locale保留脚本/地区差异；现有来源确认、外发确认、质量检查和不可变历史规则继续适用。

11. 按2026-09-09用户要求，全部内容质量异常 non-blocking：自动解析、自动检查和确定性恢复后生成译文，异常集中提示，不以缺段、数字/公式/表格/代码差异或未人工校对阻止翻译、封存、发布、导出。缺页/大段遗漏按页恢复，复杂内容提供原图对照；所有任务留存实际模型、时间、时长与脱敏日志；优化全站 UI 文案；上传发现 DOI 并异步取得元数据，成功后文档库显示书目信息，失败保留文件名。NB-P01–P12 已于本轮实现并交付8080/schema12，实际范围及真实付费Provider NOT RUN边界见[交付验收](.agent/notes/nonblocking-20260909-acceptance.md)。执行以 [Spec](milestones/nonblocking-workflow-spec.md)、[Plan](milestones/nonblocking-workflow-plan.md) 和 [NB backlog](contracts/nonblocking-workflow-backlog.json) 为准，覆盖旧内容质量阻断和强制来源全文确认要求；实际执行故障、外发授权、秘密保护、fence/CAS 和不可变历史按真实情况处理。

首次执行提示：

```text
开始实施对照文库个人PDF版v3的M0。先阅读产品基线、共享架构/API/工作流、Compose契约与M0 Spec/Plan，检查当前仓库实际完成状态。按工作包依赖先创建退出测试，再实现生产代码；不要把演示原型标成产品完成。仅PDF、单实例、无身份/权限、仅Compose、无反代。遇到不可用的Docker或真实凭据等环境条件，记录精确阻塞并继续完成不依赖它的工作，但不得跳过相应退出门。
```

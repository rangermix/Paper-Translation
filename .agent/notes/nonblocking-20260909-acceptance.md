# NB-20260909 实施与交付验收

2026-09-09。NB-P01–P12 已完成，正式实例为 <http://127.0.0.1:8080>。本记录只认证本轮 NB 范围；不改写旧 M0–M2 的真实 Provider 或 release 验收结论。

内容质量异常已从执行许可中分离：自动解析、按页恢复和检查后可以继续生成、封存、发布和导出；不完整译文标为部分结果，缺失处保留原文或原图。新阅读模板为 reader-v3，旧阅读快照和 reader-v1 CSS 保留。任务详情增加真实执行模型、起止时间、时长和分页脱敏日志；上传发现 DOI 后异步取得书目信息，失败保持文件名。全站文案映射见 [copy map](nonblocking-workflow-copy-map.md)。

非法 AST、危险路径、资源哈希不符、CAS/fence 冲突、缺少外发授权及未知付费结果仍按真实执行条件处理。未知付费单元没有自动重发；旧 needs_review 任务须由用户选择继续，新执行保留旧结果。

## 验收结果与范围

所有运行证据位于 [`../tmp/nonblocking-20260909-a084be/`](../tmp/nonblocking-20260909-a084be/)。机器可读 NB 登记为该目录的 `nb-acceptance-report.json`，24 个验收编号均映射到实际证据。

| 验证 | 结果 | 证据文件（相对于本轮运行目录） |
| --- | --- | --- |
| 全部后端 unit/integration/acceptance | 976 passed、1 conditional skipped；跳过项随后在专用 PostgreSQL 补跑 1 passed，合计 977 个独立用例通过 | `backend-final.xml`、`backend-final.log`、`maintenance-final.xml` |
| 前端单元与生产构建 | 18 passed；Vite 构建成功 | `frontend-test2.log`、`frontend-p10final-build.log` |
| 12 组浏览器回归 | 103 passed、1 conditional skipped | `browser-final/browser-results.json`、`browser-final.log` |
| 最终镜像真实 CPU Docling | 成功，13.880 秒，自动发布 | `final-cpu-docling-result.json` |
| 最终镜像真实 CPU Granite Docling | 成功，34.326 秒，实际模型 ibm-granite/granite-docling-258M | `final-cpu-granite-result.json` |
| 最终镜像真实 CPU PaddleOCR-VL 1.6 | 成功，131.789 秒，实际模型 PaddlePaddle/PaddleOCR-VL-1.6 | `final-cpu-paddle-result.json` |
| 最终镜像受控 HTTP 翻译全链路 | 4 次本机合成请求：1 单元已知拒绝、3 单元完成；部分结果自动发布、两种导出成功、旧产物不变 | `final-controlled-translation-result.json`、`final-controlled-translation.log` |
| 真实公共 DOI | 仅发送 10.1038/nature14539，匹配 Deep learning、LeCun/Bengio/Hinton、2015、Nature；实际异步任务更新文件名展示 | `live-doi.json`、`metadata-cpu3-result.json`、`metadata-mobile.png` |
| 实际手机/桌面阅读与任务历史 | 原图加载、无横向溢出、Paddle/Granite 历史身份正确、日志可读 | `reader-original-open-mobile.png`、`final-history-mobile.png`、`final-history-desktop2.png`、`final-history-desktop.json` |
| 实际未完成草稿离线导出 | file 页面在网络请求被阻断时仍显示 DRAFT、译文、原文替代，无远程资源依赖 | `nb-draft-export.html`、`offline-draft-mobile.png`、`offline-browser-verified.json` |
| schema 12 备份恢复 | 3 文档、27 业务任务、7 公共文件及实际模型/时间快照不变 | `roundtrip-result.log`、`roundtrip-before.json`、`roundtrip-after.json` |
| schema 11 升级与旧备份恢复 | 2 旧文档与阅读产物原字节保留，恢复后前向迁移到 12，Provider hash 不变 | `upgrade-result.log`、`upgrade-restore12b.log` |
| 恢复故障原子性 | 在旧备份 SQL 末尾注入故障后，schema 重置和导入数据一起回滚 | `atomic-rollback.log` |
| 正式部署、整栈冷重启与保留性 | 4 服务 healthy；4 文档、29 业务任务、7 原 PDF/历史 HTML 哈希不变；369 条已结算请求不变 | `production-final.log`、`production-final.json`、`production-cold.log`、`production-release-ps.log` |

后端补跑项需要单独的 `ACCEPTANCE_DATABASE_URL`；原全量命令只设置了 `TEST_DATABASE_URL`，因此条件性跳过并非失败。浏览器跳过项依赖旧 reader-v2 专用导出夹具；本轮 reader-v3 的真实 API → worker 草稿导出已另外进行 file/offline 浏览器验证。浏览器 `navigator.onLine` 在该工具中仍返回 true，因此离线结论依据实际网络 fetch 被拒绝，而非该标志。

三种 CPU 验证使用同一份一页受控 PDF，只证明本轮集成、模型身份、执行记录和发布链路可运行，不代表长论文吞吐量或所有扫描件识别质量。PipeDream 缺页、缺栏和表格差异类型由独立受控样本与恢复测试覆盖，没有在生产中自动重译用户旧论文。

**真实付费 Provider 验收：NOT RUN。** 用户没有提供本轮真实模型测试预算与外发授权；没有读取真实 key，没有调用真实模型。本机 HTTP 服务无鉴权，只接收合成受控单元。公开元数据请求仅传 DOI，不上传 PDF 或正文。该边界是 NB-P12 的明确执行约定，不以 FakeProvider 代替真实模型认证。

## NB 验收映射

| NB 编号 | 已验证行为 | 主要定向证据 |
| --- | --- | --- |
| AT01–02 | schema/旧数据兼容；质量与执行分离；安全 AST/路径保持 | `p01.xml`、`migration-fix.xml`、`backend-final.xml` |
| AT03–04 | 创建/执行/结束/失败/取消/重试留痕；秘密过滤；历史不读当前配置 | `history-final.xml`、`receipts.xml`、`backend-final.xml` |
| AT05–06 | 页级聚合、区域去重；尚未检查/失败/无问题分别展示 | `p03.xml`、`browser-final/browser-results.json` |
| AT07–08 | 原生页证据修复、有界局部恢复、扫描/复杂内容原图替代 | `p04d.xml`、三个 `final-cpu-*-result.json` |
| AT09–10 | 缺段/差异/未确认/检查故障均可继续；局部失败保留；未知请求不重发 | `p05c.xml`、`pipeline.xml`、`continuation2.xml`、`final-controlled-translation-result.json` |
| AT11–12 | 阅读为主、原图定位、部分结果及离线资源保留 | `reader2.xml`、原图/离线浏览器证据 |
| AT13–14 | 全类型任务历史/分页/筛选、实际身份与时长、技术删除回执 | `history-final.xml`、`receipts.xml`、实际历史页面证据 |
| AT15–16 | DOI 候选、引用区分、换行/歧义/无 DOI、非阻断发现 | `p09.xml`、`doi1.xml` |
| AT17–18 | 官方 DOI 成功；404/429/超时/错配/并发改名/换源保护 | `p09.xml`、`live-doi.json`、`metadata-cpu3-result.json` |
| AT19–20 | 文案与后台状态相符、内部枚举和空值正确呈现 | 文案映射、`frontend-test2.log`、`browser-final/browser-results.json`、正式站点截图 |
| AT21–22 | migration/可信回填/备份恢复、旧产物和模型配置保留 | `upgrade-result.log`、`atomic-rollback.log`、`roundtrip-result.log`、`production-final.json` |
| AT23–24 | 实际 Compose、三 CPU、受控翻译、官方 DOI、最终镜像和冷重启交付 | 本表全部最终证据及 `final-images.json` |

## 正式实例与可重复启动

使用 `deployment/compose.production.yaml`；根 `compose.yaml` 是历史原型。PostgreSQL 服务和客户端均为 15.19，保留原 DB 镜像和命名卷。

| 服务 | 实际 Docker image ID |
| --- | --- |
| app / worker | `sha256:4ef2b473bcd22833b668e795874c325cd2520e1ac2667cb2697897bdb8da2040` |
| parser | `sha256:e46971ba5298a7ec56dab15f1ef8331057244a95ecf614e75ac491908affe2b0` |
| db | `sha256:efefd6aa424d56b4b48de904895ed8472585efaadb033814f7be1fa44c3c74f7` |

app/parser 标签为 `nonblocking-20260909-a084be`，两者 `local` 别名也已指向该版本。可从仓库根目录运行以下命令；helper 会先校验本机镜像身份，不读取密钥内容：

```powershell
& .agent/local-data/nonblocking-20260909-a084be/release.ps1 up -d --no-build
```

更新前由旧 schema 11 镜像生成备份 `backup_af6c17100d454bd38c88f4b41719aa06`，334 文件已验证；新镜像也成功重新验证该备份。备份位于正式实例原 `backups` 命名卷，Provider 密钥仍在原独立 `provider_config` 卷中，未纳入内容备份或读取。新镜像 schema 12 的运行数据验证成功。旧版应用不应直接连接已升级 schema 12；回退须在维护窗口使用相容镜像和升级前备份恢复，不能仅改回镜像标签。

正式配置 `profile_hash=d0871c31727c28f0177863e6c2c2417b5d6ff5d1d97058c682d75ea622abc61a`、配置/凭据 revisions 及已配置 key 标志均未改变；主题 dark、语言 zh-Hans、自动发布、Docling、7200 秒超时保留。维护操作使设置 generation 从 9 合理增加到 12。最终 maintenance=false、dispatch_disabled=false（恢复升级前值），unknown/inflight=0；旧 needs_review 不被自动继续，Permit 总数仍 369。

## 源码与失败证据

构建基准 HEAD 为 `3c74d769b785644bee39e8224bb3197bbeac0646`，本轮实现未提交。最终 app/parser 的构建标签记录该 HEAD 加 `-uncommitted`，源码指纹为 `4f9078400759498f3e06d888e4591a931109e533ed42ab3ec0872b049afdce88`；部署与冷重启时重新计算仍一致。随后只更新完成状态文档（AGENTS、NB Plan/Spec/backlog）和 `.agent` 交付笔记，不改运行代码。整体收尾后指纹会因此变化，不能把收尾文档状态冒充构建时内容；记录见 `completion-source-binding.json`。

中间失败全部保留：早期后端 916/53、147/24、92/9、971/5（通过/失败）以及旧浏览器选择器失败均在本轮日志内；已逐项处理并由最终回归覆盖。实际旧备份恢复最初受新增外键约束失败，现通过同一事务重建专用 public schema 并导入 SQL，故障回滚另有真实 PostgreSQL 证据。无新 xfail 或规避性 skip。

本轮独立测试环境关闭后保留其命名卷与备份，日志和截图不覆盖；正式实例及无关 Tracea 服务保持运行。全局旧 release 门未重新认证，不将本文用作真实模型或所有扫描件质量承诺。

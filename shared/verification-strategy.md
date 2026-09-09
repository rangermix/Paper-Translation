# 验收策略、测试语料与证据

## 1. 三种结果绝不混淆

**本规格包检查** 验证JSON/文档链接、范围一致性、依赖图和样例；**原型检查** 验证浏览器交互/视觉与演示边界；**正式产品验收** 验证数据库/实际PDF解析/真实Provider/Compose/故障恢复。前两项不能替代第三项。本包中的130个AT均为planned，24个gate均为not_evaluated。

## 2. 单元与契约测试

IR：重复块/无效parent/环/owner冲突、table网格、title重复、必译缺失、空目标、protected多重集合、literal source哈希、坐标边界、Unicode非BMP字符、非法AST/路径。

PDF-only：允许有效PDF输入；拒绝HTML/TXT/MD/DOCX/图片/URL/ZIP/JSON/双语/attachments；变更扩展名、MIME谎报、空文件、加密PDF与中断上传。Schema只验证输入描述，不以验证JSON代替检查PDF字节。

无身份：迁移不存在User/Workspace/Role/Session/ACL表，API没有对应端点和securitySchemes；正常业务请求不要求账号或token；HTTPHost/Origin和路径保护独立测试。

Provider：乱序返回按ID匹配、重复/未知/缺ID拒绝，输出截断/拒绝独立状态；64→32、单位量级、重复原子、否定/比较/限制词语义夹具。语义用例人工金标准，不以LLM分数代替。

## 3. PDF语料矩阵

| 语料 | 目的 | 预期 |
|---|---|---|
| 单栏纯文本、带标题列表 | 基础段落和层级 | 顺序/原文逐段正确 |
| 两篇已提供的研究论文 | 双栏、公式、图表、附录、引用 | 对照原件建新的解析金标准，不用旧译读英文当原文gold |
| 跨页段落/脚注/重复页眉 | 合并与排除证据 | 每页覆盖可核验，正文不漏 |
| 旋转页与CropBox | PDF坐标体系 | 页图与bbox对齐 |
| 简单/合并单元格/跨页表 | 表格结构与回退 | 可恢复则结构化，否则原图与警告；不伪造数据 |
| 扫描正文/混合PDF | 当前未支持能力 | OCR_REQUIRED阻断全文翻译，仍可存原件 |
| PDF动作/嵌入文件/外部资源 | 零外部获取 | 不执行、不下载、不派生新增源件 |
| 伪PDF/加密/解压资源爆炸 | 安全检查与限额 | 明确拒绝/任务失败，不影响API/db |

包内 `fixtures/sample.pdf` 是人工生成的有限样例，不声称代表任意复杂PDF；sidecar locator与源文本对应。全结构IR样例用于渲染契约，不是Docling准确率报告。

## 4. 集成与故障注入

上传半截、finalize重放、同名异内容、hash查重、DB提交前后杀进程、parser OOM/超时、spool旧fence输出、磁盘满、worker失联、已计费超时、取消/返回并发、重复结算、staging半写、manifest损坏、CAS和ABA、备份中GC、删除后的迟到输出和索引更新。每条断言都要体现“旧版可读/不复活/未知不重发/不会无限付费”的业务结果，不只检查HTTP200。

## 5. 浏览器验收

桌面1440×1060与手机390×844；覆盖上传/错误、预检确认、任务恢复、校对阻断、阅读与导出、局部候选冲突、版本回滚、术语、设置。原型保留既有paper/teal界面，阅读页CSS hash不变。正文禁JS可读，离线导出不请求模型/API/外部资源；验证实际图片和原PDF链接。

没有Browser/IAB时用Playwright+Chromium；若环境阻止file://或localhost，应记录，用受控本地文件响应/DOM装载做有限验证，不能伪称file://实测通过。截图比对检查五项以上：版式、颜色、文字层级、表格/侧栏、控件和移动折行；改动仅限用户要求的范围收敛。

## 6. Docker Compose验收

干净宿主仅Docker+Compose；rootless/权限受限条件实际测试后再声明支持。运行正式release而非原型：镜像就绪后断开包管理/模型仓库网络，解析冷启动无需下载；db没有发布端口，parser network none，无Docker socket/Provider secret。无密钥仍能入库/阅读；重建容器数据仍在；备份与恢复命令在容器内执行。

YAML静态结构正确不等于`docker compose config`通过；后者也不等于镜像能够build/up。本轮环境无Docker CLI时这两项均标未执行。release gate拒绝空digest/未锁定运行依赖；不能自行填假hash以通过。

## 7. 真实模型验收

M1至少一份已授权的小型en↔zh-Hans样例；M2新增语言需各有受控样本人工核对。仅在派发许可/预算/unknown机制完成后进行；测试预算由维护者显式提供。记录request_id、实际token/金额、不确定费用、输出hash、语义问题。缺少凭据则blocked，不能用演示段落代替。

## 8. 性能和验收证据

先固定硬件、语料、镜像与模型配置，再量化upload/parse/queue/provider/check/render各阶段。内部API和原件读取与供应商延迟分开。首屏/长文DOM性能按文档规模记录，超大文档可按章静态输出，但不得丢全文。

证据记录建议字段：requirement_ids、test_ids、git_commit、image_digests、fixture_hash、command、environment、actual_result、status(passed/failed/blocked/not_run)、evidence_paths、review_note。截图只证明视觉/交互；耗时或完整性结论必须有实际测量数据。不存在为了个人产品强制搭建多人审批系统。

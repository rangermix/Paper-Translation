> 当前工作：2026-09-09 NB-20260909 已完成并交付8080/schema12。P01–P12全部完成；后端976通过+1条件项补跑通过（977独立用例），前端18通过，浏览器103通过/1旧夹具条件跳过；实际reader-v3离线另测通过。最终三CPU解析、受控HTTP部分翻译/两种导出、公开DOI成功，schema11备份恢复/原子故障回滚/生产整栈冷重启通过。app/worker镜像4ef2b473bcd2，parser e46971ba5298，四服务healthy。4文档/29业务任务/7原PDF与历史HTML哈希/369已结算Permit不变；Provider配置与credential revisions不变，dispatch恢复原开启状态，maintenance=false、unknown/inflight=0。未读真实key/未调用真实模型；旧M0–M2真实Provider/release门不变。当前可信入口 `.agent/notes/nonblocking-20260909-acceptance.md`、NB backlog、`.agent/tmp/nonblocking-20260909-a084be/nb-acceptance-report.json`。可重复启动helper `.agent/local-data/nonblocking-20260909-a084be/release.ps1`；旧备份backup_af6c17100d454bd38c88f4b41719aa06及所有持久卷保留，未commit。

> 最新工作：2026-09-07 外部 API 请求允许/暂停已加入8080设置页 AI 服务区域，单独保存至PostgreSQL，不使用env；Compose移除DISPATCH_DISABLED。CAS/幂等/维护保护、未知费用确认与在途记账保留，开关不改Provider凭据、不自动重试未知任务。72后端+58浏览器+16unit通过，真实8080桌面/手机只改草稿且零写请求；未读真实key/未调用模型。app/worker同镜像229e22fc9b4f4918f2fde2c350c717bf69656ac97363f90fc6ffaf7101ab0609，local别名已更新，四容器healthy；公开配置绑定完全保持，dispatch仍暂停（generation8），unknown/inflight均0。QA DB/Vite已关闭。证据.agent/tmp/dispatch-settings-20260907-8e8a0cbd，说明.agent/notes/dispatch-settings-20260907.md。原真实Provider/release门结论不变，未commit。

> 最新工作：2026-09-07 已在8080设置页加入“测试 API 连接 / 密钥”。只测试已保存配置，确认后由worker发送一条固定Hello.合成单元，四协议复用生产adapter；使用CAS/幂等/预算与Permit，未知不自动retry，已结算但完成状态丢失也不重发。结果跨刷新保持，API key不回显；测试不改变语言认证或文档。156后端+53浏览器+16前端unit通过，两次真实loopback HTTP仅合成key；未读取或使用用户真实key。最终app/worker同镜像e5b590943b81b401bfcb4d407fb2928809d029cac074e0a618af53e7a7844700，均healthy，schema11；公开配置hash/revisions/派发状态与更新前一致。运行UI只开关确认框，零写请求；QA PG容器/网络已移除。证据.agent/tmp/connection-test-20260907-e9fb991b，说明.agent/notes/provider-connection-20260907.md；M1/M2真实Provider/release门状态不变。未commit。
> 最新工作：项目已从 bilingual-library-personal-pdf-v3/ 提升到 Git 根 C:/workspaces-local/Paper-Translation，旧子目录已不存在。代码、产品规范、fixtures、ops/tools 保持原相对层级；agent可复用工具在.agent/harness，记忆.agent/memory，笔记.agent/notes；运行日志/报告/截图/历史证据在.agent/tmp，持久环境/授权receipts/VM盘在.agent/local-data。后两者Git忽略，整个.agent不进入Docker。路径映射.agent/relocation.json；历史证据原字节不改，旧源码/image绑定不得冒充重组后当前树。
>
> 已修Python/JS root定位与输入输出路径，48项定向Python通过、165语法+6CLI通过；前端13unit/build通过，96浏览器用例仅收集，未重跑UI。51设计包检查通过，27gitignore正负检查通过，独立agent最终30项迁移审查通过。新根.venv由原3.12.12/uv0.10.7重建uv sync --frozen，激活及新pytest启动器正常，最终730用例仅收集；旧环境保存在.agent/tmp/environments；pytest/mypy缓存转.agent/tmp/cache。Git仅原LICENSE已tracked，其余仍保留未暂存状态，不擅自commit。用户明确不需要逐字节认证，不再做此类检查或将其作为完成条件。
>
> WSL历史BiblioCleanD99磁盘曾被System锁定，定向detach失败。用户明确允许中断Ubuntu后，已terminateUbuntu/shutdown共享WSL并用官方wsl --manage --move迁盘，登记路径现在.agent/local-data/wsl-hosts/BiblioCleanD99/ext4.vhdx。VHDX容器长度在受控shutdown/move后从10615783424变10585374720，未声称磁盘byte identical或重做boot认证。Ubuntu已重新启动默认shell（本次启动PID89904），Biblio保持Stopped。本轮最初Docker检查为零容器；不要沿用下方历史18088运行陈述。部署/实际模型行为本轮未重测。迁移记录见.agent/notes/repository-layout.md与.agent/tmp/repository-layout/。

> 最新工作：2026-09-07 可选预算/成本控制与限额默认值已完成并交付同一18088。新配置默认off，旧完整配置保留on，三限额32768/8192/2000显示有效值；重置仅三限额待保存，撤销恢复已保存值。关闭可不填price/budget，金额null显示未计算；网络未知仍停且不自动retry。708后端+73浏览器contracts+13unit通过，独立agents完成全部人工验证：18089实际24图与18088最终只读2图。QA18089的6容器/网络已关闭，8卷保留，18089/18189/19174端口关闭；18088保持健康。4次本机合成HTTP经过真实API/PG/production worker，缺usage仍完成且4新Permit金额null，旧2unknown保持；实际recreate/backup验证与密钥排除通过。没有真实模型调用。
>
> 18088原schema10镜像真实备份验证后升级schema11，仅换app/worker；原profile hash/config+credential revisions/destination hash/数据/flags保留，其余旧容器IDs未变。当前source7228dc737ecfba0b5dc1dcc8e636c43e7e7cb7205134545a702dedb78e71d1c7，Docker image e8cbaa3f78dfe596f6206accaaaea7aafbecad074597087a6723124f87275028，asset index-6muiN2d7.js。切勿把build config digest f7d3误作可运行imageID。入口 evidence/cost-controls/runtime-final-binding.json、notes/cost-controls-20260907.md、independent-delivery-review.md。旧runtime harness会改18088/18086，禁止复用；用户可能新增真实配置，不读key/不重置。全部原M0/M1/M2 live-provider gates及release状态仍blocked，历史126/130或其它旧镜像报告不认证当前新增代码。
>
> 证据更正：旧作者测试覆盖3份不可恢复Settings截图，独立历史链未触；保留旧报告并如实声明不可重验，不能引用新图为旧bytes。见 evidence/cost-controls/frontend/screenshot-overwrite-correction.json。新截图均隔离目录。

> 历史工作：2026-09-06 Gemini Interactions与Claude Messages原生支持已实现，设置可选四协议、endpoint/key/model/Claude版本，翻译与语义review用量接入现有账本。初版644全后端回归，最后请求ID小修后312相关回归，唯一case663；57浏览器contracts+13unit，独立12实际UI/20截图。真PG任务与本机6HTTP均无真实模型。最终source48c14807…/image20189925…见 evidence/gemini-claude/runtime-final-binding.json 和 notes/gemini-claude-20260906.md；独立收尾签名见 independent-final-delivery-review。新预览18088，当前无key/空model/dispatchdisabled；旧18086与8080全部保留（不要读取/重置用户可能新增的配置），原9容器IDs不变。上轮68ec、原d99的报告仅历史，不认证新增代码；真实Provider预算/外发与语言认证仍blocked。所有人工验证由独立agents完成，保留失败与不同镜像证据的实际范围。

> 历史工作：AI服务设置已实现，支持完整endpoint、Responses/Chat Completions、model ID、key保留/清除、显式免鉴权、价格/token限额及未完成配置保存。完整后端518 passed、前端43契约+13单测；独立agent实际浏览器6组及Compose持久化/3次本机合成HTTP/真实备份密钥排除通过。预览18086，旧8080未改；当前无key/空model/dispatchdisabled。最终source/image以 evidence/ai-service-settings/runtime-final-binding.json 为准，详见 notes/ai-service-settings-20260906.md。原d99的126/130与21/24报告仅历史，不认证新增代码；真实模型预算与外发授权仍未获得。

> 历史目标状态：2026-09-06 07:05 UTC 因真实Provider配置/预算/外发授权前提连续缺失而标记blocked。当前新增设置功能可以独立完成，不等于已解除真实Provider验收前提。

# 当前实现交接 · 2026-09-06 新宿主验证完成

M0已完整通过36个场景/7个退出门。M1/M2实现与已授权本地验收完成；真实Provider证据未获授权，整体目标仍未完成，未批准release。

- 冻结源码d99e5795269d6638306f897d964ba3e9d048af712796ec2390850a0f2041b7a6；镜像stable-20260906-050731。源码、tests、harness、fixtures保持冻结。
- 126/130场景passed、4blocked；21/24退出门passed、2blocked、1not_run；零拒绝证据。
- JUnit451 passed零fail/error/skip；UI29 passed零skip/flaky/unexpected。根独审225份记录（当前87份）及新host752proof，与当前130/24聚合完全一致。
- 新独立WSL rootfs/Engine/私有网络空间完成真正Docker-only冷启动、实际浏览器入库/阅读/导出、备份新卷恢复、原Desktop跨daemon恢复、4组42页冷解析。共享物理机/WSL2kernel、Compose5.5.1、无swapcap已明确披露。
- 新host M0-AT18A/M1-AT25A由Compose sealed2046c450直接绑定756文件，web d8acd706与IR38c4b556独立agent复核；所有已执行人工验证由独立agents完成。
- 全部新增产品/QA容器已移除，新daemon和BiblioCleanD99均已停止。20命名卷和10.6GB VHDX保留；原Ubuntu/Desktop/8080/testDB55439不变。不要启动WSL读取证据，Windows已有全部原始档案。

## 当前可信入口

- IMPLEMENTATION_STATUS.md 与 evidence/acceptance-report.json：最新状态。
- evidence/release/new-host-d99-final-audit.json：根最终source/全部record/752proof/451+29/聚合审计。
- notes/new-host-final-20260906.md：完整新host过程、实际边界、失败解释、agent职责与清理。
- evidence/new-host-runtime/stable-d99-BiblioCleanD99/completion-combination-v2.json：完整实际执行证据索引。
- evidence/release/stable-20260906-050731/request.json：原不可变3image/源码匹配。
- evidence/release/stable-d99e5795-security-summary-final.json：已扫描漏洞及native blindspot；未批准release。

## 唯一未完成的外部前提

M1-AT08A/08B/26A、M2-AT21A需要真实OpenAI验收。先前已请求：后端密钥文件绝对路径（不要密钥正文）、固定model ID、所有调用共用总预算（可US$1）、受控EN/ZH两份PDF的8文本块与相邻上下文外发授权；仍无回复。AGENTS.md§6适用，禁止自行取密钥、真实调用或换供应商。固定model后再核官方价格。已备好默认关闭的live harness和单次预算/授权receipt。

未授权前不重复已通过本地矩阵。新host阻塞已经消除；不得继续沿用旧124/6或“宿主不可用”的判断。源代码若需变更，必须明确原因并重新建立current证据，不能重新贴旧标签。所有后续人工/语义核对仍分配agents并使用文件交接。

旧报告/审计字节在evidence/release/pre-new-host-old-final-snapshot，上一版memory在notes/history-before-new-host-final-20260906.md。旧GATE_GAPS.md、旧final/local notes中的“当前”皆是历史；以本页和最新report为准。

## 完整真实验收范围补充 · 2026-09-06 07时前后

最新字面复核确认旧EN↔ZH runner只是首阶段，不具备完整负例/续跑/五语言对入口。M2-spec133另要求EN→ja/de/zh-Hant受控认证；仅填key运行两对不能完成M1/M2。

已准备 evidence/live-provider-closure-scope/authorization-proposal.json（approved=false，固定model/key路径/总预算仍为空）、closure-runbook.md，以及IR agent预写、web agent独审的12句三语参考和语义判据。参考不是实际Provider输出，不认证或启用任何新语言。preparation-check.json绑定全部材料SHA；source d99及126/4报告不变。

完整待批准外发范围仅原8受控块及其中相邻上下文、对应译文/候选/受控词表：EN↔ZH简体、EN→ja/de/zh-Hant，加真实配置负例。共享同一实例/账本的一次总预算，不为阶段或语言重置；unknown停止。后续需独立实际语义审阅、QA/seal/publish、冲突/回滚/offline累积流程。研究PDF来源纠错、100段锁、20文重建仍是明确分开的local-only fixture，不得把其内容外发。

旧首阶段外层--execute会新建project且只接受两对，不能用它再次执行来“续跑”；无虚构--resume。成功helper的全库all-settled断言与真实负例released permit不兼容，完整续链按runbook的实际API/每Job核账，在同一总预算内操作。模型能力负例需选定model后基于官方文档决定，不伪造错误等价。

本轮新字面差距证据改变了下一授权范围，并完成独立语义材料准备，故算progress；后续若仍无用户输入，不再反复准备同类材料或重跑本地矩阵。harness/memory/blocker-state.json记录最新状态。

# Optional budget / cost controls · 2026-09-07

用户要求：预算/成本控制可选，各token limits有默认值、输入框显示当前值、可重置。

root负责API4入口/worker协调/schema11升级/Compose交付；IR负责billing/config/secret-store与root代码独审及docs；web_ui负责前端与作者contracts；acceptance独立审IR后端及全部人工/实际浏览器验收。仍无真实模型调用或key读取，所有QA synthetic/真实隔离PG。

约定：profile.cost_control_enabled bool；新配置默认false，旧完整配置缺flag视true，旧未完成稿缺flag公开false。旧rawprofile及hash不重写，GET有效defaults为纯视图，保存新revision才填具体字段。新save遗漏flag/limits沿用已存effective值，幂等lookup先于动态继承，避免重放历史请求被错误判冲突。三默认：32768/8192/2000。metadata token_limits_defaults，reset前端只改三fields待原CAS保存，undo恢复当前已保存值。不改endpoint/key/model/price/switch。

关闭时4 API入口可省budget_micro，Job.budget_micro/Permit.reserved_micro为null（schema11只扩nullable、不改历史行），Permit仍持久化且price_snapshot明确costflag。有可用费率+用量可算实费，其他actual=None，不因金额不明拦合法输出。缺价/用量不等于网络outcome_unknown；后者仍停且不自动retry。原生model mismatch仍独立先unknown，不能用关成本绕过。显式retry保持原风险确认和冻结job已有外发确认；仅off可不填预算。统计任一桶含未计算金额则总值null，旧job/attempt已知金额仍可读；启用金额预算只约束控制开启时建立的Permit，不声称覆盖先前off支出或外部账户账单。

保护运行实例：18088已交用户可能有真实key，升级只换app/worker代码和nullable schema，不写provider_config、不清配置、不自动派发；备份/迁移与public哈希+key元数据做preservation检查。原8080与18086保持。实际写入QA在新18089隔离临时project/volumes完成。旧WSL不动。

初步验证：root17新workflow用例（4入口off/conditionalon/external、missingusage/modelmismatch/timeout、riskretry）与旧native/shared/migration合46pass。IRowned71pass，acceptance8独立APIpass；web新增16contracts+原57=73pass，13unitpass。完整后端目前后台运行。

证据事件：web作者测试旧固定screenshot路径触发旧作者截图覆盖；2native图已从独立exactSHA副本恢复，3旧Settings作者图无exactcopy。已保留旧报告/expectedhash，新correction声明这3图现不可复验（不能伪造替代原bytes）；独立actual历史链未触。详见evidence/cost-controls/frontend/screenshot-overwrite-correction.json。新测试已改隔离outputPath。

## 已完成的当前树交付

完整后端708 passed（516.68s，零fail/error/skip，2条既有依赖deprecated warning），含真实schema10→11升级测试。前端73浏览器contracts+13unit，tsc/Vite通过。acceptance独立8 settings+7 execution+16 frontend contracts；IR独立17 root workflow+4边界通过。独立actual18089的6设置检查与4个真实202入口通过，2 frozen unknown任务的金额/风险UI正确，24图已逐张目视。新入口尚dispatch disabled；语义fixture在后续同doc导入改变source后正确SOURCE_STALE，不把它写成Provider完成。

18088已原址升级并保留现有配置与数据：旧schema10镜像创建并验证实际备份，再升schema11并只换app/worker。profile_hash、config_revision、credential_revision、key presence、destination digest、preferences hash、1doc/0job/0task/0attempt/0permit保持，maintenance恢复false/dispatch仍true；其他全部preexisting container IDs保持。新app be7fe9b7…/worker022170dd…均健康，db/parser未重建。没有PUT设置，没有读取Provider secret文件。当前公开effective cost=false与32768/8192/2000是视图默认值，旧raw profile/hash未重写。

准确source=7228dc737ecfba0b5dc1dcc8e636c43e7e7cb7205134545a702dedb78e71d1c7；可运行Docker image/RepoDigest=e8cbaa3f78dfe596f6206accaaaea7aafbecad074597087a6723124f87275028。初次root消息误把build的config digest f7d3当imageID，acceptance实际inspect纠正，尚未执行的两个脚本常量已修后经IR补充独审，才执行升级；不是运行镜像中途变更。原始记录及更正见image-identity-correction.txt。前端index-6muiN2d7.js SHA2f04e76908372ea76d4cc628dad0b5db21238dbbe32d9d84de2cbfab35521dd6，与18088HTTP字节相同。

关键证据：evidence/cost-controls/runtime-final-binding.json、user-upgrade-final.json、independent-ui-review.md、independent-root-workflow-review.md、independent-implementation-review.md。原.local-data/native-providers/env.ps1仅APP_IMAGE改为新不可变ID，完整旧env复制在.local-data/cost-controls/native-env-before-upgrade.ps1。不要使用历史native/provider-settings runtime harness写18088或18086；新的QA必须新隔离项目。完整M0/M1/M2 goal/live Provider验收与release状态保持原blocked；本次设置功能完成不改变真实模型授权边界。

最终独立18088只读桌面/手机验证通过（2图目视、0writes/外发/浏览器错误，前后public metadata完全相同），见independent-delivery-review.md。新18089 smoke实际4本机HTTP（Responses/Gemini各candidate+semantic），由真实API创建、PG任务和production worker实际adapter调用；缺usage但4新Permit settled/actual=None/reserved=None，旧2unknown逐字段保持，既有目标译文不变。实际重建配置持久化、备份6文件/141DB行密钥排除通过，见runtime-runs/20260906T150733Z-e4a3eb56/result.json。此测试没有真实模型、没有语言质量或实际收费认证。

QA清理已完成：只移除bilingual-cost-controls-20260907的6容器与网络，8命名卷保留；18089/18189/19174端口均关闭，其余容器IDs保持，18088 schema11 ready。清理证据qa-cleanup.json。open_in_codex打开设置请求返回queued，不能声称已强制刷新用户tab；用户刷新原18088即可取得新asset。

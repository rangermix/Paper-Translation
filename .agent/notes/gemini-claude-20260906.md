# Gemini Interactions / Claude Messages · 2026-09-06

本轮用户追加两种原生API；原M0/M1/M2目标blocked状态不变。无真实密钥读取、无付费模型调用，设置功能与协议实现独立验证。

## 分工与文件交接
- root：protocol registry / immutable native HTTP / config / billing / execution / Settings API / real PostgreSQL integration / runtime smoke。
- ir_publisher_parser：Gemini pure adapter42tests；独立Claude与root共用层审查。报告 evidence/gemini-claude/independent-shared-native-review.md。
- acceptance_harness：Claude pure adapter38tests；独立Gemini审查、最终实际浏览器/截图（evidence/ai-native-providers）。自己实现的Claude由IR独立审查。
- web_ui：设置协议/鉴权/Claude版本、四个外发目的地隐私说明、57浏览器contracts与build；独立实际QA由acceptance。

## 实现约束
四协议：responses/openai/bearer，chat_completions/openai/bearer，gemini_interactions/gemini/api_key，claude_messages/anthropic/api_key。所有协议支持显式none。原生调用使用完整endpoint，不拼接、不回退、不重定向，无SDK内置重试。Gemini x-goog-api-key；Claude x-api-key + anthropic-version，默认2023-06-01，用户可编辑合法日期。普通API key范围，不增加OAuth、云供应商鉴权或多workspace身份。

Gemini stateless store=false；Claude Messages无此字段，不伪称零留存。只发送确认文本/受限上下文/词表，原文与网页由既有路径管理。现有源文保护及翻译/语义review schema沿用。

Gemini current steps/model_output/content响应，input含cached子集，output+thought合并计费，须有完整6整数计数并守恒；缺失可选字段也保守unknown，不默补0。Claude input=普通input+cache_read+cache_creation，output已含thinking；cache_creation/servertool/iterations额外收费不猜价，进入unknown。非空拒绝结算已知usage后needs_review，不repair或fallback；空拒绝文档计费语义不一致，billing_unconfirmed。响应model缺失/不同为PROVIDER_MODEL_MISMATCH，保留已知usage但unknown且不产译文；Gemini仅models/前缀等价。应填服务实际固定model ID，不猜dated alias。

Gemini官方Interactions文档未明确证实max_output_tokens与thought共用上限；本轮不做真实预算边界认证。actual完整usage结算，reserve超限停止后续调用，不能声称硬保证本次真实调用不超cap。当前3rate线性价格需要用户核对，不填模型/价格默认值。

## 已处理失败
- 独审4case模型返回不匹配仍可结算：真实代码缺口。root补immutable model+响应比较；原4probe不改复验绿，再加4positive/binding和4PG负例。
- native-expanded-first.xml 1fail/45pass：测试错误假定未填endpoint的草稿会返回endpoint字段，实际正确是字段省略且missing_fields含endpoint。修正测试预期，未给草稿发明URL。
- 两原生pure adapters初始red与具体后续fixture失败保留各agent报告，不统称production缺陷。

## 运行边界
旧8080、旧18086两个项目完全保留，尤其18086已交用户可能有真实配置，禁止本轮写/清空/重建。新项目bilingual-native-20260906，端口18088，镜像native-20260906，独立空provider_config/DB卷，DISPATCH_DISABLED=true。测试DB55439只unique schema。新本机HTTPfixture18188，6实际请求（Gemini与Claude翻译/review+Claude免key）；不是产品Job或真实模型证据。真实PG任务与账本另有integration tests。

runtime脚本 harness/verify_native_provider_runtime.py；旧harness/verify_provider_settings_runtime.py硬编码18086，不可本轮运行。部署env在.local-data/native-providers/env.ps1（无凭据）。正式source/image/独立QA最终证据待当前运行完成补记。

## 当前验证结果（收尾中）
完整后端 tests 当前644 passed / 0fail / 0skip（581.14s），证据 evidence/gemini-claude/backend-full-current.xml。前端57实际Playwright但API均mock的contracts、13Vitest单测及tsc/Vite build通过；这里的“实际Playwright”不代表真实模型调用。

新Compose首次startup及runtime smoke通过。source 99b06bbacc1799ae386e69468cc747559340ee3c4238d346f5811930b08588af，app/worker镜像sha256:4dcfcfc2183100f297370289d32412210e3a46124270e227ec067f10ba0d2a3d，web index-xIGlNiTn.js。IR独立核12个image内生产文件与当前源码SHA一致，原9个容器IDs全保留；provider_config appRW/workerRO、parser无网、secret metadata边界实际验证。

6次容器→Windows本机HTTP分别Gemini key翻译/review、Claude key翻译/review、Claude none翻译/review。Gemini none另在MockTransport+真PG测试覆盖，不宣称实际容器Gemini none。fixture临时绑定0.0.0.0:18188以供Docker访问，已实际socket检查闭合；不是网络隔离证据。配置实际重建持久化，pg_dump+verify-backup及pg_restore导出SQL扫描无synthetickeys；无另库恢复声明。其時0Job/Permit，仅adapter smoke，PGtasks计费靠独立integration矩阵。

独立真实UI最后通过12checks，最终run evidence/ai-native-providers/independent-ui/2026-09-06T13-39-23-285Z。无route mock、只新18088设置API写入、6处目的地只读展开（两protocol×edition/candidate/semantic）；import第4种入口两protocol另有独立mockcontracts覆盖。人工seed_editor源文/译文与空ja Edition只为展示，不是PDF解析/翻译/语言认证。第一次失败是有draft时不显示开始翻译按钮的测试假设错误；第二次是共享Page保留candidate弹窗挡住semantic点击。均修脚本/fixture，未改产品，原2次失败目录保留。最终截图由acceptance独立目视，root不自签视觉QA。

## 最终修复与交付绑定
收尾新增真实缺陷：服务返回id={}或201字符request-id时，PostgreSQL分别无法adapt dict或超出String(200)，导致合法usage结算事务回滚。root在NativeProvider共用层仅规范化可选request_id（非非空ASCII可打印str、超过200均置None；不截断、不改usage、不发明ID）。这不变更协议请求、Settings API或前端。IR原2真实PG负例原样复验通过，再独跑17unit+2PG新例。见 independent-native-request-id-finding.md / -fixed-review.md / post-tracking-files.json，旧失败和旧17file签名保留，有意变化仅native.py及两测试文件，其余14项未动。

最后完整644回归在此小修前；最终312相关回归（全部unit及受影响native/Settings/dispatch PG/API）通过，两批唯一case合计663，不宣称最终全套663重新执行。前端57contracts/13unit、12实际UI/20截图的源码和asset字节完全不变；实际6HTTP与备份证据仍绑定首镜像，最终镜像由source/具体文件及增量测试复核，不覆盖首次结果伪称重跑。

最终source=48c148078506e5ec09b53d91009a5edd7001c4867d0d1c89349585df12c3046e；app/worker image=sha256:201899259be198c955ad7fa12bdf018ff9ce76571421f48ab91f63f0eca686f0；web仍index-xIGlNiTn.js (190cc7a731670699273047c101a60c20f7593e2c14c64415ad46e7a0475a6b6e)。evidence/gemini-claude/runtime-final-binding.json为本轮可信current入口，包含current Compose、全部证据文件SHA、旧9个容器IDs、当前无key/空model/dispatchdisabled、0Job/Permit以及11个历史syntheticsecret文件仅metadata检查（0600/uid10001，无内容读取）。不删除历史已绑定synthetic版本；清除的是当前配置。测试数据明确为本机受控fixture，未改8080/18086任何配置。

最终证据收集器首次误向capabilities查询dispatch_disabled（KeyError），实际该字段属于settings/provider，已改收集器，生产代码不受此错误影响；原诊断见 final-binding-first-failure.json。

模板reader-v1CSS 51dacbcd96a21214ed83a62cad870a6281eb20db1aa260f3a7d782c58fdd18a8不变。19173临时Vite和18188临时HTTP已关闭。原预算/外发授权阻塞与语言认证缺口不变；新增原生API支持不是完整M1/M2认证或release批准。

最终独审已通过并结束：evidence/gemini-claude/independent-final-delivery-review.{json,md}。IR核当前source/image与100个binder文件SHA、50个UI证据和posttracking绑定；JUnit644+312重叠293、唯一663的声明精确；旧9服务/当前0JobPermit/11key metadata/readerCSS/关闭listener均验证。未读key或再次reset。18088设置页已请求Codex打开（tool queued），之后用户可能填新配置，后续不得按本轮清理脚本重置。新增原生协议功能可交付，原完整里程碑真实Provider gates仍blocked。

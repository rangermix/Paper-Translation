# 当前实现交接 · 2026-09-06

本地实现与可执行验收已完成；完整 M0/M1/M2 退出门尚未全部通过，不能宣称已完成认证或批准发行。

- 冻结源码：`d99e5795269d6638306f897d964ba3e9d048af712796ec2390850a0f2041b7a6`；候选镜像标签：`stable-20260906-050731`。
- 130 个场景中 124 passed、6 blocked；24 个退出门中 18 passed、5 blocked、1 not_run（M2-G04 缺真实 Provider 证据）。M2-G08 累计完整流程的 browser/live_provider 证明也随外部条件保留未完成。
- 当前完整 pytest：451 passed，0 failed/error/skipped，434.344s；前端交互合同：29 passed，0 skipped/flaky/unexpected。
- 20 个本地通过的 mixed 场景各有独立子 agent 审查；执行者、审查者、命令、输出、文件哈希与失败记录均已留存。其余 mixed 场景由外部条件阻塞，不伪造人工通过。
- 已真实执行当前镜像的四组 PDF 解析、原文校对、完整浏览器流程、预算/并发/未知付费结果、发布中止、schema5→10、3/10断点恢复、离线导出、损坏文件与备份拒绝、删除与恢复流程。
- 两处末轮 UI 问题（legacy定位限制提示、语义源文/译文摘录）均在冻结前修复并通过新镜像原失败数据复验。

## 可信入口

- `IMPLEMENTATION_STATUS.md` 与 `evidence/acceptance-report.json`：当前状态，只以当前源码的实际完整证据判定。
- `evidence/release/stable-d99-final-local-audit.json`：最终本地证据审计。
- `evidence/release/stable-20260906-050731/request.json`：不可变 app/parser/db 镜像和实际容器源码核对。
- `notes/stable-freeze-20260906.md`：执行索引；各 agent 的 notes 和版本化 map 记录详细边界。
- `evidence/release/stable-d99e5795-security-summary-final.json`：实际漏洞扫描；OS Critical/High 与 native FFmpeg OpenSSL1.1.1k 残留已披露，未批准 release。

## 未完成的外部前置条件

1. 真实 OpenAI 验收需要固定 model/profile/价格、后端密钥文件绝对路径、全流程共用测试预算，以及受控 EN/ZH 两份 PDF 的8个文本块及相邻上下文外发授权。先前请求未获回复；不得读取密钥或执行真实调用。AGENTS.md 第6条继续适用。
2. 需要可用的独立干净/新 Docker-only 宿主机；同一主机的新 Compose 项目/新卷只能证明该局部恢复流程，不能替代新宿主机验收。此前 Hyper-V 探测被拒绝，无 QEMU/VirtualBox；既有 WSL/8080 未动。

阻塞场景：M0-AT18A，M1-AT08A/08B/25A/26A，M2-AT21A。不得用 FakeProvider、历史镜像、模型自评分或新卷冒充这些证据。

## 恢复工作规则

所有生产代码、测试、harness 与 fixtures 保持冻结。只有获得上述真实外部条件后，才执行对应已准备的验收，不重做已通过的本地矩阵。若确需修改 tracked 文件，先记录原因并重新建立对应当前源码证据；不得给旧记录换标签。所有人工/视觉/来源/语义复核继续分配独立 agents，使用项目文件传递上下文。

此批临时验收实例均已关闭，命名恢复卷保留；原 localhost8080 与测试 DB55439 保持原状态。历史交接保存在 `notes/history-before-final-stable-d99.md`，其中旧“当前”或“待修”文字均为历史。

---

# 历史检查点（已由上文取代）

Current freeze: 2149861aa7c8cb4f5e92225fa2b7a1f2ebc7016e5c94b2f03ff209300244b29c; literal-final-20260906-042500. Product resource guard is cgroup <=4 GiB with no RLIMIT_AS. Earlier c3e/9a and836 wrappers/images are historical. Current final suite/new images/new browser/Compose in progress. Real Provider and clean-host proof remain unavailable.

# M0–M2 implementation and verification checkpoint

This is a working delivery checkpoint, not milestone completion or an approved
release. The source freeze recorded below is historical: subsequent literal
acceptance found a same-column ordering defect and an overly restrictive parser
virtual-address ceiling. Both have scoped fixes and independent verification;
additional full workflow tests are passing. See `notes/root-implementation.md`
for the latest state. New image builds and final certification are pending the
last controlled two-column source/UI scenarios. The earlier frozen source was
`836a3322356bcdd41ae984d293497744c780c3d0447058641dff24b6d22f7e41`.
The git checkout remains uncommitted; no branch was published or merged.

## Implemented product scope

- M0: PDF-only resumable storage, restricted inspection, metadata/library/original
  reading, immutable IR and publication/export, preserved reader-v1 CSS and legacy
  seeds, Compose deployment, integrity health checks and backup/restore.
- M1: isolated offline Docling/native parsing and preflight, frozen Provider
  profiles/consent/budgets, durable work leases/attempts, strict translation units,
  persistent cache, conservative unknown-payment recovery, QA and publication.
- M2: original-page source workbench and evidence-bound mechanical corrections,
  immutable editorial history and review invalidation, glossary/local candidates,
  optional semantic issue review, explicit experimental locales, safe publication
  rollback, zero-model template rebuild, search/TM/bookmarks and deletion cleanup.
- Harness: independent agents own formerly manual source/visual/review checks;
  project notes record ownership, failures, commands and next actions. Execution
  records include source/environment/command/output hashes. Fake/MockTransport
  tests never substitute for actual Provider or original-source gold.

## Current verified executions

- Complete local suite: **385 passed, zero failures/errors/skips**, 364.885s.
  Wrapper 371.015s, source unchanged. JUnit:
  `reports/core-evidence/final-frozen-local-385.xml`; execution:
  `evidence/runs/20260906T030536142133Z-final-frozen-local-385-20260906-75d611ac.json`.
- An independent reviewer mapped 36 conservative automatic AT predicates to exact
  nodes/parameters in that run. Every node was present and passed:
  `evidence/reviews/final-385-node-registration-verification.json`.
  Current independent review certificates were separately imported; this does not
  certify unrelated browser/Compose/Provider requirements.
- App: `sha256:08761c5178032a30fd449a3dd8d89926a273823d8a84c8a9307bdc7792eb547f`.
  Parser: `sha256:575600235b826a32b97483eac5de6c5d3358667a0be8af1363467aafdce30a10`.
  Both tags end `final-review-20260906-025940`; running-container source/lock hashes
  match the frozen tree. Database remains the unchanged
  `sha256:04a249fe1c97c960a51b8630d0cec6b82a9a8ee87a78933c1e15bccbd669ff2a`.
- Actual final-parser cross-page PDF inference without source overlays:
  `evidence/cross-page-table-runs/94c42de4`. Both table pages and captions are
  retained; uncertain graphic grouping retains original images and explicitly
  requires source review. This is a conservative blocked-preflight success, not
  complete automatic graphic grouping or source-gold certification.
- Actual final-image offline Compose startup, upload, four legacy worker exports,
  referenced-PDF corruption/health recovery, backup and fresh-volume restore:
  `evidence/offline-compose/runs/bd6c7ddf/roundtrip.json`, 89.735s. All networks
  internal, no Provider calls, both temporary projects removed and volumes kept.
- Exact image SBOM/license/vulnerability evidence:
  `evidence/release/final-836a3322-image-manifest.json`. App/parser each have 3
  critical and 51 high OS findings; unchanged DB has 13 critical and 73 high.
  The scanner reports no fixed versions for those C/H entries and no application
  dependency findings. Native bundled OpenSSL linkage limitations remain disclosed;
  these are not vulnerability-free or release-approved images.

Earlier actual process-fault and source-gold evidence remains valid for its
recorded snapshots/images, not silently relabelled as final-image executions:
`evidence/translation-resume/6f605985`, `evidence/unknown-risk-ui/0f46c074`,
`evidence/schema-upgrade/9c6afc0d`,
`evidence/reviewed-source-pathways-1788658073125877700`, and
`evidence/efficient-native-final-1788660392870495400`.

## Still required

1. **Real Provider authorization/configuration**: the single prior request for a
   backend key-file path, fixed model/profile, total budget and controlled-text
   external-processing approval has no reply. No genuine Provider call occurred.
   Scope is the eight text blocks and neighbouring context from the two controlled
   PDFs in `fixtures/live-provider/manifest.json`, for translation, candidates and
   semantic issue checks. The default-off harness does not execute without approval.
   AGENTS.md rule 6 explicitly requires budget and external-processing confirmation.
2. **A clean Docker-only host**: Hyper-V read-only discovery was denied by current
   Windows permissions. Existing WSL distributions were not modified. Isolated new
   Docker volumes on this host do not establish the clean-host literal requirement.
   Exact probe: `evidence/reviews/clean-host-capability-20260906.md`.
3. **Current image observations and remaining formal gate records**: the preceding
   final-image UI three-scenario run passed with independent signatures, and the
   dedicated instance was shut down. New compound browser rehearsals have passed;
   they will run once more after the current parser fixes are built. Many earlier scoped scenarios have real evidence but lack
   a complete current-tree certificate. See the generated
   `IMPLEMENTATION_STATUS.md` and `evidence/acceptance-report.json`; `not_run` is
   not an assertion that the corresponding implemented feature is absent.

Do not set the goal or M0/M1/M2 release status to complete while these requirements
remain. Do not turn old partial records, Fake responses, or image build success
into missing gate passes.

# 新宿主验证完成与最终交接 · 2026-09-06

## 实际当前状态

M0全部36场景/7退出门通过。M1/M2实现和已授权本地验证完成，但完整退出门仍需真实Provider验收，不能宣称整体目标完成或批准发行。

当前130场景126 passed/4 blocked；24退出门21 passed/2 blocked/1 not_run。剩余 M1-AT08A、M1-AT08B、M1-AT26A、M2-AT21A。当前源码d99e5795269d6638306f897d964ba3e9d048af712796ec2390850a0f2041b7a6，HEAD3c74d769b785644bee39e8224bb3197bbeac0646，原dirty状态保留；未提交、推送或发布。

根最后独立重算225份历史/当前证据（当前87份）、全部752组合proof文件、130场景/24门聚合，零拒绝。原JUnit451 testcase零失败/错误/跳过；UI29 expected零失败/flaky/跳过，再次核对的是既有证据，不重跑测试。完整审计：evidence/release/new-host-d99-final-audit.json。

## 本轮新增证据

- 新WSL2发行版BiblioCleanD99具有独立ext4 VHDX、独立Engine27d192f4-781d-4c84-9ec4-64adc6319e3d及私有netns4026532891。原用户WSL网络4026531840/Desktop4026532231未修改。
- 目标宿主实际没有19种Python/Node/qpdf/Postgres/Docling/OCR/CUDA运行工具。实际Alpine3.24.1、Docker29.8.0、Compose plugin5.5.1。明确共享物理计算机和WSL2内核；不是第二物理机，也未声称实跑Compose2.x二进制。
- 加载前0image/container/volume；3个产品image传输SHA及完整Config/RootFS/ID/架构一致，115源码文件独立核对。只有产品4常驻Compose服务；QA Node/Chromium是临时独立工具容器内依赖，直接HTTP，无反代、无hostPython。
- 真正空库浏览器上传、2份legacy seed幂等、4个新worker导出/16浏览器视图、app重建持久性、57文件M0备份到新PG/data卷恢复、原Desktop旧schema5备份跨daemon恢复11原文件/schema10通过。
- 普通worker在维护状态仍不派发；恢复后只执行本地index恰一次。未知80000micro、原Permit1和原Attempt/evidence完整保留；所有真实supplier request_id/usage0。这是明确的合成账本恢复fixture，不是实际供应商调用或支出。
- 主产品API→worker→spool实际controlledEN解析4块。进一步4个新隔离parser容器冷解析双栏/跨页资源/Efficient18p/Pathways20p；42页PNG和所有源资产与冻结actual字节一致，inspection/coverage一致。raw论文仍含源校对阻断，不冒充人工gold。
- 各解析容器新/tmp缓存，模型前后hash正确，memory.max4GiB/pids128，无RLIMIT_AS，0OOM；WSL memory.swap.max=max，不声称限制swap。
- 212个cold原始文件通过目标nativeSHA和Windows原字节双重独审。内层cold-result对4个外层run.stdout的hash是采样时前缀，保留未改；最终日志由封存212清单核实，未放宽payload/assets校验。

## 独立 agents 与正式登记

- /root/acceptance_harness：Compose阶段、原备份复制/恢复、正式因果组合；最终sealed2046c450直接绑定752proof+manifest/原receipt/log/封存脚本共756文件。
- /root/web_ui：真实QA容器initial、legacy、restored_m0、restored；原图人工视觉和原dump核对；完整18A/25A独立证书d8acd706。
- /root/ir_publisher_parser：新rootfs/空Engine/115源码/模型/cgroup/网络、held/resume只读SQL和11文件、cold212文件、最终环境；完整18A/25A独立证书38c4b556。
- 根：新OS/独立daemon、镜像二进制传输、实际4cold运行、关闭清理、最终哈希聚合审计。

原浏览器失败ecf483f6以及旧expected request_count0保留。两agent分别从原Desktop只读备份pg_restore确认1Permit/request_idNULL；JobAPI按Permit计1而运维helper按非空request_id计0。独立v2预期与完整重跑cefb7ebc验证全字段不增加，产品未改。最初组合文字误称Debian，旧record7b629e72保留；v2实际Alpine3.24.1由正式sealed2046c450绑定。

## 已清理与未完成条件

所有自建新host产品/QA容器均已退出并移除，20命名卷保留。根按实际PID/namespace/EngineID验证后SIGTERM，只终止BiblioCleanD99；VHDX10,615,783,424bytes保留。exec29375/83212均完成。最后WSL清单：BiblioCleanD99 Stopped，Ubuntu/docker-desktop Running。原8080和测试DB55439维持运行，未global shutdown/unregister/prune/删除卷。完整证据已取回Windows，不要为读取证据重新启动distro。

真实OpenAI验收的早先用户输入请求没有回复：后端密钥文件绝对路径（不要密钥正文）、固定model ID、共同总预算（先前建议US$1），以及受控EN/ZH两份PDF的8文本块与相邻上下文外发授权。AGENTS.md§6和verification-strategy§7要求预算/外发确认，未获授权不得读取真实密钥或运行live --execute。模型价格可在固定model确认后核官方信息。

本轮完成了新的实际环境验证，不能把它算作无进展阻塞轮。完整goal仍active/incomplete；不要假报完成，不因新增本地证据而放行缺失真实Provider的退出门。

旧124/6报告与旧finalaudit在evidence/release/pre-new-host-old-final-snapshot逐字节保存；旧harness/GATE_GAPS.md属于冻结源码历史状态，本条与当前报告明确supersede其中“新宿主不可用”的判断，未改tracked文档导致证据失效。当前入口是IMPLEMENTATION_STATUS.md、evidence/acceptance-report.json和new-host-d99-final-audit.json。

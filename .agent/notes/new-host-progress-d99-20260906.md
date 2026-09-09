# 新 Docker-only 主机验收进展 · 2026-09-06

本条更新 supersedes 早前 current.md 中“新宿主不可用”的环境判断；尚不提前把完整场景标为通过。

- 新建 WSL2 发行版 BiblioCleanD99，从官方 Docker 29 dind 文件系统导出并导入独立 ext4 VHDX；未运行 privileged dind 容器。
- 独立 Engine ID 27d192f4-781d-4c84-9ec4-64adc6319e3d，Docker29.8.0 / Compose plugin5.5.1，明确共享物理计算机与 WSL2 kernel。它不是另一物理机。
- dockerd PID9 位于新私有网络空间4026532891，无默认路由/uplink；默认共享 WSL 网络4026531840及 Desktop4026532231未改变。不能把普通新Compose卷当作本次新OS宿主证明。
- agent /root/ir_publisher_parser 实际独立读取：加载前0镜像/0容器/0卷，19种宿主应用运行工具不存在，Unix socket FD归属于新daemon，数据根位于新rootfs。
- 源码 d99e5795269d6638306f897d964ba3e9d048af712796ec2390850a0f2041b7a6 不变，app/parser/db 的归档传输SHA与目标镜像Config/RootFS/ID/架构全部一致。
- doctor通过115个镜像内源文件核对；m0-start四服务健康。agent /root/web_ui 已真实执行空库上传、原PDF字节核对与4张桌面/手机截图检查；后续读取/导出/重建/恢复仍进行中。
- 浏览器QA容器为独立验收工具，image sha256:b8a2c3c2b8b1dbfb07eb2eb5267a68f0f9f4581790717bcf82cd83189ebea07f。Node/Chromium都位于该工具容器内，通过newdaemon host网络直接HTTP访问app，不在宿主安装脚本依赖，不增加产品长期服务或反代。
- /root/acceptance_harness负责stage编排、备份搬运和正式组合记录；/root/web_ui独立浏览器；/root/ir_publisher_parser独立环境/镜像/网络/限额/模型核查。全部命令/失败/截图/哈希落盘。
- Windows UNC传输不可用，使用wsl stdin/stdout二进制tar并验证SHA；Windows控制器Python不是目标宿主依赖。
- 实际限额需区分memory.max和WSL NoSwapLimitSupport警告。原localhost8080四旧容器保持不动。
- 持续运行的exec session29375是新host daemon，所有stage及末轮审查/证据导出完成前不可关闭。最终仅停止自建新host项目，保留恢复卷/VHDX，不全局shutdown/unregister/prune。
- 真实Provider前置输入仍未收到：后端密钥路径、固定model/profile/价格、共同预算、受控EN/ZH8块及上下文外发授权；AGENTS.md§6适用。不得读取密钥或执行真实请求。

证据入口：evidence/new-host-bootstrap/stable-d99/；evidence/new-host-independent/；evidence/new-host-runtime/stable-d99-BiblioCleanD99/；evidence/new-host-browser-runs/。

# 对照文库 · Paper Translation

单实例个人 PDF 文库，提供 PDF 上传、内容提取、翻译、双语阅读、译文编辑和离线导出。应用直接通过 HTTP 提供服务，使用 Docker Compose 部署，没有账号或权限系统。

## 启动

从仓库根目录执行。首次部署复制共享模板；已有 `compose.yaml` 时保留现有配置：

```sh
cp compose.example.yaml compose.yaml
docker compose build app parser db
docker compose up -d --wait
```

打开 `http://127.0.0.1:8080`。`compose.example.yaml` 是唯一受版本管理的 Compose 模板，默认启用 CPU；CUDA/MLX 通过复制文件中的注释块选择。根目录 `compose.yaml` 是 Git 忽略的本地配置，保留已有实例设置。详见[部署说明](docs/deployment/README.md)。构建会取得锁定的依赖与解析模型，运行容器不安装依赖。默认只绑定本机地址；能访问服务的客户端均可操作文库。

## 使用

上传 PDF 后可以先保存和阅读原件。设置页选择解析模型、设备和超时，保存翻译服务配置并明确确认内容处理后开始翻译。只完成解析的文档提供继续翻译入口，不会被标为已翻译。

支持 OpenAI Responses、兼容 Chat Completions、Gemini Interactions 和 Claude Messages；也可部署[本地 MLX 翻译](docs/deployment/local-translation.md)。服务地址和 model ID 可编辑，密钥只保存到后端文件且不回显。保存配置不调用模型；连接测试和翻译需要单独确认。金额控制默认关闭，可按需启用；未知费用显示为未计价，未知请求结果不会自动重发。

内容质量提示不阻止翻译、封存、发布或导出。系统执行自动检查与确定性恢复，无法可靠恢复的内容保留原文或原图供对照。作者、机构、标识符和参考文献等可识别的学术元数据保留原文。人工核对可选，所有语言均可选择。编辑、来源修正、发布和回滚保留不可变历史。

详细行为见[产品范围](docs/product-baseline.md)和[工作流](docs/workflows.md)。运维见[备份与恢复](docs/ops/restore.md)、[保留与清理](docs/ops/retention.md)。

## 开发与验证

```sh
docker compose -p paper-checks -f compose.example.yaml run --build --rm checks
docker compose -p paper-tests -f compose.example.yaml run --build --rm tests
docker compose -p paper-tests -f compose.example.yaml --profile tests down --volumes
```

以上命令使用模板中的检查/测试服务和独立项目；测试只启动专用 `test-db` 依赖。不要改用 profile 整体 `up`，它也会启动默认产品服务；清理命令仅用于该独立测试项目。实际解析模型、硬件推理、真实翻译服务和生产恢复需要各自的运行证据；普通测试通过不代表它们已经验证。宿主开发和浏览器测试见[测试说明](tests/README.md)。

| 目录 | 内容 |
| --- | --- |
| `src/apps/` | FastAPI 与 React 前端 |
| `src/packages/` | 领域逻辑、数据库迁移、阅读模板 |
| `src/workers/` | 任务 worker 与隔离 PDF parser |
| `src/tools/` | 仓库检查、模型打包与部署工具 |
| [res/](res/README.md) | 运行时 Schema、冻结阅读样式和受控种子资料 |
| [tests/](tests/README.md) | 自动化测试、合成测试资料、测试镜像构建输入 |
| [deployment/](docs/deployment/README.md) | 产品镜像、硬件运行环境和模型构建输入 |
| [docs/](docs/README.md) | 当前产品、架构、API 与操作说明 |

Python 模块入口仍为 `apps`、`packages`、`workers`、`tools`。宿主直接调用时设置 `PYTHONPATH=src`；pytest 和容器已配置搜索路径。前端命令使用 `npm --prefix src/apps/web ...`。

[AGENTS.md](AGENTS.md)说明编码约束；[`.agent/`](.agent/README.md)存放开发工具和运行证据。历史计划与报告保留在 Git 历史或明确标注的 agent 记录中，不作为当前实施指令。

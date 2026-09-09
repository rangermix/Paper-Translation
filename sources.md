# 设计依据与版本差异

## 1. 主要材料

本包从用户提供的 `bilingual-library-prototype.zip` 和 `bilingual-library-m0-m2-spec-plan-v2.zip` 重建。旧包中的reader-v1、原论文页面和原PDF是阅读回归参考；旧版用户/工作区/鉴权/多格式内容不再作为当前要求。

本轮用户的五条范围要求是最终约束。新增的PDF-only M0原件库、无身份实体、Compose依赖打包及parser spool部署细节属于对这些约束的设计落实，而不是旧文档已实现的能力。旧版全部42个工作包重新审查，状态仍为未开始；不沿用旧包“静态检查通过”充当新应用验收。

## 2. 运行机制核对资料（2026-09-06）

以下仅用于核对实现机制；不证明本产品部署或语义准确率。

- **S1** Docker Compose startup order：service_healthy与service_completed_successfully，短depends_on不是就绪保证。https://docs.docker.com/compose/how-tos/startup-order/
- **S2** Docling advanced options：模型预取与离线artifacts_path。https://docling-project.github.io/docling/usage/advanced_options/
- **S3** Docker Compose secrets与service定义：secret按服务挂载，文件来源的权限重映射限制。https://docs.docker.com/compose/how-tos/use-secrets/ ; https://docs.docker.com/reference/compose-file/services/
- **S4** Docker none network：network_mode:none隔离外部网络。https://docs.docker.com/engine/network/drivers/none/
- **S5** FastAPI FileResponse：应用可直接提供文件响应，无需本产品内置反代。https://fastapi.tiangolo.com/advanced/custom-response/
- **S6** PostgreSQL SELECT锁定与SKIP LOCKED：沿用旧版队列设计依据。https://www.postgresql.org/docs/current/sql-select.html
- **S7** OpenAI Structured Outputs：结构化响应与拒绝/不完整结果仍需区分。https://developers.openai.com/api/docs/guides/structured-outputs

API型号、价格、模型许可证及平台架构以实施时实际锁定和验收为准；本包不编造最新型号或可拉取的产品镜像地址。

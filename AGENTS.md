# 项目维护约定

- 主项目为 `backend/`（Java 17 + Spring Boot）、`frontend/`（Vue 3）、`ai-service/`（Python）。`trash/` 为用户归档的旧项目，不应作为运行目录，也不要修改其中内容。
- 当前前端来源为 `IP_Copyright_Prototype-2.html`，原件存档在 `docs/reference/frontend-original.html`。保持现有布局与中文界面。
- 操作手册的章节保存、提交和审核已接入服务端，源码自动分析生成及官网自动申报仍保留原型。不生成虚构官网结果。
- 任何数据库结构修改，必须同时更新 `database/production.sql`；对已有数据库的变更加上 `database/migrations/` 中按版本排列的增量SQL。生产完整建表SQL始终以 `production.sql` 为唯一来源。
- 数据库凭据只放 `.env.local`，模型地址、Key、模型名、思考深度放 `config/assistant.json`。两者均不提交Git，不在日志、API响应或前端持久存储中暴露Key。
- 权限、填报校验和审核状态转换必须在Java服务端执行，不能依赖前端角色、按钮状态或请求中自报的角色。按用户2026-11-19要求，软著助手可跨项目读取所有附件，但写入仍按当前账号字段权限校验。
- 修改业务流程后执行真实MySQL集成验证 `ai-service/.venv/bin/python scripts/verify_integration.py`；助手改动运行 `ai-service/.venv/bin/python -m pytest ai-service/tests -q`。前端或Java改动后运行 `python3 scripts/build.py`。

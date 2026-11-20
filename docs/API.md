# 接口与状态

业务接口前缀 `/api`。除健康检查、登录外均需有效HttpOnly会话Cookie。以数据库中的用户角色和项目授权为准，请求体或请求头中的自报角色无效。涉及写操作的浏览器请求校验Origin。

| 接口 | 用途 |
| --- | --- |
| POST `/auth/login`、POST `/auth/logout`、GET `/auth/me` | 登录、退出、当前用户 |
| GET `/metadata` | 服务器字段目录 |
| GET/POST `/projects` | 已授权项目查询、创建 |
| GET/PUT/DELETE `/projects/{id}` | 详情、编辑、归档 |
| PUT `/projects/{id}/form` | 保存分部门字段，携带revision |
| POST `/projects/{id}/form/validate` | 检查已保存表单 |
| POST `/projects/{id}/form/submit` | 校验并提交审核，可携带已保存草稿的 revision |
| POST `/projects/{id}/form/review` | 管理员审核，field可为字段名或all |
| POST `/projects/{id}/files` | multipart附件上传，file及category |
| GET `/projects/{id}/files/{fileId}/download` | 原件下载，安全类型支持inline=true预览 |
| GET `/projects/{id}/files/{fileId}/text` | 已提取文本 |
| PUT/DELETE `/projects/{id}/files/{fileId}` | 分类、软移除 |
| POST `/projects/{id}/files/{fileId}/extract` | 重新提取文本 |
| POST `/projects/{id}/records` | 人工登记真实办理记录及凭证 |
| GET `/projects/{id}/reuse/{sourceId}` | 读取已授权历史填报字段 |
| GET `/notifications` | 管理员查看待核实项，其他用户查看可访问项目的待修改项 |
| GET/POST `/projects/{id}/manual-jobs` | 获取本账号在本项目的最近一次任务；以 `fileId`、`url`、`browserReady` 创建任务 |
| GET/DELETE `/projects/{id}/manual-jobs/{job}` | 查询进度、结果和状态；停止活跃任务 |
| POST `/projects/{id}/manual-jobs/{job}/capture` | 确认计划，开始真实浏览器截图 |
| GET `/projects/{id}/manual-jobs/{job}/plan`、GET `/projects/{id}/manual-jobs/{job}/word` | 下载截图计划 JSON 或生成完成的 Word |
| GET/DELETE `/assistant/messages` | 按projectId、scope查询或清空自己的会话 |
| POST `/assistant/chat` | question、projectId、scope；scope为knowledge/project/history |
| GET/PUT `/assistant/config` | 管理员读取或更新模型配置，Key只写 |
| POST `/assistant/config/test` | 管理员测试模型连接 |
| GET/POST `/assistant/knowledge` | 知识资料查询、管理员新增 |
| PUT/DELETE `/assistant/knowledge/{id}` | 管理员编辑或停用资料 |

表单状态：draft → submitted → approved；审核退回为returned，可修改后重新提交。审核中禁止编辑。已审核字段值改变后不再显示其原通过状态，表单回到draft。项目修改通过revision避免多人覆盖，冲突返回409。

Python服务仅由Java通过 `X-Service-Token` 调用：`/agent/step`、`/chat`、`/extract`、`/config`、`/config/test` 和 `/manual/jobs`。模型请求采用 `messages`、`model`、`stream:false`，可选 `reasoning_effort`。接口地址包含或不包含 `/chat/completions` 均可。模型错误不将提供方原始响应或Key透传给浏览器。

管理接口 GET/POST `/api/admin/users`、PUT `/api/admin/users/{id}` 均要求管理员。GET `/api/admin/reviews` 返回项目基础填报、手册和审核记录。GET `/api/admin/reviews/{id}/manual/{reviewId}` 返回该次审核的手册章节快照。
手册接口为GET/PUT /api/projects/{id}/manual、POST /manual/submit、POST /manual/review。写操作需携带手册revision，提交检查章节确认状态。
申报记录新增PUT/DELETE /api/projects/{id}/records/{recordId}，管理员和行政业务办可操作。
助手先调用 Python `/agent/step` 分析意图，Java 逐次执行附件搜索、读取、状态查询或草稿填写。仅当模型给出 `knowledge(query)` 时，才按重写后的查询词检索并调用模型作答。跨项目附件读取按本次业务授权开放，代填仍经过 `ProjectService.saveForm`。

手册生成任务状态为 `running → review → running → complete`，也可进入 `failed` 或 `cancelled`。`events` 提供模型改写的事实进度，`result` 提供结构化目录、路径、操作和截图数。创建、确认和下载均校验当前账号及项目权限；任务文件不写入审核数据。服务重启会清空任务状态。

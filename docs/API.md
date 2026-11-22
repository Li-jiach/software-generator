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
| POST `/projects/{id}/form/review` | 管理员整表审核，提交 revision 与 status（approved 或 returned），returned 必须填写 comment |
| POST `/projects/{id}/official-application/start` | 管理员或行政业务办经四项预检取得一次性启动凭证 |
| POST `/projects/{id}/official-application/consume` | 同一工作台会话以 ticket 领取当前审核表单和已通过审核的附件标识及 SHA-256。服务端再次校验审核状态，系统管理员可领取机构登录配置 |
| GET `/projects/{id}/official-application/materials/{kind}/{fileId}/pdf?sha256=…` | 对照当前审核附件和原件哈希生成申报 PDF，仅管理员或行政业务办可用 |
| GET / PUT `/admin/official-credentials` | 系统管理员读取已配置账号，或提交 username 和 password 更新加密配置 |
| POST `/projects/{id}/files` | multipart附件上传，file及category |
| GET `/projects/{id}/files/{fileId}/download` | 原件下载，安全类型支持inline=true预览 |
| GET `/projects/{id}/files/{fileId}/text` | 已提取文本 |
| PUT/DELETE `/projects/{id}/files/{fileId}` | 分类、软移除 |
| POST `/projects/{id}/files/{fileId}/extract` | 重新提取文本 |
| POST `/projects/{id}/records` | 人工登记真实办理记录及凭证 |
| GET `/projects/{id}/reuse/{sourceId}` | 读取已授权历史填报字段 |
| GET `/notifications` | 管理员查看待核实项，其他用户查看可访问项目的待修改项 |
| GET/POST `/projects/{id}/manual-jobs` | 获取本账号在本项目的最近一次任务；以 `fileId`、`url`、`browserReady` 创建任务 |
| POST `/projects/{id}/manual-jobs/source` | 以 `fileId` 启动目录分类和前后端源码分析，完成后状态为 `source_ready` |
| POST `/projects/{id}/manual-jobs/reset` | 停止当前账号在本项目的生成任务，并清空页面显示的任务状态 |
| POST `/projects/{id}/manual-jobs/{job}/generate` | 以 `url`、`browserReady` 继续已完成的源码分析任务，自动生成截图计划并截图 |
| GET/DELETE `/projects/{id}/manual-jobs/{job}` | 查询进度、分析结果和最近的模型回复 `modelLogs`；停止活跃任务 |
| POST `/projects/{id}/manual-jobs/{job}/capture` | 重试当前截图步骤，停止仍在运行的截图并保留已通过核验的图片。不可达目标记入 `unreachableShots`，截图或核验失败记入 `failedShots` |
| GET `/projects/{id}/manual-jobs/{job}/plan`、POST `/projects/{id}/manual-jobs/{job}/word` | 下载内部截图计划 JSON，或通过 `acknowledged:true` 确认用途后下载参考 Word。截图失败时，Word 在对应位置留白并标注待补截图 |
| GET/DELETE `/assistant/messages` | 按 projectId、scope 查询或清空自己的会话。助手消息的 operations 含实际操作、目标项目和已保存的字段变更 |
| POST `/assistant/chat`、POST `/assistant/chat/stream` | question、projectId、scope、page、hasUnsaved。scope 可为 knowledge、project 或 history。完成响应包含 operations |
| GET/PUT `/assistant/config` | 管理员读取或更新模型配置，Key只写 |
| POST `/assistant/config/test` | 管理员测试模型连接 |
| GET/POST `/assistant/knowledge` | 知识资料查询、管理员新增 |
| PUT/DELETE `/assistant/knowledge/{id}` | 管理员编辑或停用资料 |

表单状态：draft → submitted → approved；审核退回为returned，可修改后重新提交。审核中禁止编辑。已审核字段值改变后不再显示其原通过状态，表单回到draft。项目修改通过revision避免多人覆盖，冲突返回409。

Python服务仅由Java通过 `X-Service-Token` 调用：`/agent/step`、`/chat`、`/extract`、`/config`、`/config/test` 和 `/manual/jobs`。模型请求采用 `messages`、`model`、`stream:false`，可选 `reasoning_effort`。接口地址包含或不包含 `/chat/completions` 均可。模型错误不将提供方原始响应或Key透传给浏览器。

管理接口 GET/POST `/api/admin/users`、PUT `/api/admin/users/{id}` 均要求管理员。GET `/api/admin/reviews` 返回项目基础填报、手册和审核记录。GET `/api/admin/reviews/{id}/manual/{reviewId}` 返回该次审核的手册章节快照。
手册接口为GET/PUT /api/projects/{id}/manual、POST /manual/submit、POST /manual/review。写操作需携带手册revision，上传到项目的最终操作手册通过 `attachmentId` 送审。历史章节提交仍会校验章节确认状态。
申报记录新增PUT/DELETE /api/projects/{id}/records/{recordId}，管理员和行政业务办可操作。
助手先调用 Python `/agent/step` 分析意图，Java 逐次执行附件搜索、读取、状态查询或草稿填写。仅当模型给出 `knowledge(query)` 时，才按重写后的查询词检索并调用模型作答。跨项目附件读取按本次业务授权开放，代填仍经过 `ProjectService.saveForm`。

手册生成任务状态为 `running → complete`，也可进入 `failed` 或 `cancelled`。`events` 提供模型改写的事实进度，`result` 提供结构化目录、路径、操作和截图数。创建、确认和下载均校验当前账号及项目权限；任务文件不写入审核数据。服务重启会清空任务状态。

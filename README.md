# 知产协同 · 软件著作权工作空间

从新克隆的仓库启动项目时，先读 [AGENTS.md](AGENTS.md)，然后在仓库根目录执行下面的步骤。项目由 Vue 3 前端、Java 17 / Spring Boot 后端、Python 3.12 / FastAPI 服务和 MySQL 8 组成。

## 从空环境启动

如果收到的是 Git Bundle，先执行 `git clone software-generator.bundle software-generator`，再进入 `software-generator/`。

以下命令适用于 macOS 和 Linux。先安装 **JDK 17、Maven 3.6+、Node.js 20.19+ 或 22.12+、Python 3.12、MySQL 8.0+ 和 `mysql` 命令行客户端**。启动 MySQL，并确保初始化所用账号能创建库和表。

1. 复制配置模板并限制本地配置的读取权限。

   ```sh
   cp .env.example .env.local
   chmod 600 .env.local
   ```

   编辑 `.env.local`，填写本机的 `DB_HOST`、`DB_PORT`、`DB_USERNAME` 和 `DB_PASSWORD`，将 `DB_NAME` 设为 `copyright_workspace`。如果系统默认的 Java 不是 JDK 17，把 `JAVA_HOME` 设为本机 JDK 17 的安装目录。设置随机 `SERVICE_TOKEN` 和至少 12 位的 `BOOTSTRAP_PASSWORD`，可用 `openssl rand -hex 32` 分别生成。Java 与 Python 必须读取同一个 `SERVICE_TOKEN`。

2. 初始化空数据库，安装依赖并构建。已有业务库请走下方的升级步骤。

   ```sh
   python3 scripts/init_db.py
   python3.12 -m venv ai-service/.venv
   ai-service/.venv/bin/python -m pip install -r ai-service/requirements.lock.txt
   npm ci --prefix frontend
   python3 scripts/build.py
   ```

3. 任选一种方式启动。

   | 运行方式 | 命令 | 浏览器入口 |
   | --- | --- | --- |
   | 开发，修改 Vue 后自动刷新 | `python3 scripts/dev.py` | [127.0.0.1:5173](http://127.0.0.1:5173/) |
   | 运行已打包的应用 | `python3 scripts/serve.py` | [127.0.0.1:8080](http://127.0.0.1:8080/) |

   开发模式同时启动 Vue（5173）、Java（8080）和 Python（8090），日志在 `.run/`。打包模式启动 Java 和 Python，Vue 已内置在 `backend/target/copyright-workspace-1.0.0.jar`。两种方式使用相同的后端端口，请择一运行。按 Ctrl+C 停止本次启动的服务。

4. 用 `admin` 和 `.env.local` 中的 `BOOTSTRAP_PASSWORD` 首次登录，创建一个测试项目。空库首次启动还会创建 `adminDept`（行政业务办）和 `research`（研发人员），初始密码相同。已有账号使用其原有密码。

## 配置模型和截图

基础业务在无模型配置时也能启动。使用软著助手或智能生成操作手册时，管理员在右下角「软著助手 → 设置」填写兼容 Chat Completions 的模型地址、Key、模型名和思考深度，然后保存并测试。管理员也可以按 [config/assistant.example.json](config/assistant.example.json) 在本机创建 `config/assistant.json`。模型地址接受 `/v1` 基址或完整的 `/v1/chat/completions` 地址。手册生成和助手共用该配置，相关源码和项目资料会按需发送给所选模型。

需要截图时安装 Chromium。

```sh
ai-service/.venv/bin/python -m playwright install chromium
```

也可在 `.env.local` 中设置 `MANUAL_CHROMIUM_PATH`，指向已安装的 Chromium / Chrome 可执行文件。管理员先在「操作手册生成 → 智能生成」保存项目的本机测试站点入口，例如 `http://127.0.0.1:3000/`。使用可直接访问的测试页面，保持站点运行。在页面选择本地项目目录、ZIP 或已上传的源码附件，执行分析，确认截图计划后下载 Word。截图使用独立浏览器，Word 下载与章节送审各有入口。

## 业务流程和代码入口

- `frontend/` 提供项目查阅、填报、附件、手册、申报记录、人员及审核界面。界面参考在 `docs/reference/frontend-original.html`。
- `backend/` 管理登录、项目访问、字段权限、材料审核、版本和申报启动校验。接口见 [docs/API.md](docs/API.md)。
- `ai-service/` 提供附件文本提取、知识库与助手服务、手册分析和截图。内置知识在 `knowledge-base/`，Word 导出模板在 `template/`。
- 基础信息和操作手册从各自页面送审。源程序鉴别材料与权属证明在「附件资料」选择项目附件后送审。管理员在「管理页面 → 审核管理」处理四项待办。四项均通过后才能启动官网申报流程预览。真实申报办理情况通过「申报记录」登记。
- `.env.local`、`config/assistant.json`、运行日志和运行数据由部署环境提供。移交业务数据时需另行备份 MySQL、`data/attachments/`、本机模型配置和自定义知识资料。凭据通过授权渠道交接。

## 升级已有数据库

当前结构版本为 **V004**。新库用 `database/production.sql`。已有库先查询 `copyright_workspace.schema_versions`，再按版本顺序应用尚未执行的增量脚本。V003 升级到当前版本只需执行以下命令，`<数据库维护账号>` 替换为实际账号。

```sh
mysql -h 127.0.0.1 -u '<数据库维护账号>' -p < database/migrations/V004.sql
```

连接远程数据库或非默认端口时相应调整 `-h` 和 `-P`。后端启动时不自动执行迁移。详见 [database/README.md](database/README.md)。

## 验证改动

```sh
python3 scripts/build.py
ai-service/.venv/bin/python -m pytest ai-service/tests -q
```

业务集成验证使用单独运行的 Java、Python、Chromium 和真实 MySQL。测试脚本会临时更新所指向的模型配置，因此下例使用独立 Python 配置文件、附件目录和端口。建议用临时 MySQL 库运行，确保该库已按 `production.sql` 初始化，并向 Java 与测试脚本提供相同的数据库连接参数。测试所用 `BOOTSTRAP_PASSWORD` 应与该库初始化时一致。

先在终端 A 和 B 的环境中设置与本机配置一致的 `SERVICE_TOKEN`。在终端 B 同时设置 MySQL 连接变量、`BOOTSTRAP_PASSWORD` 和适用的 `JAVA_HOME`。统一使用 `.env.local` 中的本机配置，凭据含特殊字符时注意按终端语法引用。安装 Chromium 后，从仓库根目录在终端 A 启动测试 Python。

```sh
test_config=$(mktemp)
printf '%s\n' '{"base_url":"http://127.0.0.1:1/v1","model":"integration-test-isolated"}' > "$test_config"
(
  cd ai-service
  ASSISTANT_CONFIG="$test_config" .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 18090
)
rm -f "$test_config"
```

在终端 B 启动测试 Java。若使用单独的库，设置对应的 `DB_NAME` 等连接参数。保持测试附件目录与终端 C 一致。

```sh
SERVER_PORT=18080 AI_SERVICE_URL=http://127.0.0.1:18090 \
  ATTACHMENT_DIR="$PWD/data/integration-attachments" \
  "${JAVA_HOME:+$JAVA_HOME/bin/}java" -jar backend/target/copyright-workspace-1.0.0.jar
```

在终端 C 运行测试。临时库或自定义 Chromium 的环境变量需与前两步保持一致。

```sh
TEST_BASE_URL=http://127.0.0.1:18080/api ATTACHMENT_DIR="$PWD/data/integration-attachments" \
  ai-service/.venv/bin/python scripts/verify_integration.py
```

启动排查可先核对端口、MySQL 连接与 `schema_versions`，再检查 `.run/backend.log` 和 `.run/assistant.log`。如果截图失败，核对 Chromium 路径、测试入口和模型配置。

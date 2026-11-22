# 知产协同 · 软件著作权工作空间

从新克隆的仓库启动项目时，先读 [AGENTS.md](AGENTS.md)，然后在仓库根目录执行下面的步骤。项目由 Vue 3 前端、Java 17 / Spring Boot 后端、Python 3.12 / FastAPI 服务和 MySQL 8 组成。

## 从空环境启动

```sh
git clone https://github.com/Li-jiach/software-generator.git
cd software-generator
```

通过 Git Bundle 交接时，使用 `git clone software-generator.bundle software-generator`。

以下命令适用于 macOS 和 Linux。先安装 **JDK 17、Maven 3.6+、Node.js 20.19+ 或 22.12+、Python 3.12、MySQL 8.0+ 和 `mysql` 命令行客户端**。启动 MySQL，并确保初始化所用账号能创建库和表。

1. 复制配置模板并限制本地配置的读取权限。

   ```sh
   cp .env.example .env.local
   chmod 600 .env.local
   ```

   按实际环境填写 `.env.local`。可用 `openssl rand -hex 32` 分别生成独立的服务令牌和初始密码。

   | 变量 | 配置方式 |
   | --- | --- |
   | `DB_HOST`、`DB_PORT`、`DB_USERNAME`、`DB_PASSWORD` | 实际 MySQL 连接参数。初始化账号需要建库建表权限。 |
   | `DB_NAME` | 标准安装填写 `copyright_workspace`。 |
   | `SERVICE_TOKEN` | Java 与 Python 之间共用的随机令牌。 |
   | `BOOTSTRAP_PASSWORD` | 空库首次创建内置账号时使用，至少 12 位。 |
   | `JAVA_HOME` | 系统默认版本不是 JDK 17 时指定 JDK 17 安装目录，同时确保 Maven 使用该版本。 |
   | `SECURE_COOKIE` | 本机 HTTP 使用 `false`，通过 HTTPS 部署时使用 `true`。 |
   | `ATTACHMENT_DIR` | 可选。自定义附件存储时填写 Java 可读写的绝对路径，默认 `data/attachments/`。 |
   | `MANUAL_CHROMIUM_PATH` | 可选。Chrome 安装在自定义路径时指定 Google Chrome 可执行文件。 |
   | `OFFICIAL_CREDENTIAL_KEY` | 使用工作台保存官网账号时填写，运行 `openssl rand -base64 32` 生成。 |
   | `SOFFICE_PATH` | 可选。需要转换非 PDF 材料且 `PATH` 中找不到 LibreOffice 时，指定 `soffice` 可执行文件。 |

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

截图与浏览器预检使用 Google Chrome。请先安装 Chrome。若装在自定义位置，可在 `.env.local` 中设置 `MANUAL_CHROMIUM_PATH` 指向 Chrome 可执行文件。管理员先在「操作手册生成」保存项目的本机测试站点入口，例如 `http://127.0.0.1:3000/`。使用可直接访问的测试页面，保持站点运行。通过「选择路径」选中本地项目目录，或点击「使用源码 ZIP」选择本地 ZIP 并立即上传。保存测试站点入口后，勾选 Chrome 确认并点击「测试站点」。检测通过后才可点击「开始分析」。系统随后扫描目录，由配置的模型分类并分别分析前端和后端源码。源码分析完成后，系统会自动生成截图计划。勾选项旁的「查看开发者模式打开方式」提供操作教程。计划生成后，独立 Chrome 会话自动按计划截图，并把每张图片发送给支持图片输入的已配置模型核验。未通过时，系统最多调整取景并重拍两次。生成参考 Word 时会插入通过核验的截图，无法取得的截图留白并标明待补内容。确认参考用途后下载，编辑完成后可上传最终 Word 或 PDF 并送审。

## 业务流程和代码入口

- `frontend/` 提供项目查阅、填报、附件、手册、申报记录、人员及审核界面。界面参考在 `docs/reference/frontend-original.html`。
- `backend/` 管理登录、项目访问、字段权限、材料审核、版本和申报启动校验。接口见 [docs/API.md](docs/API.md)。
- `ai-service/` 提供附件文本提取、知识库与助手服务、手册分析和截图。内置知识在 `knowledge-base/`，Word 导出模板在 `template/`。
- 软著助手按账号和项目会话保留对话、查阅项目及草稿字段前后值。可追问「刚才查的是哪个项目」「具体改了什么」，也可展开消息下的「本轮操作」。清空会话后，助手不再使用该会话的旧操作。
- 基础信息和操作手册从各自页面送审。源程序鉴别材料与权属证明在「附件资料」选择项目附件后送审。管理员在「管理页面 → 审核管理」处理四项待办。四项均通过后才能启动官网自动填报。真实申报办理情况通过「申报记录」登记。
- `.env.local`、`config/assistant.json`、运行日志和运行数据由部署环境提供。移交业务数据时需另行备份 MySQL、`data/attachments/`、本机模型配置和自定义知识资料。凭据通过授权渠道交接。

## 官网自动填报

### RPA 脚本

仓库包含 R11 RPA 源码，随 Vue 一起构建部署。

| 文件 | 用途 |
| --- | --- |
| [official-macro.js](frontend/src/official-macro.js) | 生成 `Copyright_R11_Fill` 的 Ui.Vision JSON 宏，包含官网控件定位、填写和上传逻辑。 |
| [official-launch.js](frontend/src/official-launch.js) | 调度本次申报，交接申报窗口，显示进度并处理重试。 |
| [official-session.html](frontend/public/official-session.html) | Ui.Vision 接管官网窗口前的本地启动页。 |
| [official_pdf.py](ai-service/official_pdf.py) | 将已审核的附件整理为申报所需 PDF。 |

每次点击「启动申报」，工作台会生成并向 Ui.Vision 发送当次运行的宏。初始化无需手动导入。运行宏含短时有效的一次性启动凭证，请从工作台启动每次申报。

### 首次配置与操作

1. 在办理申报的电脑上安装 Google Chrome 和 Ui.Vision 10。打开扩展设置的 API，启用网页嵌入宏，然后在同一 Chrome 配置文件中打开工作台并登录。允许工作台站点打开申报弹窗。[Ui.Vision 嵌入宏说明](https://ui.vision/rpa/docs/)
2. 如需由工作台协助登录官网，在 `.env.local` 配置 `OFFICIAL_CREDENTIAL_KEY` 后启动服务。由管理员打开「管理页面 → 官网账号」，保存中国版权保护中心机构管理员的账号和密码。MySQL 保存 AES-256-GCM 密文，配置密钥随部署凭据备份。行政业务办可在申报窗口使用自己的官网会话。
3. 补齐预检列出的字段，送审基础信息、源程序鉴别材料、操作手册及权属证明。四项均经管理员审核通过后，由管理员或行政业务办在「官网自动申报」点击「启动申报」。
4. 在工作台标签页确认 Ui.Vision 的运行提示。待「打开申报窗口」出现后点击它。保持工作台和申报窗口打开，在「实时申报状态」查看进度。遇到登录、安全验证或需补充的字段，按提示在官网窗口操作。
5. 宏填写当前 R11 页面并上传对应的已审核材料。经办人核对每页后手动点击「下一步」，在最终确认页复核并点击「确认填报」。签章页由官网生成，真实办理结果在工作台「申报记录」登记。

### PDF 转换与排查

已审核的 PDF 可直接进入整理流程。使用 Word、ODT、RTF 或 UTF-8 文本材料时，在 Python 服务所在机器安装 LibreOffice 和常用中文字体。可运行 `soffice --version` 确认安装，或在 `.env.local` 指定 `SOFFICE_PATH`。历史审核通过的系统手册章节可以转换成 PDF。一般交存的源程序或手册超过 60 页时，生成的 PDF 保留前后各连续 30 页。单份 PDF 上限为 20 MB。工作台保留原始附件。

- 「启动申报」不可用时，先查看预检列出的待补字段和待审核项目。
- 扩展未启动时，检查是否使用同一 Chrome 配置文件、嵌入宏是否已启用，以及 Ui.Vision 是否在等待确认。
- 官网窗口停在登录或验证页时，在该窗口完成操作，回到工作台查看下一步提示。
- PDF 转换失败时，检查文件格式、大小、加密状态和服务端的 LibreOffice 配置。

## 升级已有数据库

当前结构版本为 **V007**。新库用 `database/production.sql`。已有库先查询 `copyright_workspace.schema_versions`，再按版本顺序应用尚未执行的增量脚本。V006 升级到当前版本执行以下命令，`<数据库维护账号>` 替换为实际账号。

```sh
mysql -h 127.0.0.1 -u '<数据库维护账号>' -p < database/migrations/V007.sql
```

连接远程数据库或非默认端口时相应调整 `-h` 和 `-P`。后端启动时不自动执行迁移。详见 [database/README.md](database/README.md)。

## 验证改动

```sh
python3 scripts/build.py
ai-service/.venv/bin/python -m pytest ai-service/tests -q
```

业务集成验证使用单独运行的 Java、Python、Google Chrome 和真实 MySQL。测试脚本会临时更新所指向的模型配置，因此下例使用独立 Python 配置文件、附件目录和端口。建议用临时 MySQL 库运行，确保该库已按 `production.sql` 初始化，并向 Java 与测试脚本提供相同的数据库连接参数。测试所用 `BOOTSTRAP_PASSWORD` 应与该库初始化时一致。

先在终端 A 和 B 的环境中设置与本机配置一致的 `SERVICE_TOKEN`。在终端 B 同时设置 MySQL 连接变量、`BOOTSTRAP_PASSWORD` 和适用的 `JAVA_HOME`。统一使用 `.env.local` 中的本机配置，凭据含特殊字符时注意按终端语法引用。安装 Google Chrome 后，从仓库根目录在终端 A 启动测试 Python。

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

在终端 C 运行测试。临时库或自定义 Chrome 的环境变量需与前两步保持一致。

```sh
TEST_BASE_URL=http://127.0.0.1:18080/api ATTACHMENT_DIR="$PWD/data/integration-attachments" \
  ai-service/.venv/bin/python scripts/verify_integration.py
```

启动排查可先核对端口、MySQL 连接与 `schema_versions`，再检查 `.run/backend.log` 和 `.run/assistant.log`。如果截图失败，核对 Chrome 路径、测试入口和模型配置。

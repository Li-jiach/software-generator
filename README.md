# 软著材料工作台（Software Generator）

用于软件著作权材料整理与操作手册生成的 Web 应用，由原生 HTML/CSS/JavaScript 前端、Spring Boot 后端和 Python AI 服务组成。

## 主要功能

- 管理软著项目、基础信息、模型设置和上传材料。
- 在画布中组织系统、模块、页面、截图及父子连线。
- 调用模型优化文本、识别截图，按组件或整棵组件树生成操作手册。
- 保存项目工作区，下载材料 ZIP，使用 Word 模板导出包含标题层级与截图的操作手册。
- 导入医疗影像运维管理系统示例，验证组件结构、截图和导出流程。

## 目录

```text
frontend/        前端页面、画布逻辑和示例测试资源
backend/         Java REST API、MySQL 建表脚本、Word 导出和测试
ai-service/      FastAPI 模型代理与生成逻辑
scripts/         模板制作、手册导出、PDF 提取与回归测试
templates/       Word 操作手册模板
Samples/操作手册/  测试使用的源 PDF
```

Git 仅收录代码、必要模板与测试资源。运行时上传材料、数据库数据、构建产物、缓存、临时结果和其他参考文档不纳入版本控制。

## 环境要求

- JDK 17、Maven、MySQL 8。
- Python 3.10 或以上版本。
- Node.js 18 或以上版本（运行 JavaScript 回归测试时使用）。
- 可调用的模型接口和 API Key（执行 AI 功能时配置）。

## 本地启动

在项目根目录初始化数据库：

```bash
mysql -u root -p < backend/src/main/resources/schema.sql
```

在一个终端启动 AI 服务：

```bash
cd ai-service
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8090 --reload
```

在另一个终端配置数据库密码并启动后端：

```bash
export DB_USERNAME=root
export DB_PASSWORD='替换为本机数据库密码'
cd backend
mvn spring-boot:run
```

浏览器访问 http://localhost:8080/ 。后端从相邻的 `frontend/` 目录提供页面，因此请在 `backend/` 中运行 Maven。也可直接打开 `frontend/index.html` 体验前端，本地演示数据保存在浏览器 localStorage 中。

## 配置

| 环境变量 | 默认值或用途 |
| --- | --- |
| `DB_URL` | 本机 MySQL 的 `copyright_studio` 数据库，完整默认连接串见 `backend/src/main/resources/application.yml` |
| `DB_USERNAME` | `root` |
| `DB_PASSWORD` | 空；启动前设置实际密码 |
| `AI_SERVICE_URL` | `http://127.0.0.1:8090` |
| `ASSET_ROOT` | `./data/assets`，相对于后端工作目录 |
| `MODEL_ENDPOINT` | AI 服务的模型接口地址回退值 |

在页面设置中填写模型地址、模型名和 API Key。支持 Chat Completions 及 Responses 兼容接口；可直接填写完整 `/chat/completions` 或 `/responses` 路径。基础地址在 Responses 模式下会尝试 `/response` 和 `/responses`。模型未配置或请求失败时返回错误，不生成本地替代文本。请勿提交真实密钥或带凭据的项目数据。

## 测试

在项目根目录运行：

```bash
node --test scripts/test-medical-manual.cjs scripts/test-incremental-generation.cjs
python3 -m unittest discover -s ai-service -p 'test_*.py'
python3 -m pip install python-docx Pillow
python3 -m unittest discover -s scripts -p 'test_*.py'
cd backend
mvn test
```

当前打包检查中，示例资源测试 6 项通过；增量生成测试 5 项因测试 DOM 替身缺少 `classList.toggle` 失败，尚未修复。未执行完整后端、Python 与浏览器集成测试。

AI 服务测试需要先安装 `ai-service/requirements.txt`。浏览器集成检查可在服务启动并安装 Playwright 后执行 `node scripts/check-medical-manual-browser.cjs`；该检查会创建测试项目并验证保存、材料下载和刷新恢复。

## 示例资源与 Word 工具

一键导入案例来自 `Samples/操作手册/医疗影像运维管理系统V1.0 操作手册.pdf`。测试资源包含源 PDF、37 张截图、清单与章节大纲；导入后形成 51 个组件和 50 条连线，生成文本等待真实模型调用。

重新提取示例需要 `pdfplumber`、Pillow 和 Poppler 的 `pdfimages`：

```bash
python3 scripts/extract_medical_manual.py
```

可用 `--poppler-bin` 指定 Poppler 工具目录。独立 Word 导出使用包含 `profile`、`nodes`、`connections`、`generated` 的工作区 JSON：

```bash
python3 scripts/export_manual.py workspace.json output.docx
```

导出按父子结构与画布坐标组织章节；模板位于 `templates/操作手册模板.docx`，Java 后端使用 `backend/src/main/resources/templates/` 中的副本。

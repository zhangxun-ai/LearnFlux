# 配置与 API Key 指南

先完成一次文字学习，再配置需要的音视频或集成服务。首次使用步骤见[本地快速开始](quickstart.md)。真实密钥保存在被 Git 忽略的本地配置或受保护的环境变量中。

## 1. 创建本地配置

在项目根目录运行：

```bash
bash scripts/bootstrap.sh
```

脚本用 Python 3.11 安装锁定的应用依赖；没有 uv 时会安装 uv。首次创建 `config/config.jsonc` 时自动生成独立随机管理口令，默认只监听 `127.0.0.1`，文件权限为 `0600`。已有配置不会被改写；初始化过程不显示口令。仅有旧 `config/config.json` 时，脚本会保留它并提示迁移，运行时读取的是 `config/config.jsonc`。

已经安装依赖、只需初始化配置时，也可运行不依赖第三方 Python 包的工具：

```bash
python3 scripts/init_config.py
```

不要直接复制带空口令的模板启动。模板用于查阅配置项；初始化工具会保留模板注释并填好本机连接所需的值。开发测试依赖使用 `bash scripts/bootstrap.sh --dev` 安装。

只有启用云端 ASR、PostgreSQL 或 S3 等服务时，才需要额外准备环境变量文件：

```bash
cp .env.example .env
chmod 600 .env
```

不要把 `config/config.jsonc`、`.env` 或前端保存密钥的 `data/config.db` 提交到 Git。配置项以 `config/config.example.jsonc` 和 `.env.example` 为准。

## 2. 本机管理口令

`api.auth_token` 是本实例的管理口令和 API Bearer Token，不是模型服务商的 API Key。初始化时已自动生成，无需另运行生成命令。

默认单用户模式下，直接访问本机地址的浏览器可以自动连接。需要手动验证、使用手机或调用 API 时，在你自己的电脑上查看 `config/config.jsonc` 中的 `api.auth_token`；不要把它复制到聊天、日志、截图或 Issue。静态多用户模式另见[多用户配置指南](multi_user_setup.md)。

## 3. 大模型 API

LLM API 用于转录校对、总结、问答、图解和复盘等 AI 功能。没有可用 LLM Key 时，导入和基础转录仍可单独配置使用，但不会产生依赖模型的结果。

| 用户要准备的内容 | 配置位置 | 说明 |
| --- | --- | --- |
| 服务商 API Key | `llm.api_key` | 从你选择的模型服务商控制台创建。 |
| API Base URL | `llm.base_url` | 填服务商提供的 OpenAI 兼容接口地址；不要填到 `/chat/completions`。 |
| 模型 ID | `llm.calibrate_model`、`llm.summary_model` 等 `llm.*_model` 字段 | 必须是该 Key 和 Base URL 可调用的模型名称。不同任务可以使用不同模型。 |

在 Web 的 `/settings` 页面可以填写常用 LLM Key、Base URL 和模型；其他任务模型和高级选项可在 `config/config.jsonc` 中设置。配置模板中的模型名只是示例默认值；换服务商后，请按其官方文档改成实际可用的模型 ID，并确认账号已开通对应模型及额度。

主流程的校对和总结分别使用 `llm.calibrate_model`、`llm.summary_model`。使用对应功能时，还应检查系列解读的 `llm.collection_summary_model`、系列分段处理的 `llm.collection_summary_module_model`、图解提纲 / 渲染的 `llm.visual_learning_outline_model` 与 `llm.visual_learning_render_model`，以及边播边学问答的 `llm.study_chat_model`。所有模型 ID 都必须能通过所配置的服务商 Key 和 Base URL 调用。

设置页的服务商列表提供 OpenAI、DeepSeek、Google Gemini、Moonshot / Kimi、智谱 GLM、阿里云百炼、火山方舟和 SiliconFlow，并可跳转到对应的 Key 页面、预填 Base URL 和选择可用模型；也支持自行填写其他 OpenAI 兼容服务商。

| 服务商 | API Key 官方入口 |
| --- | --- |
| OpenAI | [API Keys](https://platform.openai.com/api-keys) |
| DeepSeek | [API Key 管理](https://platform.deepseek.com/api_keys)；[首次调用与接口文档](https://api-docs.deepseek.com/zh-cn/) |
| Google Gemini | [Google AI Studio API Key](https://aistudio.google.com/apikey)；兼容调用方式见[项目内说明](../development/llm/gemini_openai_compat.md) |
| Moonshot / Kimi | [API Key 管理](https://platform.kimi.com/console/api-keys) |
| 智谱 GLM | [API Key 管理](https://open.bigmodel.cn/usercenter/apikeys) |
| 阿里云百炼 | [API Key 指南](https://help.aliyun.com/zh/model-studio/get-api-key) |
| 火山方舟 | [API Key 管理](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey) |
| SiliconFlow | [API Key 管理](https://cloud.siliconflow.cn/account/ak) |

LearnFlux 按兼容接口发送模型请求。服务商控制台中给出的 Key、Base URL、模型名称和兼容能力应成套使用；模型名称或接口地址不匹配时，Key 正确也会调用失败。

## 本地功能按需安装

| 你要做什么 | 安装方式 | 说明 |
| --- | --- | --- |
| 粘贴文字、阅读可复制文字的文档 | 默认安装即可 | 不要求先配置 ASR、FFmpeg 或 OCR。AI 解读需要上一节的大模型配置。 |
| 处理音频 / 视频 | `bash scripts/bootstrap.sh --with-media` | 检查并安装 FFmpeg；还需选择实际可用的转录引擎。Linux 缺少 FFmpeg 时系统安装可能要求管理员权限。 |
| Apple Silicon Mac 本机转录 | `bash scripts/bootstrap.sh --with-local-whisper` | 安装 FFmpeg 与独立的 mlx-whisper 环境；按脚本提示启用 `local_whisper`。首次转录会下载模型。 |
| 识别扫描 PDF | `uv sync --extra ocr` | 安装 PaddleOCR / PaddlePaddle 后重启服务。未安装时文档保留为等待 OCR，可稍后重试，不阻塞普通文字文档。 |

`uv run` 默认保留已经安装的可选包。若以后重新运行精确同步 `uv sync`，请带上需要保留的 extra，例如 `uv sync --extra dev --extra ocr`。OCR 模型本身首次使用时也会下载；请预留网络和磁盘空间。

## 4. TikHub API

TikHub 主要用于抖音、小红书及部分社媒链接解析。只处理不依赖 TikHub 的来源时可以不配置。

| 参数 | 配置位置 | 获取方式 |
| --- | --- | --- |
| API Key | `tikhub.api_key` | 在 [TikHub 用户中心](https://user.tikhub.io/dashboard/api) 创建或复制 API Token。 |
| Base URL | `tikhub.base_url` | 模板默认使用 `https://api.tikhub.io`；仅在服务商文档明确要求时更改。 |

将 Key 填到 `/settings` 页面或 `config/config.jsonc`，不要写入 `.env.example` 或公开截图。

## 5. 阿里云百炼云端 ASR

云端 ASR 默认关闭，启用后会调用阿里云百炼并按实际用量收费。只在明确需要云端转录并接受费用时配置；任务提交前产品会显示预计费用并要求确认。

在 `.env` 中填写以下三个值：

| 环境变量 | 填写内容 | 获取位置 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 百炼 API Key | [官方 API Key 指南](https://help.aliyun.com/zh/model-studio/get-api-key)。 |
| `DASHSCOPE_WORKSPACE_ID` | 当前业务空间 ID | [官方 Workspace ID 指南](https://help.aliyun.com/zh/model-studio/obtain-the-app-id-and-workspace-id)。 |
| `DASHSCOPE_API_HOST` | `https://<Workspace ID>.cn-beijing.maas.aliyuncs.com` | 将尖括号部分替换为同一业务空间 ID；必须与该 ID 匹配。 |

然后在 `config/config.jsonc` 将 `cloud_asr.enabled` 改为 `true`。保存 `.env` 后重启服务，使新环境变量生效。`DASHSCOPE_API_KEY` 也可供模板内可选的百炼 LLM 次级端点使用；若不使用百炼模型，可保持该端点未配置。

## 6. 其他按需凭据

| 功能 | 凭据与参数 | 何时配置 |
| --- | --- | --- |
| 远程 YouTube API Server | `youtube_api_server.enabled`、`base_url`、`api_key` | 仅在你有可用的远程下载服务时填写；地址和 Key 由该服务的部署方提供。 |
| LLM Collector | `llm.collector_url`、`llm.collector_project`、`llm.collector_api_key` | 仅在使用单独部署的 Collector 服务时填写；不是公共模型服务商 Key。 |
| PostgreSQL | `LEARNFLUX_PERSISTENCE_BACKEND=postgres`、`DATABASE_URL` | `.env.example` 也提供 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`、`POSTGRES_SSLMODE` 作为连接参数；连接地址可能包含用户名和密码。按[迁移指南](postgresql.md)完成迁移后再切换。 |
| S3 对象存储 | `LEARNFLUX_OBJECT_BACKEND=s3`、`LEARNFLUX_S3_ENDPOINT_URL`、`LEARNFLUX_S3_BUCKET`、`LEARNFLUX_S3_REGION`、`LEARNFLUX_S3_ACCESS_KEY_ID`、`LEARNFLUX_S3_SECRET_ACCESS_KEY` | 仅在选择 S3 时需要；Endpoint 必须使用 HTTPS，凭据由你的对象存储服务商控制台提供。 |
| LongCut 本地集成 | `longcut.enabled`、`longcut.base_url`、`longcut.project_dir`，也可用 `LONGCUT_BASE_URL`、`LONGCUT_PROJECT_DIR` | 只有安装了 LongCut 并希望在 YouTube 结果页打开它时启用；不需要 API Key。 |
| 远程 ASR 基准脚本（开发验收） | `.env` 中的 `GROQ_API_KEY`，另需百炼的三个变量 | 只供 `tests/performance/remote_asr_benchmark.py` 显式付费验收使用，不是 LearnFlux 运行依赖；Groq Key 从 [GroqCloud 控制台](https://console.groq.com/keys)创建。 |

`.env.example` 还列出 PostgreSQL 部署 / 迁移辅助参数。运行普通本地版时，默认 `sqlite` + 本地文件即可，不需要填写数据库或 S3 凭据。

## 7. 保存、重启与排错

1. 复制对应模板，不要把真实值填进 `.example` 文件。
2. 在服务商控制台申请 Key，并确认账号权限、可用模型和计费状态。
3. 按表格把每个值填入指定配置项；不要把 API Key 当成 Base URL，也不要把 Workspace ID 当成 API Host。
4. 修改配置文件后运行 `./server.sh restart`；`.env` 中的新变量也需要重启后才会进入服务进程。
5. 打开 `/settings` 检查服务端已保存的配置，再用一条短任务确认调用链路。

调用失败时，先确认 Key、Base URL 和模型 ID 属于同一服务商；云端 ASR 还要确认 Workspace ID 与 `DASHSCOPE_API_HOST` 对应。查看日志或提交 Issue 前，遮盖 Key、数据库 URL 和带访问令牌的链接。

## 8. 凭据安全

- 不要提交 `config/config.jsonc`、`config/users.json`、`.env`、下载的 Cookie 或真实媒体数据。
- 不要把 Key 写入前端代码、截图、示例日志或 Issue；若意外公开，立即在服务商控制台撤销并重新生成。
- 公网部署时使用 HTTPS、强随机 `api.auth_token`、防火墙和访问控制。不要把本地单用户自动登录当作公网身份验证。

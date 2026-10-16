# 配置与 API Key 指南

本文说明如何从模板创建本地配置、哪些功能需要外部凭据，以及每项凭据应填入哪个字段。模板中的端口、监听地址和模型名是示例值，启动前请按本机环境修改。真实密钥和连接口令应保存在被 Git 忽略的本地文件或部署平台的受保护环境变量中。

## 1. 创建本地配置

初始化脚本会在配置文件不存在时自动复制模板：

```bash
bash scripts/bootstrap.sh
```

如果你已经安装好依赖，也可以手动复制：

```bash
cp config/config.example.jsonc config/config.jsonc
chmod 600 config/config.jsonc
```

仅当要启用云端 ASR、PostgreSQL 或 S3 时，才需要额外创建环境变量文件：

```bash
cp .env.example .env
chmod 600 .env
```

编辑前先确认 `config/config.jsonc` 和 `.env` 是本机文件，不要把它们提交到 Git。初始化脚本不会覆盖已有配置。配置项以 `config/config.example.jsonc` 和 `.env.example` 为准。

在 macOS / Linux 上，无论使用初始化脚本还是手动复制，都建议限制配置文件权限：

```bash
chmod 600 config/config.jsonc
```

## 2. 必需的本机管理口令

`api.auth_token` 是本实例的管理口令和 API Bearer Token，不是第三方平台 API Key。首次运行前请自行生成长随机值：

```bash
openssl rand -hex 32
```

将结果填入 `config/config.jsonc` 的 `api.auth_token`。Web 设置页用它验证管理员身份；命令行和 API 客户端则通过 `Authorization: Bearer <token>` 调用接口。不要复用下面列出的服务商 API Key。

若启用静态多用户模式，另见[多用户配置指南](multi_user_setup.md)。

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

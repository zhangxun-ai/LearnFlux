# 配置与 API Key 指南

先按目标平台和转录方式配置必要服务，再用真实链接验收；文字示例只用于排查基础模型问题。首次使用步骤见[本地快速开始](quickstart.md)。真实密钥保存在被 Git 忽略的本地配置或受保护的环境变量中。

## 先选真实使用路径

DeepSeek 等模型服务负责校对和解读，TikHub 负责相应平台的内容解析，ASR 负责语音识别；三者的 Key 不能互换。可先选一个常用平台，选中多个平台时分别验收。

| 目标 | 要准备什么 | 验收时要区分 |
| --- | --- | --- |
| YouTube 可用字幕 | 模型服务及可访问字幕 / 网络 | 字幕取得成功不代表 ASR 已运行 |
| 抖音视频 / 小红书视频 | 通常需要 TikHub、模型服务，语音内容需要可用 ASR；音视频处理准备 FFmpeg | 真正下载和识别语音，不能以图文或缓存替代 |
| 小红书图文 | TikHub、模型服务 | 只证明图文正文链路，不证明视频 / ASR |
| 本地 ASR | 当前普通链接 `local` 为 MLX Whisper，安装脚本仅支持 Apple Silicon Mac | 程序与模型安装后仍须真实识别验证 |
| 云端 ASR | 百炼三项 `DASHSCOPE_*`、启用 `cloud_asr.enabled`、选择 `cloud`、确认任务报价 | 单独的付费语音服务，不是 LLM Key 的附带能力 |

Intel Mac / Linux / Windows 不能套用 `--with-local-whisper`。当前普通链接的 `local` 不会回退 CapsWriter；只填写 CapsWriter 地址并不能使这个入口可用。已有其他兼容 ASR 调用路径须独立核对和验证，不把遗留页面标签当成引擎执行证据。当前平台缺少所需路径时，要说明兼容缺口，由用户选择可用方案，不能自动切换收费服务。

处理前确认本次链接、内容发送对象及费用范围：TikHub 可能收到链接，云端 ASR 接收媒体，模型服务接收正文 / 转录。只有真实内容取得、实际所需 ASR、真实 AI 解读及查看 / 导出都成功，才称该目标已可用；页面、Key 格式检查或离线 mock 都不是这项验收。

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

仓库中的 `.env.example` 可以公开，真实 `.env` 只留在本机。首次安装在项目根目录复制模板；已有文件时 `cp -n` 会保留原内容：

```bash
cp -n .env.example .env
chmod 600 .env
```

不要把 `config/config.jsonc`、`.env` 或前端保存密钥的 `data/config.db` 提交到 Git。配置项以 `config/config.example.jsonc` 和 `.env.example` 为准。

### 环境变量哪些必须填

**仅启动 SQLite 本机页面没有用户必填的凭据**；PostgreSQL 需要 `DATABASE_URL`，真实 AI 学习需要下面的模型配置。用户的 Key、服务地址和模型名建议只填写在自己的 `.env`，不要改源代码或公开模板。主文字模型和 TikHub 使用模板列出的 `LEARNFLUX_*` 名称，不会自动读取其他项目的 `OPENAI_API_KEY`、`LLM_API_KEY` 或 `TIKHUB_API_KEY`；手动图解的独立 `OPENAI_API_KEY` 见下表。

| 使用场景 | 必填项 / 位置 | 不使用时 |
| --- | --- | --- |
| 本机启动、阅读、写作 | 无需填写环境变量 | 保留模板默认值 |
| AI 解读、校对、问答 | `LEARNFLUX_LLM_API_KEY`、`LEARNFLUX_LLM_BASE_URL`、`LEARNFLUX_LLM_MODEL` | 无法验证依赖模型的学习结果；已有设置页配置可沿用 |
| 抖音 / 小红书等对应来源 | `LEARNFLUX_TIKHUB_API_KEY`，可选 `LEARNFLUX_TIKHUB_BASE_URL` | 不影响文字学习 |
| PostgreSQL | `LEARNFLUX_PERSISTENCE_BACKEND=postgres` 和 `DATABASE_URL`，先建专用账号和库；启动自动应用表结构迁移，SQLite 旧数据另行迁移 | 保留 `sqlite`，连接串留空 |
| S3 | `LEARNFLUX_OBJECT_BACKEND=s3` 和模板中的五个 `LEARNFLUX_S3_*` 连接 / 凭据项 | 保留 `local`，凭据留空 |
| 百炼云端 ASR | `DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`、`DASHSCOPE_API_HOST`，另在主配置启用 | 三项留空，云端 ASR 关闭 |
| 百炼次级模型端点 | `DASHSCOPE_API_KEY`，且端点显式配置 `api_key_env` | 留空；不会自动替代主模型配置 |
| 手动 AI 图解 | `OPENAI_API_KEY`，使用 OpenAI 官方服务，与主文字模型独立 | 留空时不可生图；显式生成可能计费，见[图解指南](image-diagrams.md) |
| LongCut / 视频号本地解密服务 | 模板中的地址、路径覆盖项，按对应能力配置 | 留空沿用主配置 |
| 飞书交付状态 / 日报集成 | 可选私有配置路径 `LEARNFLUX_FEISHU_ARCHIVE_CONFIG` / `LEARNFLUX_BRIEFINGS_CONFIG` | 保持注释，不能设成空值覆盖默认路径 |

`main.py` 启动时自动加载项目根目录 `.env`，已有进程环境变量优先，修改后需重启。文件按 `python-dotenv` 语法读取，不要把未知来源的 `.env` 当 Shell 脚本 `source` 执行。`POSTGRES_*` 是部署 / 迁移辅助项，不会自动拼装 `DATABASE_URL`，也不代替应用连接串。

应用配置优先级为 **非空环境变量 > 已保存的设置覆盖 > 私有 JSONC 配置**。环境变量不会写回数据库；设置页对这些字段显示只读提示，保存其他字段时不会把它们一并存入库中。移除环境变量并重启后恢复已有配置。`LEARNFLUX_LLM_MODEL` 统一覆盖主 LLM 的各任务模型，单独的 `LEARNFLUX_LLM_SUMMARY_MODEL` 等变量优先于通用模型。

监听地址、端口和管理口令也可用 `LEARNFLUX_API_HOST`、`LEARNFLUX_API_PORT`、`LEARNFLUX_AUTH_TOKEN` 配置；留空沿用初始化生成的私有配置。转录服务、YouTube 远程服务、Obsidian 路径与 Collector 的可选覆盖项见模板，配置地址 / Key 不等于启用对应能力。

独立工具有各自的配置入口，不会自动读取这份根目录 `.env`：飞书归档 worker 使用 `--config`；数据库迁移工具使用已导出的环境变量或参数；Agent CLI 使用自己的私有配置，详见各自指南。`server.sh` 的管理参数也应在运行脚本的进程环境设置。Docker 当前不自动注入宿主机 `.env`，需要按容器部署方式单独传入；不要复制真实 `.env` 到镜像中。

## 2. 本机管理口令

`api.auth_token` 是本实例的管理口令和 API Bearer Token，不是模型服务商的 API Key。初始化时已自动生成，无需另运行生成命令。

默认单用户模式下，直接访问本机地址的浏览器可以自动连接。需要手动验证、使用手机或调用 API 时，在自己的电脑上使用生效的管理口令：优先为 `.env` 的 `LEARNFLUX_AUTH_TOKEN`，未设置时为私有 `config/config.jsonc` 的 `api.auth_token`；不要把它复制到聊天、日志、截图或 Issue。静态多用户模式另见[多用户配置指南](multi_user_setup.md)。

## 3. 大模型 API

LLM API 用于转录校对、总结、问答、图解和复盘等 AI 功能。没有可用 LLM Key 时，导入和基础转录仍可单独配置使用，但不会产生依赖模型的结果。

| 用户要准备的内容 | 配置位置 | 说明 |
| --- | --- | --- |
| 服务商 API Key | `.env` 的 `LEARNFLUX_LLM_API_KEY` | 从你选择的模型服务商控制台创建。 |
| API Base URL | `.env` 的 `LEARNFLUX_LLM_BASE_URL` | 填服务商提供的 OpenAI 兼容接口地址；不要填到 `/chat/completions`。 |
| 模型 ID | `.env` 的 `LEARNFLUX_LLM_MODEL`；按需单独指定各任务模型 | 必须是该 Key 和 Base URL 可调用的模型名称。不同任务可以使用不同模型。 |

默认可引导 DeepSeek 用户在[官方控制台](https://platform.deepseek.com/api_keys)创建 Key，Base URL 按[官方首次调用说明](https://api-docs.deepseek.com/quick_start/your_first_api_call.md)填写。模型 ID 从账号当前可用列表选择，参考[官方模型查询接口](https://api-docs.deepseek.com/api/list-models/)；不要把旧截图中的模型名当作长期固定值。官方 SDK 示例使用的 `DEEPSEEK_API_KEY` 不会自动替代本项目的 `LEARNFLUX_LLM_API_KEY`。

已有用户可继续在 Web 的 `/settings` 页面保存未被环境变量管理的 LLM 配置；其他高级选项仍可在私有 `config/config.jsonc` 中设置。配置模板中的模型名只是示例默认值；换服务商后，请按其官方文档改成实际可用的模型 ID，并确认账号已开通对应模型及额度。

换服务商还需要核对 `llm.model_endpoints` 与 `llm.endpoints`。模板默认将 `qwen*` 路由到名为 `dashscope` 的百炼次级端点，该端点从 `DASHSCOPE_API_KEY` 读取密钥；只填写主模型的三项 `LEARNFLUX_LLM_*`，不能保证 Qwen 请求会使用主端点。如果希望 Qwen 走自己配置的主 Base URL，需在私有配置中移除或调整匹配的 Qwen 路由；若继续使用百炼次级端点，则配置它实际需要的 Key。最后用目标模型的真实调用确认，不以设置页保存成功代替验证。

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
| API Key | `.env` 的 `LEARNFLUX_TIKHUB_API_KEY` | 在 [TikHub 用户中心](https://user.tikhub.io/dashboard/api) 创建或复制 API Token。 |
| Base URL | `.env` 的 `LEARNFLUX_TIKHUB_BASE_URL` | 模板默认使用 `https://api.tikhub.io`；仅在服务商文档明确要求时更改。 |

TikHub 的 Token 获取与 Bearer 使用方式以[官方文档](https://docs.tikhub.io/186826050e0)为准，主域名以[官方连接说明](https://docs.tikhub.io/)为准。实际解析所选链接前确认权限、额度与费用，不把测试 Key 或账号查询视为必然免费。

将真实 Key 填到自己的 `.env`，不要写入 `.env.example` 或公开截图。已有 `/settings` / 私有主配置仍可沿用；环境变量非空时优先。

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

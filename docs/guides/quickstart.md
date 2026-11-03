# 第一次使用 LearnFlux

以你常用平台的一条真实链接完成“解析 / 下载 → 字幕、正文或语音识别 → AI 解读 → 导出”的首次验收。示例文字仅用来排查页面与模型，不代表链接或 ASR 可用。新用户可直接复制 [README 顶部提示词](../../README.md#不懂代码复制这段提示词给-ai)，让 Agent 按平台与转录方式引导。

默认数据库仍是 SQLite；已有 PostgreSQL 保留原连接。选择 PostgreSQL 时按[数据库指南](postgresql.md)准备服务、专用账号与库，首次启动自动创建表结构。

先确定下列选择：

- 目标平台：YouTube / 抖音 / 小红书，可多选；每个选中的平台分别验收。
- 真实样例：有权处理、公开可访问的短内容。需要验证 ASR 时，使用未缓存、确需语音识别的口播视频；小红书图文不能代替视频 ASR，抖音图集暂不作为视频验收样例。
- 转录方式：Apple Silicon Mac 可用当前 MLX Whisper 本地路径；其他系统先核对能力，或在接受费用后选择云端。YouTube 有字幕时可不转录，但应标明 ASR 未验证。

## 1. 安装并启动

准备 Git、Bash、curl、lsof 和可访问依赖源的网络。macOS 通常已自带 lsof；Linux 若缺少它，请先通过系统包管理器安装（例如 Ubuntu / Debian：`sudo apt-get install lsof`）。macOS / Linux 在项目根目录运行：

```bash
cp -n .env.example .env
chmod 600 .env
bash scripts/bootstrap.sh --with-media
bash server.sh start
```

`bootstrap.sh` 用于首次安装：安装 uv（如尚未安装），由 uv 准备 Python 3.11 和应用依赖，并创建只供本机使用的配置。已有配置和数据保持原样；若仅有旧 `config/config.json`，脚本会保留它并提示迁移到 `config/config.jsonc`。以后启动只需 `bash server.sh start`。

`.env.example` 是随仓库分发的空凭据模板；`cp -n` 不覆盖已有 `.env`。只启动 SQLite 本机页面无需填写凭据；真实 AI 学习需填写下面的模型环境变量。PostgreSQL、云端 ASR、S3 等启用条件见[配置指南](configuration.md)。不要把真实值写回 `.env.example`，也不要把 `.env` 上传到 GitHub。

`server.sh` 后台运行服务，关闭终端后仍可访问。macOS 使用用户级 LaunchAgent，用户登录时也会自动启动；执行 `bash server.sh stop` 会卸载该启动项。Linux 使用 nohup，不会自动配置开机启动。

默认端口为 **8000**。`LEARNFLUX_API_PORT` 非空时优先，否则读取 `config/config.jsonc` 的 `api.port`；启动脚本与应用使用同一规则。看到启动成功后，用浏览器打开：

- 工作台：<http://127.0.0.1:8000/add_task_by_web>
- 设置：<http://127.0.0.1:8000/settings>

如果已有配置更改了端口或监听地址，请以配置与启动日志为准。新配置仅监听本机，手机不能直接访问这个回环地址；手机接入见[手机快捷指令指南](mobile-shortcut.md)。

日常管理也在项目根目录运行：

```bash
bash server.sh status   # 查看运行状态
bash server.sh log      # 查看实时日志，Ctrl+C 只退出日志查看
bash server.sh restart  # 修改配置或更新代码后重启
bash server.sh stop     # 停止服务并卸载 macOS 启动项
```

日志文件为 `data/logs/server.out.log`。若提示找不到 uv，重新打开终端，或把 uv 的安装目录（通常是 `~/.local/bin`）加入 PATH；`server.sh` 也会自动查找 `~/.local/bin/uv` 和 `~/.cargo/bin/uv`，并优先使用项目 `.venv` 中的 Python。

首次安装可能需要下载较大的依赖包，不把下载时长算作解析耗时。扫描 PDF 的 OCR 已拆为可选依赖，默认不会安装。

Windows 用户可先在 WSL2 中使用 Linux 路径；本轮没有验证 Windows 原生安装。Docker 是面向已有容器使用经验的替代路径，见下文。

## 2. 配置模型与目标平台

默认引导使用 DeepSeek，也可复用已有可用的 OpenAI 兼容服务。在自己的 `.env` 填 `LEARNFLUX_LLM_API_KEY`、`LEARNFLUX_LLM_BASE_URL`、`LEARNFLUX_LLM_MODEL`；模型 ID 以当前账号可调用的列表为准。不要把官方 SDK 示例的 `DEEPSEEK_API_KEY` 当成项目读取名。

要解析抖音或小红书，再填写 `.env` 的 `LEARNFLUX_TIKHUB_API_KEY`，按需覆盖 `LEARNFLUX_TIKHUB_BASE_URL`。TikHub 负责平台内容解析，不替代模型或 ASR。只有 YouTube 字幕 / 文字学习时通常不需要它。

Key 的官方入口与完整字段见[配置指南](configuration.md)。模型和 TikHub 的额度、接口权限与本次费用范围都需要确认；填好了字段不等于真实调用已成功。修改后 `bash server.sh restart`，在系统设置核对生效状态，环境变量字段只读、密钥脱敏。已有设置页配置仍可沿用。

## 3. 配好实际要用的 ASR

### 本地转录

音视频处理需 FFmpeg / ffprobe。Apple Silicon Mac 运行：

```bash
bash scripts/bootstrap.sh --with-local-whisper
```

按脚本输出设置私有 `config/config.jsonc` 的 `local_whisper.binary`、`model`、`enabled` 等，检查程序可执行；首次使用会下载模型。准备好后在页面选择本地转录。

**当前普通链接的 `local` 策略固定走 MLX Whisper，不会自动回退 CapsWriter。** Intel Mac、Linux、Windows 不能照搬 MLX 安装；只填 CapsWriter WebSocket 地址不能说明这个入口已可用。CapsWriter 仍供其他兼容调用路径使用，不能混作普通链接本地策略的验收。当前平台若缺少可用本机路径，应明确记录，并由用户选择已支持的云端方案，或另行解决本地兼容，不擅自切到收费服务。

### 云端转录

项目当前使用百炼云端 ASR。在自己的 `.env` 填 `DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`、`DASHSCOPE_API_HOST`，Host 与同一 Workspace 的北京节点匹配；在私有主配置显式启用 `cloud_asr.enabled`，选择 `cloud`。

提交后先准备音频并展示任务报价，用户确认费用上限后才提交云端识别。DeepSeek / TikHub 的 Key 不能替代这些 ASR 凭据；不要重发提交状态未知的付费请求。完整配置见[云端 ASR](configuration.md#5-阿里云百炼云端-asr)。本地转录不产生云端 ASR 费用，但模型、TikHub 等调用仍可能收费。

## 4. 用真实链接验收

1. 明确本次内容会发送给哪些服务及费用范围后，在“单篇深度学习”粘贴选中的真实链接，选择已配置的本地 / 云端转录并提交。
2. 等待任务完成，核对来源、标题及内容；分别标明取得的是平台字幕、图文正文还是实际 ASR 转录。要验 ASR，必须有真实语音识别结果，缓存命中或字幕可用不算 ASR 通过。
3. 核对原文覆盖和真实 AI 解读与来源相符，实际导出原文 / 解读并打开检查完整性。
4. 刷新后从历史记录重新打开；可安全停止的新实例再重启验证持久保存。已有服务不未经同意中断。

只测 YouTube 不能宣称抖音、小红书均通过；只测本地也不能宣称云端 ASR 已通过。缺 Key、额度、授权或兼容条件时，明确列出未完成项和本机补齐步骤。示例文字、页面可打开、模型列表、已受理状态或模拟结果都不能替代真实链接验收。

## 按需要扩展

- 音视频：`bash scripts/bootstrap.sh --with-media`，随后配置转录引擎。
- Apple Silicon Mac 本机转录：`bash scripts/bootstrap.sh --with-local-whisper`，按输出提示启用 `local_whisper`。
- 扫描 PDF：`uv sync --extra ocr`，重启后在书架重试 OCR。
- 开发测试：`bash scripts/bootstrap.sh --dev`；验证命令见[测试说明](../../tests/README.md)。

需要前台排错时，先执行 `bash server.sh stop`，再运行 `uv run python main.py --start`，按 `Ctrl+C` 停止前台服务。前台运行期间必须保留终端；不要同时启动两个实例。

## Docker 替代路径

当前 Dockerfile 使用仓库中的 Linux amd64 BBDown；Compose 明确选择 `linux/amd64`。Apple Silicon 机器需要 Docker 的 x86 模拟，不能把它当作原生 ARM 镜像。

1. 在项目根目录运行 `python3 scripts/init_config.py` 创建配置。**当前 Compose 不会把宿主机根 `.env` 注入容器**；这条默认容器路径需在私有 `config/config.jsonc` 填写 `llm.api_key`、`llm.base_url`、`llm.calibrate_model`、`llm.summary_model`，或启动后在容器的设置页保存。不要把真实值写进 Dockerfile 或提交到 Git。
2. 仅为容器运行，把 `config/config.jsonc` 中的 `api.host` 改为 `0.0.0.0`。容器需要监听自己的网络接口；Compose 仍只把宿主机 `127.0.0.1:8200` 映射到它。
3. 执行：

   ```bash
   docker compose -f docker/docker-compose.yml up --build -d
   ```

4. 打开 <http://127.0.0.1:8200/add_task_by_web>。容器访问通常需要使用本机配置中的管理口令完成连接；不要公开该口令。

配置与数据通过 `config/`、`data/` 挂载保留。构建上下文使用允许列表，不包含运行配置、`.env` 和用户数据。该容器路径本轮仅通过 Compose 配置解析，未完成镜像构建和容器运行验收，不作为首次体验的推荐入口。

若要在容器中使用本指南的环境变量、PostgreSQL 或手动图解，需要在自己的私有 Compose 部署配置中显式增加服务级 `env_file` 或 `environment`。为容器单独准备环境文件，数据库主机须在容器网络中可达，不能照搬宿主机的 `127.0.0.1`；监听地址须为 `0.0.0.0`，容器端口与映射保持一致。Compose 的 `--env-file` 仅用于配置插值，单独指定它不等于把所有值传入容器。真实环境文件应被 Git 忽略，不能复制进镜像。本轮未验证这一额外部署路径。

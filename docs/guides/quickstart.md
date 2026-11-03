# 第一次使用 LearnFlux

先用一小段文字体验“导入 → AI 解读 → 保存结果”。这条路径不需要转录模型、TikHub、飞书或 Obsidian。下面的手动最小安装使用 SQLite；按项目日常方案使用 PostgreSQL 时，先完成[安装、建库与自动建表](postgresql.md)。不熟悉这些操作，可直接复制 README 顶部的[新手安装提示词](../../README.md#不懂代码复制这段提示词给-ai)：新安装默认 SQLite，已有 PostgreSQL 保留原连接，需要时再走建库流程。

## 1. 安装并启动

准备 Git、Bash、curl、lsof 和可访问依赖源的网络。macOS 通常已自带 lsof；Linux 若缺少它，请先通过系统包管理器安装（例如 Ubuntu / Debian：`sudo apt-get install lsof`）。macOS / Linux 在项目根目录运行：

```bash
cp -n .env.example .env
chmod 600 .env
bash scripts/bootstrap.sh
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

## 2. 填好一个模型服务

在本机 `.env` 中填写 `LEARNFLUX_LLM_API_KEY`、`LEARNFLUX_LLM_BASE_URL`、`LEARNFLUX_LLM_MODEL`，然后运行 `bash server.sh restart`。三项应来自同一可用服务；通用模型会用于校对、总结、问答等任务。打开“系统设置”核对生效状态，环境变量管理的字段显示为只读、密钥脱敏。已有用户没有设置这些环境变量时，仍可沿用网页保存的配置。

AI 请求按你选择的服务商规则计费。本地安装不会替你申请密钥或开通服务。字段解释及更多集成见[配置与 API Key](configuration.md)。

## 3. 完成第一份学习笔记

打开“单篇深度学习”，选择“粘贴文字”，输入一段你愿意测试的内容。例如：

> 每周留出两个晚上学习一个小主题。每次先写下一个问题，再阅读两份资料；结束时用自己的话记下三个要点，并把没弄懂的问题留到下一次。

点击“开始学习”，等待近期任务显示完成，再打开结果页。能看到原文和 AI 解读，就完成了第一次使用。你可以直接阅读、导出；需要同步到外部知识库时再配置对应服务。

若页面能打开但任务失败，先核对设置中的 Key、接口地址和模型是否配套；“页面启动”和“真实 AI 调用成功”是两项不同的验证。

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

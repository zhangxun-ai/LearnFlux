# LearnFlux

> 把视频、音频和文档变成可理解、可追问、可沉淀的学习材料。

LearnFlux 是面向个人学习和内容研究的 AI 工作台：导入链接或本地文件，获得逐字稿、AI 解读、视觉图解、系列知识地图和可同步到 Obsidian 的笔记。它不是一个只返回文本的“转录 API”，而是把内容输入推进到理解与复习的完整学习流程。

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT%20%2B%20Commons%20Clause-yellow.svg)](LICENSE)

## 它能做什么

- 导入 YouTube、Bilibili、抖音、小红书、小宇宙，以及本地音视频和文档。
- 将内容转录为带时间轴的文本，并用 AI 校对、总结、解释难点和追问全文。
- 在同一时间轴中边播边学：当前字幕、逐字稿、AI 解读、图解和个人笔记互相联动。
- 管理系列课程或专题资料：生成集合知识地图、全系列解读和 Obsidian Markdown 笔记。
- 从帖子、评论和账号内容中提取洞察，辅助选题与内容研究。

## 先选适合你的安装方式

| 你的情况 | 推荐路径 | 需要额外的转录服务 |
| --- | --- | --- |
| Apple Silicon Mac，想在本机转录 | 本地 `mlx-whisper` | 不需要 CapsWriter；说话人识别仍可选 FunASR |
| Linux、Windows 或独立服务器 | LearnFlux + CapsWriter | 需要一个可访问的 CapsWriter WebSocket 服务 |
| 需要区分说话人 | 任意基础路径 + FunASR | 仅在提交时启用“说话人识别”才需要 |
| 只处理已有字幕或文档 | LearnFlux 本体 | 通常不需要 ASR 服务 |

`LLM` 和 `TikHub` 不是启动服务的硬前提，但分别决定 AI 解读/总结与部分社媒平台解析、洞察功能是否可用。

## 三分钟启动：本机基础环境

需要 Git 和网络连接。以下命令会安装项目 Python 依赖、检查或安装 FFmpeg，并且只在配置文件不存在时从示例创建它；**不会覆盖已有 `config/config.jsonc`**。

```bash
git clone https://github.com/zhangxun-ai/LearnFlux.git
cd LearnFlux
bash scripts/bootstrap.sh
```

脚本会在缺少 FFmpeg 时使用 Homebrew（macOS）或 `apt`（Debian/Ubuntu）安装它；没有对应包管理器时会给出明确的手动安装提示。它使用 `uv` 管理 Python 环境，等价的依赖同步命令是：

```bash
uv sync --extra dev
```

### Apple Silicon Mac：一键启用本地转录

如果你使用 Apple Silicon Mac（M 系列芯片），可以在上一节的命令后运行：

```bash
bash scripts/bootstrap.sh --with-local-whisper
```

这会把官方 [`mlx-whisper`](https://github.com/ml-explore/mlx-examples/tree/main/whisper) 安装到 `~/.venvs/mlx-whisper`。首次真正转录时会下载所选模型。随后在 `config/config.jsonc` 中加入或更新以下配置：

```jsonc
"local_whisper": {
  "enabled": true,
  "binary": "~/.venvs/mlx-whisper/bin/mlx_whisper",
  "model": "mlx-community/whisper-large-v3-turbo",
  "language": "",
  "timeout": 1800
}
```

启用后，普通音视频转录优先使用本地引擎，不再依赖 CapsWriter。该模式不提供说话人识别；如需区分说话人，请继续配置 FunASR。

## 配置一次，按需开启能力

所有本机密钥都放在被 Git 忽略的 `config/config.jsonc`，请从模板生成，绝不要提交真实密钥。

```bash
cp config/config.example.jsonc config/config.jsonc
```

至少检查以下配置项：

| 配置 | 何时需要 | 说明 |
| --- | --- | --- |
| `api.auth_token` | 建议始终设置 | Web/API 管理口令和 Bearer Token。 |
| `llm.api_key`、`llm.base_url` | AI 校对、总结、问答、图解 | 使用任意 OpenAI 兼容服务。 |
| `tikhub.api_key` | 抖音、小红书、部分社媒解析与洞察 | 在 [TikHub](https://user.tikhub.io/register?referral_code=YArXsaWi) 获取。 |
| `capswriter.server_url` | 未启用本地 `mlx-whisper` 的音视频转录 | 默认 `ws://localhost:6016`。 |
| `funasr_spk_server.server_url` | 说话人识别 | 默认 `ws://localhost:8767`；仅按需使用。 |

### 远程或局域网转录服务

非 Apple Silicon 环境可以部署或连接到现有的 [CapsWriter-Offline](https://github.com/HaujetZhao/CapsWriter-Offline) 服务，并填写：

```jsonc
"capswriter": {
  "server_url": "ws://YOUR_ASR_HOST:6016"
}
```

如果需要按说话人分段，另行部署 [funasr_spk_server](https://github.com/zj1123581321/funasr_spk_server)，并填写：

```jsonc
"funasr_spk_server": {
  "server_url": "ws://YOUR_ASR_HOST:8767"
}
```

CapsWriter 和 FunASR 是独立的计算服务，硬件、模型和部署方式取决于你的机器，因此 LearnFlux 不会在安装脚本中猜测性地自动部署它们。启动后访问 `GET /health` 可以检查当前启用的本地/远程服务状态。

## 启动、检查与停止

```bash
./server.sh start
curl -s http://localhost:8000/health
```

浏览器打开 [http://localhost:8000](http://localhost:8000) 后，先在 `/settings` 填写 AI 服务和 TikHub 等可选配置，再开始导入内容。

```bash
./server.sh status
./server.sh log
./server.sh restart
./server.sh stop
```

## Docker 部署

Docker 镜像已包含 FFmpeg、BBDown 和 yt-dlp；转录服务仍需独立提供。将 CapsWriter/FunASR 部署在容器外时，配置中不能使用容器内的 `localhost`，请填写宿主机 IP、局域网地址或 `host.docker.internal`。

```bash
cp config/config.example.jsonc config/config.jsonc
cd docker
docker compose up -d
```

Compose 会从当前源码构建并标记镜像为 `ghcr.io/zhangxun-ai/learnflux:latest`。

## 常用入口

- 单篇内容学习：`/add_task_by_web`
- 系列课程与知识地图：`/collections`
- 边播边学：`/study`
- 帖子/评论洞察：`/post`
- 趋势雷达：`/trend-radar`
- IP 对标工作台：`/flywheel`
- 设置中心：`/settings`

API 调用示例：

```bash
curl -X POST "http://localhost:8000/api/transcribe" \
  -H "Authorization: Bearer your-auth-token" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=xxx",
    "use_speaker_recognition": false
  }'
```

## 项目结构

```text
LearnFlux/
├── src/video_transcript_api/  # FastAPI、下载、转录、AI 与学习功能
├── config/                    # 配置模板；真实配置被 Git 忽略
├── docker/                    # Docker Compose 与镜像构建
├── scripts/bootstrap.sh       # 新用户初始化命令
├── server.sh                  # 本地服务启停管理
├── tests/                     # pytest 测试套件
└── docs/                      # 功能、配置和开发文档
```

## 测试

```bash
uv run --extra dev pytest tests/unit
uv run --extra dev pytest
```

功能、集成、LLM、平台、手动和性能测试可能需要网络、服务或真实凭据；请按 [tests/README.md](tests/README.md) 中的具体文件单独执行。

## 更多文档

- [文档中心](docs/README.md)
- [系统架构](docs/architecture.md)
- [通知配置](docs/guides/notification.md)
- [多用户配置](docs/guides/multi_user_setup.md)
- [FunASR 客户端 API](docs/guides/api/funasr_spk_server_client_api.md)

## 开源协议

基于 **MIT + Commons Clause** 开源。允许非商业用途的学习、修改、分发；禁止售卖或商业集成。详见 [LICENSE](LICENSE)。

# 第一次使用 LearnFlux

先用一小段文字体验“导入 → AI 解读 → 保存结果”。这条路径不需要转录模型、TikHub、PostgreSQL、飞书或 Obsidian。

## 1. 安装并启动

准备 Git、Bash、curl 和可访问依赖源的网络。macOS / Linux 在项目根目录运行：

```bash
bash scripts/bootstrap.sh
uv run python main.py --start
```

初始化脚本会安装 uv（如尚未安装），由 uv 准备 Python 3.11 和应用依赖，并创建只供本机使用的配置。已有配置和数据保持原样。看到服务启动后，用浏览器打开：

- 工作台：<http://127.0.0.1:8000/add_task_by_web>
- 设置：<http://127.0.0.1:8000/settings>

首次安装可能需要下载较大的依赖包，不把下载时长算作解析耗时。扫描 PDF 的 OCR 已拆为可选依赖，默认不会安装。

Windows 用户可先在 WSL2 中使用 Linux 路径；本轮没有验证 Windows 原生安装。Docker 是面向已有容器使用经验的替代路径，见下文。

## 2. 填好一个模型服务

打开“系统设置”，填写你已有服务的 API Key、接口地址和可用模型。校对与总结使用的模型都应能被同一配置调用。保存后再提交资料；API Key 只保存在你自己的机器上。

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

前台启动时按 `Ctrl+C` 停止。需要后台运行时，可改用项目根目录的 `./server.sh start`、`./server.sh status` 与 `./server.sh stop`；不要同时重复启动两个实例。

## Docker 替代路径

当前 Dockerfile 使用仓库中的 Linux amd64 BBDown；Compose 明确选择 `linux/amd64`。Apple Silicon 机器需要 Docker 的 x86 模拟，不能把它当作原生 ARM 镜像。

1. 在项目根目录运行 `python3 scripts/init_config.py` 创建配置，并按前文填写模型。
2. 仅为容器运行，把 `config/config.jsonc` 中的 `api.host` 改为 `0.0.0.0`。容器需要监听自己的网络接口；Compose 仍只把宿主机 `127.0.0.1:8200` 映射到它。
3. 执行：

   ```bash
   docker compose -f docker/docker-compose.yml up --build -d
   ```

4. 打开 <http://127.0.0.1:8200/add_task_by_web>。容器访问通常需要使用本机配置中的管理口令完成连接；不要公开该口令。

配置与数据通过 `config/`、`data/` 挂载保留。构建上下文使用允许列表，不包含运行配置、`.env` 和用户数据。该容器路径本轮仅通过 Compose 配置解析，未完成镜像构建和容器运行验收，不作为首次体验的推荐入口。

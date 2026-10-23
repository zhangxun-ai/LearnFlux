# 本地快速启动提示词

适用于 Codex、Claude Code、WorkBuddy 等具有本机终端与文件权限的 Agent。推荐 Apple Silicon Mac，提示词也要求识别其他平台的实际能力。复制整个代码块即可；无需把 API Key 发到对话里。

```text
请在我的电脑上安装并启动 LearnFlux，完成到可以实际使用。我授权安装缺少的项目依赖；涉及管理员权限、新建付费服务或开放公网时先说明。

1. 先阅读 https://github.com/zhangxun-ai/LearnFlux 的 README、AGENTS.md 和 scripts/bootstrap.sh。
   已有仓库就复用，没有再克隆；保留已有配置、数据、虚拟环境和正在运行的服务。
2. 检查操作系统、CPU 架构、磁盘、Git、Python、uv、FFmpeg 与端口。
   使用仓库固定的 Python 版本；安装缺少的依赖后检查当前终端的 PATH。
3. Apple Silicon Mac 优先使用本机 mlx-whisper。
   先检查已有安装；需要新装时使用 bash scripts/bootstrap.sh --with-local-whisper，并在配置中启用 local_whisper、填写实际可执行文件路径。
   脚本只安装依赖，首次转录还会下载模型，请先告知磁盘和下载要求。
4. Intel Mac、Linux、Windows 不套用 MLX 安装。
   先核对当前转录策略与平台支持；可以先跑通文本学习。
   若音视频路径尚不兼容，明确说明，不把网页能打开当成转录可用。
5. 仅在 config/config.jsonc 不存在时从模板创建。
   为新配置生成随机 api.auth_token，默认只监听 127.0.0.1，个人本机开启 browser_local_auto_login。
   密钥仅在本机保存和使用，不输出到聊天、终端、截图或 Git。
6. AI 解读需要有效的 LLM API Key、Base URL 和模型。
   检查配置是否齐全，缺少时告诉我应在本机设置页填写哪些字段；不要要求我把密钥发到聊天。
   TikHub 仅在需要对应社媒来源时配置，PostgreSQL、飞书、隧道和云端 ASR 都不作为基础安装前置项。
7. 在仓库根目录使用 ./server.sh start；需要前台排错时用 uv run python main.py --start。
   端口被占用时识别已有服务，不擅自结束进程；不要重复创建启动项。
8. 打开本地工作台，检查 /health 并解释异常组件。
   已有 LLM 配置时，用不含隐私的短文本完成一次学习；启用本地转录后另用我允许的短音频验证实际结果。
   不要未经确认调用付费云端 ASR。
9. 分别汇报“页面启动、AI 学习、本机转录”哪些已验证，给出访问地址和仍缺少的配置。
   需要密钥或人工授权才继续的步骤，明确列出，不声称全部成功。
```

这是一份安装任务说明，不代表上述 Agent 已内置专用插件。初始化脚本不会替你申请密钥、完成飞书授权或配置公网域名。服务启动与一次真实学习完成是不同的验收项。

按需扩展见 README 的[服务配置提示词](../../README.md#按需配置服务给-agent-的提示词)。

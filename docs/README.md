# LearnFlux 文档中心

本页按使用场景整理当前项目文档。新用户建议从根目录 [README](../README.md) 开始，完成安装和首次使用后，再按需查阅配置、API 和运维指南。

## 用户指南

| 文档 | 内容 |
| --- | --- |
| [配置与 API Key](guides/configuration.md) | 配置文件复制、第三方 Key 来源、必填字段、环境变量与凭据安全 |
| [API Quick Start](guides/api/quickstart.md) | Bearer Token、提交任务、轮询状态和获取结果 |
| [TikHub 与小红书 API](guides/api/tikthub_xiaohongshu.md) | TikHub 接入和小红书相关接口 |
| [YouTube 下载客户端](guides/api/youtube_client_guide.md) | YouTube 下载器配置 |
| [BBDown 指南](guides/api/bbdown_guide.md) | Bilibili 下载器配置 |
| [FunASR 客户端 API](guides/api/funasr_spk_server_client_api.md) | FunASR WebSocket 服务与响应格式 |
| [多用户配置](guides/multi_user_setup.md) | 本地静态 API Token 配置 |
| [手机快捷指令](guides/mobile-shortcut.md) | 手机直达本地任务、隧道范围、独立令牌和验收 |
| [自动保存到飞书知识库](guides/feishu-archive.md) | 将完整解析结果自动归档为飞书文档，并持久化重试与去重状态 |
| [读取飞书文档（开发中）](guides/feishu-documents.md) | 将 Wiki/Docx 正文送入深度学习，保留来源及读取范围；实现尚未合入 main |
| [PostgreSQL 指南](guides/postgresql.md) | SQLite 到 PostgreSQL 的迁移、验收和回滚 |

新用户可以复制[本地快速启动提示词](prompts/macos-local-quick-start.md)，交给有本机终端权限的 Codex、Claude Code 或 WorkBuddy 检查依赖并启动服务，优先验证 Apple Silicon Mac 的本机转录路径。飞书归档、手机快捷入口和其他 ASR 的独立配置提示词见 [README 的服务配置](../README.md#按需配置服务给-agent-的提示词)，无需全部安装。

## 功能说明

- [原始内容导出](features/raw_export.md)
- [来源链接与元数据覆盖](features/source_url_and_metadata_override.md)
- [YouTube 字幕统一处理](features/youtube_transcript_unified.md)

## 开发与架构

- [系统架构](architecture.md)：模块边界、处理流程和持久化。
- [开发与验证规则](../AGENTS.md)：项目结构、命令、代码风格和验证边界。
- [测试说明](../tests/README.md)：默认离线验证及需显式运行的外部检查。
- [LLM 工程指南](development/llm/engineering_guide.md)：模型调用、结构化输出与错误处理。
- [Gemini OpenAI 兼容模式](development/llm/gemini_openai_compat.md)。
- [JSON 输出模式](development/llm/json_output.md)。
- [结构化校对配置](development/llm/structured_calibration_guide.md)。
- [并发处理](development/concurrency.md)、[日志](development/logging.md)、[风控](development/risk_control.md)和 [Web 视图](development/web_view.md)。
- [复盘模块设计](review_module_plan.md)：数据模型、AI 候选与用户确认边界。

过往方案、已完成设计和阶段性实施记录集中在 [`superpowers/`](superpowers/) 与 [`development/archive/`](development/archive/)。它们用于追溯背景；实际行为以当前代码、配置模板和测试为准。

## 配置模板与常用入口

- [主配置模板](../config/config.example.jsonc)
- [环境变量模板](../.env.example)
- [多用户模板](../config/users.example.json)
- [项目 README](../README.md)
- [许可证](../LICENSE)

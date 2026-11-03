# 新手安装与首次学习：给 Agent 的提示词

不需要先学 Git 或终端。复制下面整个代码块，发给 WorkBuddy、Codex、Claude Code 等能操作本机终端和浏览器的 Agent。默认引导 PostgreSQL 安装、建库与表结构初始化，再跑通一次文字学习；音视频等按需追加。文件名沿用旧版，内容适用于 macOS / Linux，Windows 先核对 WSL2 能力。

真实密钥只填在你自己的电脑上，不要附在这段提示词或聊天里。没有模型服务时，Agent 应引导你在本机准备凭据，并明确当前尚未完成真实 AI 验证。

```text
我是第一次使用 LearnFlux，不懂 Git、数据库和终端。请直接操作我的电脑安装并验证项目；遇到需要我参与的登录、密码输入或费用确认，用中文告诉我在哪个窗口做什么、完成后应看到什么。不要只给一串命令后就结束。

项目地址：https://github.com/zhangxun-ai/LearnFlux
目标：完成“安装 → PostgreSQL 建库和建表 → 配置模型 → 导入资料 → AI 解读 → 查看结果 → 导出”，并确认结果能持久保存。我授权安装缺少的项目依赖；需要管理员权限、新建付费服务、付费调用、开放公网、清空或迁移已有数据时，先说明具体动作并取得同意。

1. 先读当前仓库的 README、AGENTS.md、.env.example、scripts/bootstrap.sh、server.sh、docs/guides/configuration.md 和 docs/guides/postgresql.md。
   复用已有仓库和正在运行的服务；没有仓库时帮我选择用户可写的目录并克隆。不要覆盖已有文件、强制切分支或替我提交/推送代码。
   检查系统、CPU、网络、磁盘、Git、Bash、curl、lsof、uv、Python 与默认 8000 端口。缺工具时按当前官方方式安装并验证。
   macOS / Linux 使用仓库脚本；Windows 优先评估现有 WSL2，不假装已验证 Windows 原生或 MLX 跨平台支持。

2. 在项目根目录准备私有环境文件：不存在 .env 时才从 .env.example 复制，设置仅当前用户可读写的权限；已有 .env 时只补缺项，保留真实值。
   在运行任何编辑前确认 .env 和私有 config/config.jsonc 被 Git 忽略，.env.example 保持空凭据模板。
   真实 Key、密码、Webhook、数据库 URL、结果访问令牌不得进入源代码、公开模板、命令行参数、聊天、日志、截图或 Git。不要执行来源不明的 .env 内容。
   在本机安全读取已有配置，仅告诉我哪些项已配置、哪些缺失，不输出值。

3. 默认使用 PostgreSQL，与项目日常数据库方案保持一致；若我明确选择不安装数据库的轻量体验，再使用 SQLite 并说明差别。
   先识别已有 PostgreSQL 服务和已有 LearnFlux 连接；已可用时直接复用，不能换成空库或 SQLite 导致历史看似丢失。
   没有 PostgreSQL 时，按系统安装并启动本机服务，创建 LearnFlux 专用非超级用户与归其所有的独占空库。账号、密码、主机、端口和库名按我的机器配置，不能套用维护者的真实账号或固定密码。
   权限不够时引导我完成必要的管理操作；不要重复创建同名对象、改动其他项目或自动购买云数据库。
   在本机 .env 中设置 LEARNFLUX_PERSISTENCE_BACKEND=postgres 和 DATABASE_URL。正确编码密码中的 URL 特殊字符；远程数据库按部署要求使用 TLS。
   新安装不要执行 SQLite 数据迁移。若发现已有 SQLite 数据并需要切换，先说明备份与迁移计划，获得同意后按迁移指南执行，不删除旧数据。

4. 运行 bash scripts/bootstrap.sh 安装项目依赖并初始化私有主配置。它准备 uv / Python 3.11，默认不装 FFmpeg、ASR 或 OCR，也不替代 PostgreSQL 安装。
   初始化只应在 config/config.jsonc 不存在时创建，自动生成独立随机管理口令；已有主配置、.env、数据库和用户资料保持原样。
   服务默认只监听本机 127.0.0.1:8000，端口按本机实际配置；不为首次体验开放公网。

5. 引导我在自己的编辑器中填写 .env 的 LEARNFLUX_LLM_API_KEY、LEARNFLUX_LLM_BASE_URL、LEARNFLUX_LLM_MODEL。
   三项必须来自同一可用模型服务，MODEL 会用于校对、总结和问答等任务；按需再设置单独任务模型。
   不要求我把 Key 发到聊天，也不把其他项目的 OPENAI_API_KEY 当成自动生效的配置。
   非空环境变量优先于系统设置与私有主配置，保存网页设置不能覆盖它们；已有设置页配置的用户可以保留原方式。
   不需要的 TikHub、云端 ASR、S3、飞书、Obsidian、隧道等留空或关闭。模型调用可能收费，在执行真实学习前说明并等待我同意；不自动注册、充值或启用付费云端 ASR。

6. 在项目根目录用 bash server.sh start 后台启动，用 status / log 检查状态与错误；实际访问地址以配置和日志为准，默认 http://127.0.0.1:8000。
   macOS 会注册用户级 LaunchAgent，退出终端后继续运行，并在用户登录时启动；bash server.sh stop 会卸载启动项。
   bash server.sh restart 用于配置或代码更新后重启；Ctrl+C 只退出日志查看或停止前台运行。
   端口被占用时先判断是不是已有 LearnFlux，不擅自结束陌生进程，不重复启动第二个实例。

7. 验证 PostgreSQL 表结构已经真正建立。首次启动会自动应用 persistence/migrations/postgres/ 下的版本化迁移，无需手工逐份运行 SQL。
   /health 的 checks.sqlite.backend 应为 postgres，且 healthy 为 true；键名 sqlite 为兼容命名，不能仅据网页打开就判定建表成功。
   在本机私密进程中只读核对 learnflux_schema_migrations 的版本、文件名、checksum 与仓库迁移一致，必要业务表存在。
   不把维护者的数据库结构截图当验收，不对已有库强制要求精确表总数，不在我的实际库运行会写删记录的集成测试。
   遇到连接、权限或迁移校验和错误，查明并修复后再验收；不通过清库重建掩盖错误。

8. 配置与费用确认后，打开工作台和系统设置，检查模型值已生效且密钥脱敏。
   使用 examples/first-learning.md 中的公开示例或一段无隐私短文字，完成一次“单篇深度学习 → 粘贴文字 → 开始学习”。
   等待任务成功，打开结果核对原文和 AI 解读完整，再实际导出一份可打开的 Markdown 或页面支持的格式。
   刷新后重新打开记录，确认任务和结果持久保存；新建且可安全停止的实例可重启验证，已有工作中的实例不要未经同意中断。
   任务失败时根据实际错误修复配置并重试，不把任务已提交、页面可打开或模拟响应说成 AI 学习成功。

9. 再用简单选项了解我是否需要音视频、扫描 PDF、手机收集或飞书归档。
   需要时阅读 docs/prompts/optional-services.md，只添加我选择的能力并做相应实测。Apple Silicon Mac 可按需使用 --with-local-whisper；其他系统不套用 MLX。
   飞书机器人“通知”与“把内容归档到飞书知识库”是不同功能，分别配置与验收；不要默认向任何机器人或知识库发送内容。

10. 最后给我可点击的本机入口、日常启停方式，以及“数据库与表结构、页面、真实 AI 学习、导出、可选能力”的实际验证结果。
    如果仍缺密钥、人工授权或兼容条件，逐项说明缺什么和下一步；能继续做的工作继续完成，不声称已经全部跑通。
    交付前确认这次未把任何真实环境文件、数据库、Cookie、私钥或凭据加入 Git。
```

按需扩展见[服务配置提示词](optional-services.md)，数据库步骤详见 [PostgreSQL 指南](../guides/postgresql.md)。Agent 是否能自动操作，取决于所用工具和本机权限；需要你亲自输入凭据时，它应引导你完成，不让你公开密钥。

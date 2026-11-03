# 按需配置服务：给 Agent 的提示词

不必把下列服务全部安装。先跑通一次学习，再按来源和阅读习惯添加。

这些是可选集成任务。先完成[第一次文字学习](../guides/quickstart.md)，再让 Agent 根据当前代码和你的已有服务配置；涉及账号授权、费用和外部发送时，由你决定范围。

| 组件 | 什么时候需要 | 是否必须 |
| --- | --- | --- |
| LLM API | AI 校对、解读、问答；密钥在本机填写 | 使用 AI 时需要，可能产生服务商费用 |
| 本机 Whisper / ASR | 无可用字幕的音视频转录 | 纯文字学习不需要；MLX 仅 Apple Silicon |
| TikHub | 抖音、小红书等相应来源 | 按需，有独立 Key 和服务商计费 |
| 飞书 CLI | 读取飞书文档 / 自动保存到知识库 | 可选，须用户登录与文档权限 |
| Cloudflare Tunnel | 手机在外网向本地提交链接 | 可选，须域名 / 隧道配置 |
| Obsidian | 保存到本机 Vault | 可选，不附带手机云同步 |
| FunASR / CapsWriter | 说话人识别 / 独立转录服务 | 按需，先核对当前调用路径与平台兼容性 |
| PostgreSQL / S3 | 自选数据库与对象存储后端 | 可选，新安装不要求 |

<details>
<summary><strong>我要自动保存到飞书知识库：复制此提示词</strong></summary>

```text
请为已运行的 LearnFlux 配置“完成后自动保存到飞书知识库”。先读 AGENTS.md、docs/guides/feishu-archive.md、docs/guides/feishu-documents.md 和 config/feishu_archive.example.json。

复用本机已有飞书 CLI；没有时查阅其当前官方安装与授权说明，只安装所需 CLI，不安装云端 Agent。登录和授权由我本人完成，禁止提取或输出令牌。

向我确认目标知识库链接和本地任务所属身份，确认有写权限。使用独立 API 用户且 user_id 与网页资料库一致；归档配置放私人目录，since 设为本次启用时间，不默认上传全部历史任务。设置 LEARNFLUX_FEISHU_ARCHIVE_CONFIG 指向同一配置，保留所有已有密钥与资料。

运行独立 scripts/feishu_archive_worker.py，并在我的系统支持时配置用户级自启动；保持本地业务数据库与归档状态库分离。用我同意的一条无隐私结果验证：只创建一篇文档、正文与解读完整、回读通过；再验证结果页显示与打开入口；页面状态和外部实际写入分别检查。重复运行不新增文档；人工修改不得被强制覆盖。

最后给我飞书手机查看方式、后台运行状态和停用方法。只配置这一集成，不开放知识库分享，不部署公网站点。
```

</details>

<details>
<summary><strong>我要用 iPhone 快捷指令收集：复制此提示词</strong></summary>

```text
请为已运行的 LearnFlux 配置“iPhone 快捷指令 → 本地后台解析”。先读 AGENTS.md 和 docs/guides/mobile-shortcut.md。

复用已有域名和 Cloudflare Tunnel；缺少域名或登录授权时由我提供并确认，不自动购买。安装缺少的 cloudflared，只为我指定的子域名建立 HTTPS 收集入口，精确放行 /api/transcribe，其余路径返回 404，不直接公开设置或文件接口。

生成手机专用随机 Bearer Token，保留本地资料身份，使 user_id 与网页所有者一致。凭据仅在私人配置和我自己的快捷指令内使用，不在聊天、日志、截图或公开文件里展示。个人机器同时配置手机用户时，按指南保持本机管理会话自动恢复。

在可操作的快捷指令 App 内完成配置：获取剪贴板 → 提取 URL → 取第一项 → POST 到 https://<我的子域名>/api/transcribe；JSON 的 url 使用第一项变量，transcription_strategy 设为 local。通知只表示快捷指令已执行，不误报解析成功。

配置本地服务和隧道的用户级自启动。先验证无凭据拒绝、有效请求受理、其他公网路径拒绝、本地结果可读，再请我用手机移动网络实测。不要调用付费云端 ASR。说明锁屏与休眠的区别、电脑离线时如何重试，以及如何停用入口。
```

</details>

<details>
<summary><strong>我要配置其他转录服务：复制此提示词</strong></summary>

```text
请根据我的系统和音视频需求，核对 LearnFlux 当前转录路径，帮我配置最少的必要服务。先阅读 AGENTS.md、scripts/bootstrap.sh、config/config.example.jsonc 和 transcriber/providers 的实际实现。

Apple Silicon 优先复用本机 mlx-whisper；其他系统先确认显式 local 策略的兼容性，不能只填 CapsWriter 地址就声称可用。需要 CapsWriter 或 FunASR 时，查阅对应服务当前官方部署说明，核对硬件、下载量、依赖与 WebSocket 地址；FunASR 仅在我需要说话人识别时安装。

保留已有环境与服务，不自动启用云端 ASR，不开公网端口。若当前代码不支持我的平台或所选策略，先说明缺口和最小解决方案，不擅自改业务代码。配置后用我允许的短音频验证真实转录和可读结果，分别报告服务连通性与实际识别效果。
```

</details>

LLM / TikHub 通常是填写已有服务凭据，按[配置与 API Key 指南](../guides/configuration.md)操作；本地转录不产生云端 ASR 费用，**不代表 LLM、TikHub 等第三方调用免费**。云端 ASR 默认关闭，启用后仍先估算、确认再提交。


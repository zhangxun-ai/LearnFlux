# 按需配置服务：给 Agent 的提示词

先按 README 的主提示词跑通你选择平台的真实链接：模型服务、对应平台解析与所选 ASR 属于这条路径的必要依赖；其余能力再按需添加，不需要全部安装。

这些是可选集成任务。先完成[真实链接首次验收](../guides/quickstart.md)，再让 Agent 根据当前代码和你的已有服务配置；涉及账号授权、费用和外部发送时，由你决定范围。

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

## iPhone 快捷指令与 Tunnel

```text
请帮我把 iPhone 快捷指令接到本机 LearnFlux，让手机关闭 Wi-Fi 后也能提交链接。先读 AGENTS.md、docs/guides/mobile-shortcut.md 和 config/users.example.json。已存在的配置、域名和启动项优先复用。

1. 核对 LearnFlux 本机监听地址、网页资料的 user_id、可用平台和本地 ASR。在 config/users.json 的 users 对象内添加独立随机令牌，保留原用户，用同一 user_id 让手机任务出现在原历史中。令牌只在本机私有配置和我的快捷指令里使用，权限设为仅本人可读。由我在自己的设备填入真实令牌，不把令牌打印或发到对话。个人 Mac 按指南保留本机免口令访问，重启前检查运行中的任务。
2. 检查 cloudflared、Cloudflare 账号、已有 Tunnel 和我控制的子域名。缺少账号授权时引导我在官方页面登录，缺少域名时说明要准备什么。由我明确指定并授权公网入口后，按官方指南创建或复用固定域名的 Tunnel，配置精确路径 ^/api/transcribe$ → 本机端口和兜底 http_status:404。先用 ingress validate 与 ingress rule 校验，再建立 DNS 路由并启动。凭据和私有配置放在用户目录，保留其他站点和全局 VPN 配置。
3. 先检查无令牌的 POST 被拒绝，公网 /、/briefings、设置和文件路径返回 404。再用我同意的短链接确认带令牌的请求受理、本机任务归到同一个账号、结果可读。验证公网接入可用已完成的缓存，另用真实未缓存口播才能验证新视频 ASR。云端 ASR 要在工作台对实际任务确认报价，TikHub 与模型调用也要符合我的费用范围。
4. 引导我导入 docs/LearnFlux-Link-Collector.shortcut。在「获取 URL 内容」把 learnflux.example.com 换成我的 HTTPS 子域名，保留 /api/transcribe，将 Authorization 中的 YOUR_MOBILE_TOKEN 换成我自己的令牌，保留 Bearer 后的空格。JSON 的 url 保留第三步「来自列表的项目」变量。先关闭 Wi-Fi，用手机移动网络手动运行，再去本机历史核对同一条链接与结果。手机没实测时把这一步标为待验。最后可绑定「轻点背面 → 轻点三下」。
5. 前台跑通后复用或配置 macOS 用户级 LaunchAgent，验证登录后启动和进程退出后的恢复，说明电脑休眠或离线时的行为。给我停用隧道与令牌的具体步骤。飞书归档只在我选用时另行配置和实测。
```

<details>
<summary><strong>我要配置其他转录服务：复制此提示词</strong></summary>

```text
请根据我的系统、真实链接平台和本地/云端偏好，配置LearnFlux实际可用的转录链路。先读AGENTS.md、README主提示词、scripts/bootstrap.sh、config/config.example.jsonc、docs/guides/configuration.md和当前provider选择实现。

先确认我有权处理的未缓存口播短视频、所选平台及本次费用范围。保留已有环境，准备FFmpeg；抖音/小红书按需配置TikHub，校对解读配置DeepSeek或已有兼容服务，两者不是ASR Key。

本地：普通链接明确local策略时当前固定走MLX Whisper，Apple Silicon Mac用 --with-local-whisper 安装独立环境与模型并按输出配置。Intel Mac/Linux/Windows不能套用，填CapsWriter地址不会改变这条策略。CapsWriter兼容路径或FunASR说话人识别须按实际入口独立确认，不能声称普通链接因此可用。

云端：我选择并接受费用后，配置本机.env的 DASHSCOPE_API_KEY / DASHSCOPE_WORKSPACE_ID / DASHSCOPE_API_HOST，核对同一Workspace北京节点并启用私有主配置cloud_asr.enabled。选择cloud，按页面任务报价由我确认费用上限后再提交；不自动充值，不重发提交状态未知的任务。

如果我的系统不支持所要求的本机路径，明确说明并推荐可用方案，不擅自改业务代码或切收费服务。凭据只留本机，不发到对话或Git。

用项目实际处理选定真实视频，核对provider确实运行、转录非空且与口播相符，再核对AI解读与导出。字幕、图文、缓存命中都不能证明ASR成功；只验证一种模式就只报告该模式。没有Key、授权或兼容条件时保留未完成状态，给出补齐步骤。

```

</details>

LLM / TikHub 通常是填写已有服务凭据，按[配置与 API Key 指南](../guides/configuration.md)操作；本地转录不产生云端 ASR 费用，**不代表 LLM、TikHub 等第三方调用免费**。云端 ASR 默认关闭，启用后仍先估算、确认再提交。

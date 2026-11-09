# 手机快捷指令提交到本地工作台

手机通过 HTTPS 调用现有 `POST /api/transcribe`，本地服务接收后进入后台队列；无需飞书或云端 Agent 扫描消息。公网入口不会增加可解析的平台范围。

## 先准备电脑和网络入口

你需要一台已跑通目标平台真实链接的电脑、一部 iPhone，以及一个你控制、可在 Cloudflare 配置 DNS 的域名。手机使用 HTTPS 子域名提交，电脑继续用本机地址查看任务。可先复制[完整 Agent 提示词](../prompts/optional-services.md#iphone-快捷指令与-tunnel)完成以下配置。

1. 运行 `bash server.sh status` 确认本机监听地址，例如 `http://127.0.0.1:8000`。用网页打开原历史，确认要沿用哪个 `user_id`；单管理口令模式是 `legacy_user`。
2. 在本机 `config/users.json` 的 `users` 对象下增加一条以独立随机令牌为键的记录，值包含 `user_id`、`name` 和 `enabled: true`。沿用网页的 `user_id`，保留原记录。文件设为仅本人可读（`chmod 600 config/users.json`），然后检查正在运行的任务并安排重启。独立令牌用于鉴权，公网可访问路径由 Tunnel 控制。令牌只填在本机私有配置和自己的快捷指令中。
3. 安装或复用 `cloudflared`。首次接入可让 Agent 按官方指南操作 `cloudflared tunnel login`、`cloudflared tunnel create <隧道名>`，由你在浏览器授权域名。已有专用隧道可复用。配置示例如下。[Cloudflare 创建本地管理的隧道](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/)

将以下 YAML 存到本机私有文件，例如 `~/.config/learnflux-mobile/tunnel.yml`。把 UUID、凭据绝对路径、域名和端口换成自己的值。

```yaml
tunnel: YOUR_TUNNEL_UUID
credentials-file: /absolute/path/to/YOUR_TUNNEL_UUID.json
ingress:
  - hostname: learnflux.example.com
    path: ^/api/transcribe$
    service: http://127.0.0.1:8000
  - service: http_status:404
```

先验证规则。第一条 URL 应匹配本机服务，第二条应匹配末尾 404。公网开放前用同样方式检查 `/`、`/briefings` 和 `/api/transcribe/`。

```bash
cloudflared tunnel --config ~/.config/learnflux-mobile/tunnel.yml ingress validate
cloudflared tunnel --config ~/.config/learnflux-mobile/tunnel.yml ingress rule https://learnflux.example.com/api/transcribe
cloudflared tunnel --config ~/.config/learnflux-mobile/tunnel.yml ingress rule https://learnflux.example.com/settings
```

由你确认子域名后，使用 `cloudflared tunnel route dns <隧道名> <你的子域名>` 建立 DNS 记录，再用 `cloudflared tunnel --config ~/.config/learnflux-mobile/tunnel.yml run <隧道名>` 前台试跑。确认路径限制与手机收集通过后，再配置下文的后台启动。[Cloudflare 入口规则说明](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/)

## 本机免口令

个人 Mac 同时配置手机 API 令牌时，在 `api` 配置中开启 `browser_local_auto_login` 和 `browser_local_management_access`。本机直连 `localhost` / `127.0.0.1` / `::1` 的同源浏览器会自动建立管理会话，过期或服务重启后自动恢复，沿用管理身份及原历史资料。手机令牌仍独立鉴权。远程 Host、代理转发及跨站请求不会触发免登录；共享机器上的其他本地使用者也可访问管理功能，因此多用户部署默认不开启该选项。关闭 `browser_local_management_access` 并重启可恢复原多用户登录要求。

## 导入快捷指令模板

1. 在 iPhone 上[下载 LearnFlux-Link-Collector.shortcut](../LearnFlux-Link-Collector.shortcut)。在 GitHub 文件页可点 **Download raw file** 保存到“文件”，再点开并选择 **添加快捷指令**。也可以在 Mac 的“快捷指令”App 通过 **文件 → 导入** 添加，再用自己的 iCloud 同步到 iPhone。
2. 在“快捷指令”App 打开这条指令的编辑器，展开第 4 个动作 **获取 URL 内容**。只替换下面两处。

   | 要改哪里 | 模板值 | 填什么 |
   | --- | --- | --- |
   | 请求 URL | `https://learnflux.example.com/api/transcribe` | 把 `learnflux.example.com` 换成自己的 Tunnel 子域名，保留 `https://` 和 `/api/transcribe`。 |
   | 头部 → `Authorization` | `Bearer YOUR_MOBILE_TOKEN` | 把 `YOUR_MOBILE_TOKEN` 换成刚配置的手机令牌，保留 `Bearer` 后的一个空格。 |

3. 复制一条已获授权、且电脑已能处理的链接。关掉 iPhone 的 Wi-Fi，用移动网络手动运行一次。首次出现网络访问提示时核对域名。在电脑打开 LearnFlux 的历史，确认同一条链接已受理，等待结果可读。

模板从空白创建，示例域名和令牌均为占位符。填好真实令牌后，个人副本请自行保管。若系统未能导入文件，可按下面五步手动重建。[Apple 快捷指令文件说明](https://support.apple.com/zh-cn/guide/shortcuts/apdf01f8c054/ios)

### 手动搭建五个动作

1. **获取剪贴板**。
2. **从输入中获取 URL**，输入选第 1 步的「剪贴板」。
3. **从列表中获取项目**，列表选第 2 步的「URL」，项目选「第一项」。
4. **获取 URL 内容**，URL 写自己的 `https://<子域名>/api/transcribe`。展开动作，方法选 `POST`，头部分别添加 `Authorization`（`Bearer <手机令牌>`）、`Content-Type`（`application/json`）和 `User-Agent`（`LearnFlux-Mobile/1.0`）。请求体选 **JSON**，添加一个文本字段 `url`，值点选第 3 步的「来自列表的项目」变量。
5. **显示通知**，文本填写「快捷指令已执行」。若默认引用上一步的「URL 的内容」，将它替换为固定文本。

模板只发送 `url`，当前接口默认使用 `local` 转录策略。需要转录时先在电脑验证 Apple Silicon Mac 的 MLX Whisper 可用。选择 `cloud` 时才添加相应的 `transcription_strategy` 字段，实际任务报价仍需在工作台确认。TikHub 和 AI 解读可能有独立费用。响应中的 JSON `code=202` 表示后台受理，处理结果以工作台历史为准。

修改已有快捷指令可直接保留它的名称和标识，避免重新绑定手势。[Apple 请求 API 操作说明](https://support.apple.com/zh-cn/guide/shortcuts/apd58d46713f/ios)

### 绑定“背部轻点三下”

先在 iPhone 的“快捷指令”App 中手动运行一次，确认剪贴板链接能够提交，再绑定手势：

1. 打开 iPhone **设置 → 辅助功能（部分系统显示“无障碍”）→ 触控 → 轻点背面**。
2. 选择 **轻点三下**，在快捷指令列表中选中刚配置的收集指令。
3. 复制一条已获授权的链接，轻点手机背部三下，再到工作台确认任务与结果。手势未触发时先检查快捷指令是否已同步、是否选对名称。

设置路径参考 [Apple 官方说明](https://support.apple.com/zh-cn/111772)。若机型不支持该手势，可直接在“快捷指令”App 运行同一指令。

### 接上飞书阅读

手机提交不会自动启用飞书归档。按[飞书归档指南](feishu-archive.md)登录命令行工具、设置目标知识库与相同任务身份，并运行独立归档服务。用一条同意归档的真实结果，核对飞书内的解读与完整正文，最后在手机飞书打开该文档。只有提交、后台处理、归档与手机阅读都完成，才算 README 中的整条闭环跑通。

## 后台运行与验证

- macOS 使用 LaunchAgent 管理服务；`RunAtLoad` 表示登录后启动，`KeepAlive` 用于进程退出后重启。复用已有启动项，避免重复监听同一端口。
- VPN 虚拟网卡可能影响隧道出站连接。遇到 QUIC 超时或 HTTP/2 TLS EOF 时，先排查网络。本机实测通过 HTTP/2 并绑定物理接口的 IPv4 地址可连接。采用这种配置时，启动脚本应在运行中检查出站地址，发现地址变化时退出旧连接，由 LaunchAgent 用当前地址重新启动。否则旧地址失效后，进程可能一直重试，无法触发 LaunchAgent 重启。保留 TLS 校验和全局 VPN 规则。
- Apple Silicon Mac 可用 [隧道启动脚本](../../scripts/start_mobile_tunnel.sh)。脚本读取本机的 `~/.config/learnflux-mobile/tunnel.yml`，使用 Homebrew 安装的 `/opt/homebrew/bin/cloudflared`。用它更新已有 LaunchAgent 调用的启动脚本，保留原来的私有隧道配置与 `KeepAlive`。
- 登录后自动启动不等于关机、合盖或休眠后仍在线。没有云端收件箱时，离线提交会失败，需要重新提交。
- 依次验证：本地令牌鉴权、公网无凭据拒绝、公网有效请求受理、本地任务进入终态和结果可读、公网非收集路径返回 404。
- 验证可以使用已有完整缓存的视频，避免额外下载或模型费用；需明确这验证的是公网提交及缓存处理链路，并非新视频转录质量。
- 最后用手机移动网络测试快捷指令。电脑访问公网域名成功不能代替手机实测。

公网仅开放收集接口时，域名首页返回 404 是预期行为，结果在本地工作台查看。

## 停用与恢复

暂停隧道的 LaunchAgent 即可停止公网入口，保留本地工作台。停用手机令牌时，将对应用户配置的 `enabled` 设为 `false` 并重启服务。不要删除资料库、已有任务或其他用户配置。

具体机器上的隧道凭据、启动项路径和验证记录保存在本机运维配置中，不进入仓库。

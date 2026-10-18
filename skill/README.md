# LearnFlux skill

把 [LearnFlux](../README.md) 的「视频、播客 URL 转录与总结」封装为一个 **Agent Skills 标准 Skill**。它只复用现有 HTTP API 和无依赖 Python CLI，不包含 MCP，不复制 LearnFlux 的业务逻辑。

这份 README 面向**部署 skill 的人**。skill 本身的使用逻辑在 [`SKILL.md`](./SKILL.md) 里，由 agent 自己读。

---

## 目录结构

```
skill/
├── SKILL.md                     # skill 元数据 + 行为指引（给 agent 读）
├── scripts/
│   └── videotranscript.py       # stdlib-only Python CLI，无外部依赖
├── references/
│   └── api.md                   # 完整 API 端点参考（按需加载）
├── evals/
│   └── evals.json               # 7 条核心行为回归 prompt
└── README.md                    # 本文件
```

## 先决条件

- **Python 3.10+**（脚本只用 stdlib，不需要 pip install 任何东西）
- **一个可访问的 LearnFlux 实例**（本仓库根目录的服务，跑起来后监听 `:8000`，或走你的自部署地址）
- **Bearer Token**：优先使用多用户模式下 `config/users.json` 里的独立 key；可信的单用户环境也兼容 `config/config.jsonc` 的 `api.auth_token`

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `VIDEO_TRANSCRIPT_API_BASE_URL` | ✅ | **API 请求地址**。内网/tailnet/局域网优先，延迟低。如 `http://localhost:8000` / `http://100.68.21.80:8200` |
| `VIDEO_TRANSCRIPT_API_TOKEN` | ✅ | Bearer token。优先使用 `users.json` 的独立 key；不要提交到 Git 或粘贴进 Agent 对话 |
| `VIDEO_TRANSCRIPT_API_PUBLIC_URL` | — | **给用户点的公网地址**（可选）。不设时用 BASE_URL。如 `https://vt.example.com` |
| `VIDEO_TRANSCRIPT_API_WECHAT_WEBHOOK` | — | **企业微信 webhook 默认值**（可选）。设置后 submit 自动带上，`--webhook` 传参时覆盖。如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx` |
| `VIDEO_TRANSCRIPT_API_FEISHU_WEBHOOK` | — | **飞书 webhook 默认值**（可选）。设置后 submit 自动带上，`--feishu-webhook` 传参时覆盖。如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxx` |

**为什么分两个地址**：API 请求追求低延迟，通常走内网；但返给用户的 `/view/<token>` 链接需要能从公网打开。配了 PUBLIC_URL 后，`submit` / `status` / `history` 打印给用户的链接会自动用公网域名拼。

脚本不会打印 Token。它按以下顺序补全尚未设置的变量：显式环境变量 → `LEARNFLUX_AGENT_CONFIG` 指向的文件 → `~/.learnflux/agent.env` → Hermes/Claude Code 的已有配置。必填变量缺失时返回 exit 3。

### 推荐的跨平台配置

在用户目录创建 `.learnflux/agent.env`：

- macOS：`/Users/<用户名>/.learnflux/agent.env`
- Linux：`/home/<用户名>/.learnflux/agent.env`
- Windows：`C:\Users\<用户名>\.learnflux\agent.env`

```dotenv
VIDEO_TRANSCRIPT_API_BASE_URL=http://127.0.0.1:8000
VIDEO_TRANSCRIPT_API_TOKEN=<只在本机填写，不要发给 Agent>
VIDEO_TRANSCRIPT_API_PUBLIC_URL=
```

macOS/Linux 再执行 `chmod 600 ~/.learnflux/agent.env`。Windows 将文件保留在自己的用户目录，不要放入同步盘或公开项目。

配置后先运行只读自检：

```bash
# macOS / Linux
python3 skill/scripts/videotranscript.py doctor

# Windows PowerShell
python skill/scripts/videotranscript.py doctor
```

看到 `READY` 代表地址、服务和鉴权均可用。`doctor` 不提交转录任务，也不会产生转录费用。

## 各平台部署

### Codex

把 `skill/` 中的内容安装到 `$HOME/.agents/skills/learnflux/`，然后使用上面的 `~/.learnflux/agent.env` 配置。安装完成后运行 `doctor`；若 Skill 没有立即出现，再重启 Codex。不要在安装提示词里填写真实 Token。

### Claude Code

1. 把整个 `skill/` 目录放到你的 skill 索引路径下（常见路径：`~/.claude/skills/learnflux/`），或者直接保留在本仓库里用本地路径引用。
2. 推荐使用上面的 `~/.learnflux/agent.env`。已有用户继续使用 `~/.claude/settings.json` 的 `env` 字段也兼容，无需迁移。

**首次安装 prompt（不包含密钥）**：

```
帮我安装 LearnFlux skill。

1. 把 https://github.com/zhangxun-ai/LearnFlux.git 仓库里的 skill/ 目录复制到 ~/.claude/skills/learnflux/
2. 不要向我索要、读取或回显任何 API Token，也不要修改我已有的环境变量。
3. 安装后运行 videotranscript.py --help，告诉我应当手动创建的 ~/.learnflux/agent.env 路径和 doctor 验证命令。

注意：Windows 上 python3 命令是微软商店占位程序，会直接失败。请用 python 代替。
```

**更新 prompt**（skill 已安装，只需拉最新代码）：

```
更新 LearnFlux skill：从 https://github.com/zhangxun-ai/LearnFlux.git 拉取最新的 skill/ 目录，覆盖到 ~/.claude/skills/learnflux/。环境变量不用动。更新后跑 doctor 验证。
```

### Hermes

1. 把 `skill/` 同步到 Hermes skill 目录（`~/.hermes/skills/learnflux/`）。
2. 使用上面的通用私有配置文件；已有用户也可继续把变量写入 `~/.hermes/.env`。

**首次安装 prompt（不包含密钥）**：

```
帮我安装 LearnFlux skill。

1. 把 https://github.com/zhangxun-ai/LearnFlux.git 仓库里的 skill/ 目录复制到 ~/.hermes/skills/learnflux/
2. 不要向我索要、读取或回显任何 API Token，也不要修改我已有的环境变量。
3. 安装后运行 videotranscript.py --help，告诉我应当手动创建的 ~/.learnflux/agent.env 路径和 doctor 验证命令。
```

**更新 prompt**（skill 已安装，只需拉最新代码）：

```
更新 LearnFlux skill：从 https://github.com/zhangxun-ai/LearnFlux.git 拉取最新的 skill/ 目录，覆盖到 Hermes 的 skill 目录下的 learnflux/。环境变量不用动。更新后跑 doctor 验证。
```

### OpenClaw

1. 默认个人范围可把 `skill/` 内容放到 `~/.agents/skills/learnflux/`；也可在仓库根目录运行 `openclaw skills install ./skill --as learnflux` 安装到当前 workspace。
2. 使用上面的通用私有配置文件。不要把 Token 写入 `SKILL.md` 或提交到 Git。

## 安全烟测

配好环境变量后：

```bash
# 只读检查，不提交任务、不显示 token
python3 skill/scripts/videotranscript.py doctor
```

不要为了烟测提交仓库里的固定示例 URL：缓存状态无法保证，可能触发真实下载、ASR 或 LLM 成本。只有用户提供并明确要求处理 URL 时才运行 `submit`。

退出码语义：

| Exit | 含义 |
|------|------|
| 0 | 成功 |
| 1 | 业务失败（任务 failed、view_token 无效、结果为空） |
| 2 | 传输/基础设施（网络、5xx、401/403 鉴权失败） |
| 3 | 配置（缺 env、参数非法） |

## CLI 子命令速查

| 子命令 | 作用 |
|--------|------|
| `doctor` | 只读检查配置、服务和鉴权，不显示 token |
| `submit <url>` | 提交转录任务，返回查看链接（agent 内部记录 task_id 用于后续查询） |
| `status <task_id>` | 查任务状态（agent 内部使用），success 时自动附带 view_token |
| `result <view_token>` | 拉结果文本（`--type summary`/`calibrated`/`transcript`） |
| `history` | 按平台/作者/关键词/日期/状态查历史任务 |
| `filter-options` | 列出可选的平台/作者/webhook |
| `profile` | 当前用户信息 |
| `health` | 服务健康探活 |

加 `--format json` 任意命令都能给出结构化 JSON；默认 markdown 适合直接喂给 LLM。

## 更新与测试

修改 `scripts/videotranscript.py` 或 `SKILL.md` 后，用 `evals/evals.json` 里的 7 条 prompt 回归：

```bash
# 跟真实服务端对打的烟测
export VIDEO_TRANSCRIPT_API_BASE_URL=...
export VIDEO_TRANSCRIPT_API_TOKEN=...
python3 skill/scripts/videotranscript.py doctor
```

完整 agent 行为测试（带/不带 skill 对比）见 skill-creator 框架：跑完会在 `skill-workspace/iteration-N/` 输出每个 case 的 `response.md` 和 `benchmark.md`。

## 设计要点

- **stdlib-only**：脚本零依赖，`python3` 有就能跑
- **安全配置**：不在 Skill、命令行参数或对话中硬编码 Token；跨 Agent 共享用户私有配置文件
- **异步不阻塞**：`submit` 立返查看链接，不在 agent 会话里 poll 十几分钟
- **闭环优先**：`status` 自动反查 view_token，agent 内部用 task_id 闭环到 result，不用反问用户
- **用户友好**：用户只看到查看链接，task_id 等内部标识不暴露
- **清晰的退出码**：让调用方能程序化区分网络问题、业务失败、配置错误

更多设计背景见 [SKILL.md](./SKILL.md)；完整 API schema 见 [references/api.md](./references/api.md)。

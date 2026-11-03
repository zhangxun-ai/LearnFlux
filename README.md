<!-- project-cover:20261103:start -->
<p align="center">
  <img src="assets/project-cover-20261103.webp" alt="LearnFlux：视频太长、文章太多？快捷指令一键提交，AI 帮你梳理重点" width="1280" />
</p>
<!-- project-cover:20261103:end -->

# LearnFlux

**用 AI 提炼视频、文章和文档的要点，整理学习笔记。**

LearnFlux 是一个可以部署在自己电脑或服务器上的 AI 学习工具。导入资料后，可以阅读原文和 AI 总结、围绕内容提问、记录笔记，再导出或保存到 Obsidian、飞书。也可以用它管理课程、阅读电子书和写日记。

[快速开始](#快速开始) · [功能介绍](#功能介绍) · [使用指南](docs/guides/product-tour.md) · [配置服务](docs/guides/configuration.md) · [文档中心](docs/README.md)

**许可：** [MIT + Commons Clause](LICENSE)，包含商业使用限制；使用前请阅读完整条款。

以下为真实界面截图，案例来自公开资料、公版作品及原创演示内容。[截图说明](docs/images/readme-20261103-cases/README.md)

## 快速开始

第一次使用，建议先粘贴一段文字，生成一份 AI 总结。**这一步只需配置模型服务，不需要安装音视频转录或扫描件识别工具。**

准备 Git、Bash 和 curl，在 macOS / Linux 终端运行：

```bash
git clone https://github.com/zhangxun-ai/LearnFlux.git
cd LearnFlux
bash scripts/bootstrap.sh
uv run python main.py --start
```

脚本会安装 uv、Python 3.11 和应用所需的依赖，并创建本机配置与随机管理口令。已有配置和数据会保留。首次安装需要下载依赖，请等待脚本执行完成。

1. 打开 [系统设置](http://127.0.0.1:8000/settings)，填写已有模型服务的 API Key、接口地址和可用模型，保存。
2. 打开 [单篇深度学习](http://127.0.0.1:8000/add_task_by_web)，选择 **粘贴文字**，粘贴[示例文字](examples/first-learning.md)，点击 **开始学习**。
3. 在近期任务中等待处理完成，打开结果，阅读 AI 总结。需要保存时，点击 **导出**。

AI 调用由你配置的模型服务商计费。单纯阅读文档或写作不需要 API Key；处理音视频或扫描件时，再安装相应工具。在终端按 `Ctrl+C` 可停止服务。

遇到问题、需要后台运行，或使用 Windows / Docker：[完整首次使用指南](docs/guides/quickstart.md)。也可以复制[安装提示词](docs/prompts/macos-local-quick-start.md)交给能操作本机终端的 Agent。

## 功能介绍

### 单篇深度学习：提炼视频、文章和文档要点

粘贴链接、上传文件或输入文字。音视频转成逐字稿，文章和文档提取正文，再由 AI 总结要点。阅读时可以回看原文、标记重要内容，也可以导出笔记，或保存到已配置的 Obsidian、飞书。

<p align="center">
  <img src="docs/images/readme-20261103-cases/02-result.webp" alt="Karpathy 公开演讲阅读笔记：AI 编程、代码检查与原文核对" width="1040" />
</p>

<details>
<summary>查看导入页面</summary>

<p align="center">
  <img src="docs/images/readme-20261103-cases/01-import.webp" alt="单篇学习：链接、本地文件、文字三种导入方式，以及近期任务" width="1040" />
</p>

</details>

### 系列深度学习：按章节学习，生成课程总结

将一门课程或同一主题的资料放进一个系列，逐章查看原文和 AI 解读，再生成全系列总结。有可播放源文件的章节，可以直接进入 **边播边学**。

<p align="center">
  <img src="docs/images/readme-20261103-cases/03-collections.webp" alt="《竞争战略》读书笔记：咖啡店案例、四个章节与重点解读" width="1040" />
</p>

### 边播边学：对照文稿看视频，随手记笔记

视频和逐字稿同步显示，点击某段文字就能跳到对应的播放位置。遇到不懂的内容可以向 AI 提问，也可以边看边记笔记。播放需要保留可用的源文件。

<p align="center">
  <img src="docs/images/readme-20261103-cases/09-player.webp" alt="边播边学：咖啡店案例演示短片、文稿跳转与学习笔记" width="1040" />
</p>

### 心流阅读：沉浸式阅读 PDF、电子书和文档

支持 PDF、EPUB、DOCX、TXT 和 Markdown，导入后统一放在书架中。阅读器支持单页 / 双页、目录、字号和主题切换，并自动保存阅读进度。扫描版 PDF 需要另外安装 OCR（文字识别工具）。

<p align="center">
  <img src="docs/images/readme-20261103-cases/04-reading-library.webp" alt="心流书架：《背影》《朝花夕拾》等公版作品与阅读进度" width="1040" />
</p>

<details>
<summary>查看双页阅读界面</summary>

<p align="center">
  <img src="docs/images/readme-20261103-cases/05-reading.webp" alt="朱自清《背影》原文的双页阅读界面" width="1040" />
</p>

</details>

### 心流写作：在雨雪场景中专注写作

用来写日记、学习笔记或草稿。可以选择雨景或雪景，调整字体与背景音，使用专注计时。文字自动保存，支持导出 TXT 或 Markdown。

<p align="center">
  <img src="docs/images/readme-20261103-cases/06-writing.webp" alt="心流写作：下班游泳的演示日记、雨景、背景音与专注计时" width="1040" />
</p>

### 历史记录：搜索和回看学过的内容

按标题、作者或正文搜索，也可以按来源、时间和处理状态筛选，重新打开原文和 AI 总结。选中多份资料后，可以向 AI 提问、比较其中的观点，回答会附上引用出处。

<p align="center">
  <img src="docs/images/readme-20261103-cases/07-history.webp" alt="历史记录：公开演讲、读书笔记与公版散文的卡片和搜索列表" width="1040" />
</p>

### 日报：集中阅读 AI 资讯和微信日报

在同一个页面阅读 **AI 导游** 和 **微信日报**，按日期查看往期内容，下载或保存报告。使用前需按[日报指南](docs/guides/daily-briefings.md)配置数据来源和报告生成；打开页面本身不会生成日报。

<p align="center">
  <img src="docs/images/readme-20261103-cases/08-briefings.webp" alt="日报阅读：Karpathy 演讲与 Anthropic 文章的阅读摘要" width="1040" />
</p>

复盘模块支持按日、周、月、年记录和回顾。详细操作步骤见[使用指南](docs/guides/product-tour.md)。

## 支持哪些内容，需要哪些服务

| 想处理的内容 | 从哪里开始 | 需要什么 |
| --- | --- | --- |
| 一段自己的文字 | 单篇学习 → 粘贴文字 | AI 解读需要模型服务；不需要语音转录 |
| 普通文档、书籍 | 心流阅读 → 导入文档 | 本地解析；扫描件另装 OCR |
| 本地音视频 | 单篇 / 系列 / 边播边学 | FFmpeg 与合适的转录引擎 |
| YouTube、Bilibili、播客等 | 粘贴链接 | 可用字幕优先；无字幕时需要转录 |
| 抖音、小红书等社媒链接 | 粘贴链接 | 通常需要 TikHub；部分来源还受登录、限流或网络影响 |
| 飞书 Wiki / Docx | 粘贴链接 | 已登录的飞书命令行工具及文档读取权限 |
| 手机复制的链接 | iPhone 快捷指令 | 已配置快捷指令，运行服务的电脑保持在线 |
| 保存到 Obsidian / 飞书 | 结果页或独立归档 | 对应知识库路径、账号权限和可选集成配置 |

```bash
# 音视频依赖（再按配置指南选择转录引擎）
bash scripts/bootstrap.sh --with-media

# Apple Silicon Mac 本机 Whisper
bash scripts/bootstrap.sh --with-local-whisper

# 扫描 PDF 的 OCR
uv sync --extra ocr
```

音视频转录可选择本机 Whisper、CapsWriter 或 FunASR，安装后还需按[配置指南](docs/guides/configuration.md)启用。Whisper / OCR 首次使用可能需要下载模型。云端转录、TikHub 和 AI 模型分别由各服务商计费；部分平台还需要登录，并可能受访问频率或网络限制影响。

[配置与 Key](docs/guides/configuration.md) · [按需配置服务的 Agent 提示词](docs/prompts/optional-services.md) · [手机收集](docs/guides/mobile-shortcut.md) · [飞书归档](docs/guides/feishu-archive.md)

## 常见问题

| 遇到什么 | 先检查什么 |
| --- | --- |
| 页面打不开 | 终端是否仍在运行、实际端口、启动日志；避免重复启动两个实例。 |
| 有原文，没有 AI 解读 | Key、接口地址、模型名是否配套；查看具体任务错误。 |
| 音视频无法转录 | 已选择的转录引擎、模型是否下载、FFmpeg 与源文件是否可用。 |
| 扫描 PDF 等待 OCR | 安装 `ocr` extra 后重启，在书架重试。 |
| 手机显示已执行，电脑没有结果 | 电脑上的服务是否在运行、快捷指令中的地址和口令是否正确，再查看任务状态。 |

## 开发与更多文档

新安装默认使用 SQLite 与本地文件；PostgreSQL / S3 可选。模型、解析 API 和知识库集成只在启用对应能力时参与处理。不要把真实配置、媒体、密钥或结果访问令牌提交到仓库。

```bash
uv sync --extra dev
uv run --extra dev pytest tests/unit
uv run --extra dev pytest
```

[系统架构](docs/architecture.md) · [API Quick Start](docs/guides/api/quickstart.md) · [测试说明](tests/README.md) · [PostgreSQL 迁移](docs/guides/postgresql.md) · [文档中心](docs/README.md)

Docker 当前按 `linux/amd64` 准备，宿主机默认入口为 `127.0.0.1:8200`；本轮尚未验收镜像构建和容器运行，不作为首次体验的默认路径。[Docker 说明](docs/guides/quickstart.md#docker-替代路径)

[本地验证结果与未验证事项](docs/release-readiness.md)

## 项目来源与许可

LearnFlux 基于 [VideoTranscriptAPI](https://github.com/zlxlabs/VideoTranscriptAPI) 的早期版本持续演进而来。感谢原作者 [@zj1123581321](https://github.com/zj1123581321) 提供的视频解析、转录与 API 基础实现。仓库保留原项目的 Git 历史及版权和许可声明。

项目使用 **MIT License + Commons Clause**。允许个人学习、研究、修改及符合条款的分发；Commons Clause 不授予销售本软件，或以本软件主要功能提供收费服务的权利。完整范围以 [LICENSE](LICENSE) 为准。

开发过程使用 AI Coding Agent 辅助，产品方向、审查、发布与维护由维护者负责。欢迎通过 [Issues](https://github.com/zhangxun-ai/LearnFlux/issues) 反馈问题或提交 Pull Request；请去除密钥、真实结果令牌和私有内容。

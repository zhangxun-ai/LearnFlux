# 链接处理 & 本地上传 路线图

> 日期 2026-06-09。优先级（用户指定）：先做 **Phase 1 链接处理文章贴**，用户测试通过后再做 **Phase 2 本地上传**。

## 现状

| 输入 | 状态 |
|---|---|
| 视频链接（YouTube/B站/抖音/小宇宙）→ 转录 | ✅ 已通 |
| X(Twitter) 帖子链接（短推 + 长文 Article）→ 帖子洞察 + 可信度 | ✅ 已通 |
| 小红书图文链接 → 帖子洞察（正文 + 评论）| ✅ 已通（fetch_note_detail 多端点兜底 + web_v2 评论）|
| 微信公众号文章链接 → 帖子洞察（正文 + 留言）| ✅ 已通（wechat_mp detail_json + comment_list）|
| 本地视频/音频上传 → 转录 | ✅ 已通（复用 mlx-whisper + LLM 管线；先抽音频删原视频省空间）|
| 本地文档上传 → 解析 | ✅ 已通（txt/md/pdf/docx 提取文本 → LLM 总结，统一进 `process_local_upload`）|

> **Phase 2 全部完成**：统一的「本地文件」入口按类型分流——音视频走 mlx-whisper 转写（抽音频省空间），
> 文档(txt/md/pdf/docx)走 `pypdf`/`python-docx` 提取文本；两者都进 LLM 后处理 + `/view` 结果页，临时文件用后即删、零残留。
> 真实文件端到端验证通过。新增依赖 `pypdf` / `python-docx` 已写入 pyproject。

> **Phase 2a 本地视频/音频上传 完成**：复用现有 mlx-whisper 转写 + LLM 后处理 + 结果页。
> 新增 `POST /api/upload-transcribe`（multipart→存临时文件→`process_local_upload` 转写→入 LLM 队列）+ 前端拖拽上传。
> 真实音频端到端验证通过（上传→success→/view 出转写+总结）。视频链路未改、零回归。

> **Phase 1 链接处理"文章贴" 完成**：X / 小红书 / 公众号 三平台均为「正文 + 评论 + 可信度」完整版，
> 经真实链接端到端验证。每帖约 2 次 TikHub 调用（正文 + 评论），无冗余。下一步进入 Phase 2 本地上传。

## Phase 1：链接处理文章贴（优先）

### 架构小重构（1c，先做，让后续平台即插即用）
- `generate_post_insight` 改为**按平台选 fetcher**：定义统一产物
  `PostContent(title, author, content_text, comments: list[CommentItem], source_note)`。
- fetcher 注册表：`{'twitter': TwitterPostFetcher, 'xiaohongshu': XhsPostFetcher, 'weixin': WeixinPostFetcher}`。
- `TwitterPostFetcher` 适配到统一产物（现有字段已对齐，加一层薄适配即可）。
- 支持平台集合从 `{twitter}` 扩展为 `{twitter, xiaohongshu, weixin}`。

### 1a 小红书图文 → 帖子洞察
- 正文：复用现有 `XiaohongshuDownloader` 的 note info（title + desc/正文）。
- 评论：复用 `comments/fetcher.py` 已接的 `xiaohongshu/app_v2/get_note_comments`（hot 排序）。
- 路由：前端 `classifyContent` 把小红书归 `post`（图文洞察）；后端 post-insight 支持 xiaohongshu。
- 先探测真实 note info / 评论响应结构，锁定 desc/comments 字段。
- 注：小红书视频笔记的"转录"能力保留（如需，走视频流程）；本期"文章贴"统一走帖子洞察。

### 1b 微信公众号文章 → 帖子洞察
- 正文：HTTP 抓取 `mp.weixin.qq.com/s/...` 公开 HTML，提取标题/作者/正文（用 firecrawl 或 requests+解析）。
- 评论：**已知限制**——公众号留言走需登录态接口，公开不可得；输出明示"留言不可获取，仅基于正文"。
- 路由：`mp.weixin.qq.com` → post。

### 1d 帖子洞察结果入首页历史
- `/post` 分析成功后写入统一 `vta_task_history`（type=post, status=done），与现有历史/筛选/分页打通。
- 需对齐 `StorageManager` 的存储/加密格式。

## Phase 2：本地上传（用户测过 Phase 1 后）

### 2a 本地视频/音频 → 转录
- `POST /api/upload-transcribe`：multipart 接收文件 → 存临时目录 → 接入现有转录管线（复用 task/进度/结果）。
- 前端：本地文件 Tab 拖拽区接真实上传 + 进度。

### 2b 本地文档 → 解析
- 文档（pdf/docx/txt 等）→ 文本提取 → 分析提炼。

## 贯穿原则
- 每个新平台先用真实 API/HTTP 探测响应结构，再写代码（消除字段风险）。
- TDD（fixture 驱动）+ 真实端到端验证（真实 TikHub/HTTP/LLM）。
- 不碰已通的视频转录链路；新平台并联接入。
- 静态资源已加版本号自动失效缓存，前端改动用户正常刷新即可见。

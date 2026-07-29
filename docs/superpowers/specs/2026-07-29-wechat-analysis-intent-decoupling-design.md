# 公众号来源与分析意图解耦设计

## 目标

单篇深度学习入口接收 `mp.weixin.qq.com` 文章时，始终创建可追踪、可回看的深度学习任务；公众号只是内容来源，不再隐式选择帖子洞察。帖子洞察仍是显式入口，微信视频号 `weixin.qq.com/sph/...` 继续走视频下载与转录。

## 已验证的现状

浏览器链路由 `URLExtractor → classifyContent → submitTranscription` 驱动。`classifyContent()` 当前把公众号硬编码为 `post`，随后 `submitTranscription()` 跳转到 `/post?url=...`。帖子页面会自动调用 `/api/post-insight`，使用 `WeixinPostFetcher` 拉取正文与留言，再交给 `PostInsightAnalyzer` 生成社交运营输出；结果仅保存在浏览器 `localStorage`。

单篇深度学习的稳定链路是 `/api/transcribe → task_status/view_token → task_queue → process_transcription → llm_task_queue → cache/history → /view/<view_token>`。小红书图文已经通过“抓正文、保存文档源、进入 LLM 队列”复用该链路。

GitNexus 显示 `classifyContent` 有 5 个直接调用者和 23 个三层内受影响符号，属于中等风险前端共享点；小红书文章入队辅助函数只有 `process_transcription` 一个直接调用者，适合复用其边界。`generate_post_insight` 的影响面局限于帖子洞察服务与测试，不需要改写其分析语义。

## 方案比较

### 方案 A：仅删除前端跳转，在转录处理器中按域名特判

改动最小，但来源识别、用户意图和处理策略仍混在条件分支中。新增下一种文章来源时会重复同一问题，不采用。

### 方案 B：最小纵向切片（采用）

前端先输出纯 `source_type`，再由当前工作台确定 `analysis_intent=deep_learning`。API 请求和队列载荷显式携带两者；服务端校验公众号文章只能进入文章抓取路径，复用 `WeixinPostFetcher` 的正文适配能力后进入现有深度学习缓存和 LLM 队列。帖子洞察保留独立 API，但不再因 `?url=` 自动执行。

该方案建立了清晰边界，同时不引入数据库迁移、不重写下载器注册表，也不影响当前 TikHub V2 迁移。

### 方案 C：一次性建设完整 `ContentSourceAdapter` 注册表和统一分析任务仓库

长期最完整，但会同时触及所有平台、持久化 schema、计费和结果页，爆炸半径过大。作为后续演进方向，不纳入本轮。

## 架构与数据流

### 来源分类

浏览器新增纯来源分类：

- `mp.weixin.qq.com` → `wechat_mp_article`
- `weixin.qq.com/sph/...` → `wechat_channels_video`
- 已知视频平台 → `video`
- X/Twitter 状态页 → `social_post`
- 小红书 → `mixed_media`
- 其他 → `unknown`

`source_type` 只描述抓取适配器选择，不决定分析模块。

### 意图选择

单篇工作台固定提交 `analysis_intent=deep_learning`。公众号检测横幅说明将获取文章正文并生成学习笔记，并提供次级链接到帖子洞察；次级链接只预填，不自动产生外部 API 或 LLM 调用。

帖子洞察页面仍由用户点击“分析”显式提交 `analysis_intent=post_insight` 所对应的独立接口。

### 公众号深度学习

`TranscribeRequest` 增加向后兼容字段：

- `analysis_intent` 默认 `deep_learning`
- `source_type` 可选；新首页显式传递

任务路由把字段放入队列。`process_task_queue` 继续传递到 `process_transcription`。服务端不信任客户端 `source_type`，也不只依赖当前未锚定 host 的 `URLParser` 正则；统一 canonical predicate 使用 `urlsplit()`，只在 hostname 严格等于 `mp.weixin.qq.com` 且路径/查询符合受支持文章形态时识别为公众号文章。当 canonical predicate 成立且意图为 `deep_learning` 时：

1. `WeixinPostFetcher.fetch_article()` 只获取正文，不拉留言；
2. 服务端强制派生 `effective_include_comments=False`，覆盖缓存判定和全部 LLM 载荷；
3. 保存为 `platform=weixin` 的文本缓存；
4. 可选保存源文档；
5. 进入既有 `llm_task_queue`；
6. 任务状态进入 `CALIBRATING`，结果继续由 `/view/<view_token>` 承载。

评论洞察不作为默认步骤，避免把运营意图带入学习输出，也避免不必要的额外 TikHub 调用。

LLM 队列根据服务端确认的 `wechat_mp_article + deep_learning` 派生
`deep_learning_article` 总结契约。该契约要求输出核心问题、三分钟摘要、
结构化大纲、关键概念、论点与原文证据、事实/观点/待核实、盲点与反思、
行动清单、复习卡、自测题和继续追问，并禁止虚构引用或混入社交运营建议。
该 profile 同时传入首次生成、部分缓存补算和 summary-only 自动重试；其他
来源继续使用原有单/多说话人模板。

### 结果与费用边界

公众号深度学习复用服务端任务、缓存、历史和稳定 `view_token`。本轮证明并承诺两条边界：结果页刷新不发起新的抓取/LLM 请求；成功缓存落盘后的串行重提复用结果。API 级并发同源提交在缓存落盘前的 in-flight 合并不在本轮保证范围，不能据此声称并发绝不重复计费。帖子洞察的 `?url=` 只预填，必须再次点击按钮才会调用 TikHub/LLM；页面明确提示该操作可能产生费用。现有本地 `?view=` 仅作为旧结果兼容，本轮不引入数据库 schema。

## 错误处理

- TikHub Token/scope 错误保持失败并脱敏展示，不降级绕过权限。
- 公众号正文为空时任务失败，错误明确指出无法获取正文。
- `wechat_channels_video` 不进入公众号文章抓取器。
- 客户端伪造 `source_type` 不作为服务端路由真相；服务端以 canonical hostname/path predicate 决定公众号抓取器。
- 旧客户端未发送新字段时继续默认深度学习，不破坏现有调用。

## 测试策略

1. Node 单元测试证明 URL 提取不会从公众号 URL 生成内嵌 `qq.com` 假链接。
2. Node/静态测试证明单篇入口把公众号分类为文章、意图为深度学习、隐藏转录方式并不包含静默 `/post` 跳转。
3. Python 单元测试先证明公众号正文可独立抓取且不请求留言。
4. Python 单元测试证明公众号文章保存正文、进入 LLM 队列、更新任务状态，并覆盖真实 mp 正例、lookalike host、userinfo、子域和视频号负例。
5. Python 单元测试证明 `include_comments=true` 在公众号深度学习的冷缓存、部分缓存和完整缓存路径都被强制关闭。
6. API 路由与 worker 转发测试证明 `source_type` 和 `analysis_intent` 从 HTTP 请求一直进入 `process_transcription`。
7. 模板测试证明 `?url=` 不自动分析、结果页刷新不发请求且显示费用提示。
8. 串行缓存重提测试证明成功缓存不会重新抓取或重新运行 LLM。
9. 最后运行相关单元测试、JS 语法检查、必要 UI 验证和 GitNexus `detect_changes`。
10. LLM 兼容性测试证明新增 profile 是可选参数，公众号缓存补算和自动重试不会退回通用视频总结。

# X / Twitter 帖子精华提炼 — 设计文档

- 日期：2026-06-09
- 范围：本期只做 X / Twitter。小红书图文、微信公众号为后续增量，沿用同一管线。
- 状态：已与用户对齐方向，进入实现。

## 1. 目标与痛点

用户经常看 X 上的帖子，但**无法快速判断帖子内容与高赞回复"是否属实、是否对自己有价值"**，
现有流程要手动下载、复制评论再打包给 AI，繁杂。

本功能：输入一条推文链接 → 自动抓取「作者完整 thread（正文）+ 高赞回复（评论区）」→ LLM
审核、分析、提炼 → 输出对用户有价值的精华，**并显式给出可信度/存疑判断**。

验收两条硬线：
1. 功能正确：thread 与高赞回复抓得到、分析准确。
2. 结果页交互优质：可信度判断视觉突出；具备加载进度、原文折叠、一键复制等体验。

## 2. 设计原则

复用优先、低耦合。现有评论洞察管线（fetch → select → analyze → insight）整套复用，
新代码集中在「X 数据入口」与「帖子专用分析 prompt」两处，不动现有视频链路（零回归风险）。

## 3. 架构与复用边界

```
推文链接 x.com/<user>/status/<id>
  │
  ▼
URLParser → platform=twitter, tweet_id           [改] url_parser.py 加 twitter 正则；t.co 短链复用现有 HEAD 解析
  │
  ▼
TwitterPostFetcher (经 TikHub)                    [新] 工作量主体
  ├─ 作者自接 thread ─► 正文文本(summary_text)
  └─ 回复列表        ─► CommentItem[]              复用 comments/fetcher.py 归一化逻辑(补 twitter 字段别名)
  │
  ▼
select_high_value_comments()                      [复用] comments/selector.py 原样
  │
  ▼
PostInsightAnalyzer                               [新] 帖子专用 prompt，复用 analyzer.py LLM 调用骨架
  │
  ▼
insight = 正文核心主张 + 可信度/存疑 + 评论区共识/争议 + 可行动启发
  │
  ▼
任务 + Web 结果页                                  [新] 独立并联流程，不改视频管线；复用 task_progress / 渲染 / base.html
```

| 模块 | 处理 |
|---|---|
| `comments/pipeline.py` | 复用编排（必要时抽象出"内容来源"参数：视频=转写文本 / 帖子=正文文本） |
| `comments/selector.py` | 原样复用 |
| `comments/analyzer.py` | LLM 调用骨架复用；新增帖子 prompt 常量，**不改现有视频 prompt** |
| `utils/url_parser.py` | 新增 twitter 平台识别与 tweet_id 提取 |
| Twitter thread + 回复抓取 | 新增 `downloaders` / `comments` 下的 twitter 入口 |
| 任务/Web 入口 | 新增独立「帖子洞察」流程，**不改视频管线**；复用 task 进度 / Markdown 渲染 / base.html |

> 不另起独立 `posts/` 管线——会重复抄一遍 select/analyze/编排，违背高复用原则。

## 4. 帖子分析输出契约（核心价值，针对"是否属实"痛点）

帖子专用 prompt 固定输出以下结构（中文 Markdown），供前端结构化渲染：

- **正文核心主张**：作者到底在说什么（thread 提炼，不堆砌原文）
- **可信度 / 存疑点**：逐条标注——
  - ✓ 共识/可信　⚠ 单方面断言　❗需外部核实　🔁 回复区有反驳
- **评论区：共识 vs 争议**：高赞回复在补充还是打脸
- **代表性高赞回复**：附点赞数
- **对你的可行动启发**

LLM 信息不足时必须明说，禁止强行拔高（沿用现有 analyzer 的诚实约束）。

## 5. 结果页交互契约（UX 硬要求）

新增 X 帖子洞察结果页，对齐并抬高现有 `base.html` / `styles.css` 风格：

- **来源头部**：作者、原推链接（新窗口打开）、抓取时间、回复抓取数量。
- **可信度区视觉优先**：用色彩/徽章把 ✓/⚠/❗/🔁 做成可扫读的卡片，是页面重点，不可埋进长文本。
- **正文与原文分离**：默认展示"核心主张"，原 thread 折叠可展开核对。
- **评论区精华**：共识/争议分栏；代表性回复带点赞数与作者。
- **加载/进度**：抓取 + LLM 有秒级耗时，复用 `task_progress.py` / `processing.html` 进度反馈，不空白卡死。
- **一键复制**：整篇精华可复制（用户原痛点就是"复制打包给 AI"，这里直接给成品）。
- **响应式**：桌面/移动端均可读。
- **空/异常态**：无回复、受保护/已删除推文、抓取失败都有明确文案，不留死路。

## 6. 错误处理

- TikHub 失败/限流/非 0 code：明确错误态，记录日志（沿用现有 logging）。
- 受保护账号 / 推文已删除 / 链接无效：前置校验并给用户可读提示。
- 无回复：仍输出正文分析，评论区标注"无可用回复"。
- 评论洞察是可选增强，正文分析失败才算任务失败。

## 7. 测试策略

- `url_parser`：twitter 链接（标准 / x.com / 含 query / t.co 短链）→ 平台与 tweet_id 解析，确定性单测。
- Twitter 归一化：用**固定 fixture JSON**（依据 TikHub 文档响应）测 thread 组装与回复归一化，
  不依赖网络，确定性。
- selector：已有覆盖，复用。
- 任务分支：platform=twitter 跳过转写、走帖子分析的集成测试。
- 全部测试置于 `tests/`，console 输出纯英文、无 emoji/中文。

## 8. 风险

- **TikHub Twitter 响应字段名需以真实/文档响应核对**：归一化器多字段兜底（`_normalize_comment`
  已是此设计），落地时补 twitter 别名并以 fixture 锁定。执行前确认 `config.jsonc` 是否已配 TikHub key
  决定能否实测；否则 fixture 优先。
- thread 组装边界（作者中途夹杂他人回复、引用）：v1 只取作者连续自接，规则明确、可后续增强。

## 9. v1 明确不做（YAGNI）

- 引用转推（quote tweet）纳入评论区——后续增量。
- 小红书图文、公众号——后续按同一管线接入。

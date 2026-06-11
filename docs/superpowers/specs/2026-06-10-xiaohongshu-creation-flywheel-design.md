# 小红书对标驱动的创作飞轮 — 最终设计（MVP）

> 状态：**已定稿**（UI/IA 经多轮 mockup 评审通过）· 日期：2026-06-10 · 分支：codex/comment-insights
> 可视化原型：`docs/superpowers/mockups/flywheel-mockup.html`

## 1. 产品与价值

- **用户**：在做内容的创作者（持续产出，含起步期）。
- **核心 job**：学对标 → 用自己的真实数据验证 → 按反馈迭代 → 内容越做越好（**为结果买单**，不为未经验证的方法论买单）。
- **飞轮**：学(拆对标) → 做(产出) → 测(我的数据) → 改(对比诊断 + 迭代) → 个性化方法论沉淀 → 循环。
- **护城河**：用户自己的实验史 + 个性化 playbook 沉淀，用得越久越值钱。

## 2. 信息架构（详见 mockup）

- **底部三 Tab**：
  - **内容**：跨博主内容列表（待解析为主）+ 强筛选 + 按「日期↓→博主」分组 + 分页。triage 入口。
  - **博主**：我订阅的博主列表 → 博主详情（个人说明 + 历史内容 + 「总结整体套路」）。
  - **我的**：我的账号 + 本月进步 + 「下一条建议」 + 我的笔记诊断 + 用量与成本入口。**飞轮回报的主场。**
- **两个入口（关键区分）**：① **临时解析(adhoc)**：贴单条链接直接拆，不订阅；② **订阅(feed)**：订阅博主→追更新，**默认不解析**，按需手动解析。**订阅 ≠ 解析。**
- **首次使用**：空状态走"贴一个博主/内容 → 秒懂为什么火"的惊艳路径，而非空列表。
- **视频与图文严格分离**：分析维度、提示词、展示均按 `media_type` 分叉，不互相污染。

## 3. 解析与方法论

- **单条解析**：一条内容 → 结构化拆解（视频：开头/中段/结尾；图文：标题/封面/正文）+ 一句"可马上照做的事"。
- **整体套路（多样本，map → reduce + 数据加权）**：
  1. *map*：逐条拆成结构化特征 + 真实数据（**缓存**，新内容只拆增量）。
  2. *reduce*：跨多条找"爆款共性 vs 普通款差异"，按表现加权，输出**带证据 + 样本量**的方法论。
- **提示词可查看可编辑**：视频/图文两套，存版本号，改完重算。
- **异步**：解析耗时十几秒 → 状态机 `pending → processing → success / failed`。

## 4. 数据策略（务实 + 诚实）

- **地基 = 公开互动数据**（赞/藏/评/转/粉丝）：对标与本人同一接口 `get_user_posted_notes`。
- **增强 = 用户手动回填**关键后台数据（曝光/CTR/完播）：MVP 手填；V1.5 截图 OCR；**不做** cookie 抓取（非官方、易碎、ToS 风险）。
- **局限与缓解**：公开数据受曝光影响 → 用相对基准（对自己历史 / 对标同类）+ 自我对照抵消噪声，结论方向性可靠。

## 5. 筛选与排序（可选值已定稿）

| 筛选项 | 可选值 | 单/多选 | 参数 → 字段 |
|---|---|---|---|
| 订阅状态 | 全部 / 已订阅 / 未订阅(临时解析) | 单 | `subscribe` → `blogger.is_subscribed` |
| 博主 | 全部 / 我订阅的(多选，**动态来自订阅列表**) | 多 | `blogger_ids[]` → `content.blogger_id` |
| 解析状态 | 待解析 / 解析中 / 解析成功 / 解析失败 | 多 | `status[]` → `content.analysis_status` |
| 类型 | 全部 / 视频 / 图文 | 单 | `media_type` → `content.media_type` |
| 发布日期 | 今天 / 近7天 / 近30天 / 近90天 / 全部 / 自定义 | 单+区间 | `date_from,date_to` → `content.published_at` |
| 排序 | 最新发布(默认) / 最高赞 | 单 | `sort` → `published_at↓` / `like_count↓` |

- **博主列表排序**：智能(置顶 → 待解析数 → 最近更新，默认) / 最近更新 / 粉丝数 / 名称。
- **博主筛选选项动态**：前端拉 `GET /api/bloggers` 填充，博主增删即变。
- **用量统计维度**：周期(本周/本月/自定义) × 博主(全部/单个)。

## 6. 数据模型（SQLite，置于 Repository 接口后；上线换 Supabase）

```
blogger   id · platform · platform_user_id · handle · avatar · bio
          · follower_count · media_types[] · is_subscribed · pinned · last_post_at · subscribed_at
content   id · blogger_id · platform · platform_item_id · media_type(video/article)
          · title · original_url · cover_url · published_at
          · like_count · collect_count · comment_count · share_count · stats_synced_at
          · source(feed/adhoc) · analysis_status(pending/processing/success/failed) · latest_analysis_id
          索引: (blogger_id, published_at↓) · (analysis_status) · (published_at↓) · (media_type)
analysis  id · content_id · media_type · status · result_json · error_message · prompt_version · model · created_at
analysis_cost  id · analysis_id · content_id · blogger_id · fetch_cost · llm_cost · total_cost · currency · in_tokens · out_tokens · created_at
prompt_template  id · media_type(video/article) · version · body · is_default · updated_at
my_account / my_content / diagnosis  —— 我的账号、我的笔记、我的笔记×对标的诊断结果
```

- **adhoc 内容也建 blogger 行**（`is_subscribed=false`），不留空 FK；"未订阅" = `is_subscribed=false`。
- 持久化沿用现有 `sqlite3`（`cache_manager` 已用，WAL 模式），但**新表走 Repository 抽象**，业务逻辑不直连 SQL。

## 7. 关键能力

- **批量解析**：列表多选 → 预估成本 → 批量入队（异步）。
- **成本**：每条解析记一笔 `analysis_cost`（抓取 + LLM）→ 按周期/博主聚合。
- **订阅追更机制**：订阅时拉博主近 N 条入库为 `pending`；用户进 App 被动刷新增量（MVP 不做后台定时/推送）。

## 8. 复用现有代码

`comments/` 按平台 fetcher 思路（新增 `xiaohongshu_user` 账号作品列表）· `transcriber/`（视频**带时间戳**转写，用于切分开头/中段/结尾）· `post_insight` 卡片渲染 · `cache_manager` · `task_progress`（分阶段 loading）· 首页 Bearer Token。新增 `api/services/flywheel/` 编排，独立流不污染转写主线。

## 9. MVP 范围（Musk 精简后）

**做**：小红书；临时解析 + 订阅追更；单条解析（视频+图文，提示词分离）；整体套路（多样本+证据）；我的诊断 + 下一条建议；5 筛选 + 排序 + 分页 + 分组；博主详情；批量解析；成本明细；提示词编辑；首次惊艳页。

**不做（V1.5/V2）**：截图 OCR 回填、AI 代写草稿、定时推送、选题灵感流、多平台(公众号/抖音/B站/YouTube/Reddit)、多租户登录鉴权、跨博主对比、付费墙。

## 10. 错误处理 / 测试 / Roadmap

- **错误**：抓取失败→标 `failed` + 重试 + 原因；笔记数上限；视频转写超时降级；回填数值校验；空态/冷启动友好。
- **测试**（`tests/`，console 纯英文）：ContentUnit/媒体类型映射、筛选与排序逻辑、解析状态机、成本聚合、多样本 reduce 的 schema 校验、Repository CRUD；mock TikHub 集成；不依赖真实网络/模型。
- **Roadmap**：V1.5 截图回填 + AI 代写 + 方法论自动个性化；V2 监控订阅 + 选题流 + 多平台 + Supabase 多租户。

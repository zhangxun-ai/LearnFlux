# LearnFlux 复盘模块技术方案

## 1. 目标与边界

复盘模块把分散的日常记录逐步组织成可追溯的周、月、年视图，以及仍可被证伪的内在洞察。第一版完成桌面 Web 闭环：记录、聚合、连接、抽象、行动实验、AI 候选确认、搜索回看和 Obsidian 同步。

明确不做：原生移动端、系统通知、连续打卡、积分与游戏化、社交协作、自由画布、语音输入和桌面打包。

## 2. 方法映射

以下内容来自对《复盘自己：从记录到蜕变的行动指南》的全文与关键版式审阅，产品只吸收方法，不复刻书页或长段文字。

| 方法要点 | 产品落点 |
| --- | --- |
| 复盘不是自我批评，也不要求预先拥有宏大目标 | 所有提示使用观察式语言；允许空项、负面体验和暂时无结论 |
| 先分开事实与感受，再区分他人与自己、行动与结果、过去与现在 | 今日复盘的“当时 / 现在”时间铰链矩阵 |
| 为经历赋予用户真正认可的意义 | 意义类型可选发现、学习、决断、喜悦、直觉或自定义，AI 不强迫积极解释 |
| 周复盘依次聚焦、连接、抽象、具体化 | 周度左侧四步工作区，右侧保留每日来源 |
| 连接可能直接、间接或出乎意料 | 独立连接记录，必须带来源和用户确认 |
| 抽象从枝叶到树干再到树根逐层深入 | 八级抽象区，按枝叶 / 树干 / 树根分组，不把候选洞察写成定论 |
| 具体化应回到可立即验证的行动 | 4W1H、资源预算、成功信号、复查日期和后续结果 |
| 月度记录允许内心、行动、结果彼此独立 | 四列月度表，不自动制造因果箭头 |
| 重复记录、碎片记录和中断后重启都有效 | 自动草稿、重复内容不报错、新手模式与无惩罚空状态 |
| 通过事实与内在声音来回观察，避免陷入责备 | 来源抽屉、反例、不同视角和不确定性字段 |

## 3. 现有能力审计与复用

- Web：沿用 FastAPI 静态页面路由、`app-shell.css`、`product-linear.css`、统一侧栏生成器和现有 Bearer Token 读取约定。
- 数据：沿用 repository 模式与 `get_repository_database()`，同时兼容 SQLite 路径、SQLite 适配器和 PostgreSQL 适配器。项目当前没有 ORM 或 Alembic；PostgreSQL 使用编号 SQL migration，因此新增同风格 migration。
- LLM：沿用 `call_llm_api()`、项目当前模型配置、结构化 `response_schema`、既有重试与错误返回。现有 HTTP 层没有可直接复用的流式响应基元，第一版采用有加载状态的完整结构化响应，不伪造流式输出。
- Obsidian：复用 `resolve_vault_path()`、`ensure_vault_directory_tree()` 与 `atomic_write_text()`；不另造 Vault 选择或文件写入体系。
- 时间：沿用项目配置时区；周界固定默认为周一至周日，并在偏好中保留周起始日字段。
- 日志：沿用项目 logger，console 消息使用英文。

## 4. 数据模型

所有主键使用带类型前缀的稳定 UUID，时间字段使用 UTC ISO 时间，业务日期使用用户配置时区的 `YYYY-MM-DD`。

| 表 | 主要职责 |
| --- | --- |
| `review_daily_events` | 一天多事件、当时/现在矩阵、情绪、来源、排序与软状态 |
| `review_weekly_reviews` | 周范围、聚焦顺序、抽象层级和周总结 |
| `review_connections` | 直接/间接/意外连接及来源集合 |
| `review_action_experiments` | 4W1H、资源预算、成功信号、复查与结果 |
| `review_monthly_reviews` | 内心/行动/结果/备注四列及跨月连接 |
| `review_annual_reviews` | 年度关键词、用户总结与来源集合 |
| `review_insights` | 枝叶/树干/树根洞察、证据、反例、不确定性和状态 |
| `review_ai_candidates` | AI 候选、调用范围、模型、确认状态与确认后内容 |
| `review_preferences` | 新手模式、周起始日和 Obsidian 覆盖偏好 |
| `review_sync_state` | 每条记录的目标路径、内容哈希、状态和错误 |

复杂数组与矩阵以 JSON 文本保存，避免 SQLite/PostgreSQL 类型分叉；查询频繁的用户、日期、类型和状态保留独立列与索引。

连接同时保存 `source_type/source_id`、`target_type/target_id` 与方向，来源引用统一保存类型、ID、日期和可读标签。洞察的时间跨度、独立来源数、来源类型与反例数由程序确定性计算，不采用模型随意给出的可信度百分比。

## 5. API 与服务边界

页面入口为 `/review`，内部 tab 由 URL hash 表示，仍然只有一个侧栏一级入口。

核心 API：

- `/api/reviews/daily-events`：按日期查询、新建与批量排序。
- `/api/reviews/daily-events/{id}`：读取、更新、复制、删除。
- `/api/reviews/weekly/{week_start}`：读取/保存周复盘和自动聚合的每日来源。
- `/api/reviews/connections`、`/api/reviews/action-experiments`：连接与行动实验 CRUD。
- `/api/reviews/monthly/{month}`、`/api/reviews/annual/{year}`：周期复盘读取/保存。
- `/api/reviews/insights`：分层、状态与证据筛选。
- `/api/reviews/search`：时间、类型、关键词、意义、情绪与状态组合筛选。
- `/api/reviews/source/{source_type}/{source_id}`：统一来源追溯。
- `/api/reviews/ai/analyze`、`/api/reviews/ai-candidates/{id}/confirm`：主动调用与显式确认。
- `/api/reviews/sync`、`/api/reviews/sync-status`：同步和失败重试。
- `/api/reviews/preferences`：新手模式与周期偏好。

路由只做身份、参数和响应转换；`ReviewService` 负责编排 repository、AI 和 Obsidian，具体持久化、Markdown 和同步规则各自独立。

现有 `/static/history.html` 增加统一记录类型筛选，通过同一个 `/api/reviews/search` 组合日期、关键词、类型、意义、情绪、洞察层级和状态。结果使用 `source_type/source_id` 深链回 `/review` 并自动打开来源抽屉。

## 6. AI 数据流与确认边界

```text
用户点击 AI → 前端展示本次范围/目的 → 用户确认调用
→ 服务端按 source_id 重新读取原始记录
→ 结构化模型调用 → 校验来源只能落在本次范围内
→ 保存为“AI 候选” → 前端展示证据/反例/不确定性
→ 用户编辑并确认 → 才改变正式复盘或洞察数据
```

模型输出统一包含候选陈述、层级、证据来源、可能反例、不确定性、追问和可验证实验。提示词明确禁止心理诊断、人格定论、道德评判、强迫积极解释，以及将相关性写成确定因果。枝叶、树干和树根候选由有效记录数、周/月记录数和时间跨度决定可到达的最深层级；超出层级的模型结果直接丢弃。年度分析最多接收十二类有来源候选，其余分析最多五条。结构化解析失败可在既有 LLM 层重试；最终失败保留用户原文与现有页面状态。

## 7. Obsidian 规则

默认根目录为 `复盘`，可通过 `obsidian.review_root` 配置：

```text
复盘/
├── 每日/YYYY/YYYY-MM-DD-每日复盘.md
├── 周度/YYYY/YYYY-Www-周度复盘.md
├── 月度/YYYY/YYYY-MM-月度复盘.md
├── 年度/YYYY-年度复盘.md
├── 内在洞察/
└── 行动实验/
```

Frontmatter 固定包含 `id`、`type`、`period`、`created_at`、`updated_at`、`source_ids`、`related_ids`、`status` 和 `learnflux_managed`。正文由 LearnFlux 管理区标记包裹：重复同步只替换该区并保留标记外的用户内容。周、月和行动实验保存后会刷新相关每日文档的反向链接；每日事件使用稳定块 ID。若目标文件已存在但没有 LearnFlux 标识，则报告冲突，不覆盖。数据库写入先完成；同步失败只更新 `review_sync_state`，不回滚或删除数据库记录。

## 8. 界面信息架构

视觉延续 LearnFlux 的冷白/蓝色产品系统，正文使用既有 Inter 与中文系统字体，日期和数据使用等宽数字。标志性构图是今日复盘的“时间铰链”：事件跨在上方，中轴把“当时”与“现在”分开，同一语义行可以直接对照。

```text
┌ 复盘  [今日] [周度] [月度] [年度] [内在洞察] [复盘指南] ┐
│ 日期/周期    保存·同步状态    搜索    新手模式    新增      │
├──────────────────────────────────────────────────────────┤
│ 今日：事件桥                                                   │
│        当时       │ 时间中轴 │       现在                      │
│ 事实   …          │          │ 新视角 …                        │
│ 意义   …          │          │ 自我发现 …                      │
│ 行动   …          │          │ 可控行动 …                      │
│ 结果   …          │          │ 后续结果 …                      │
└──────────────────────────────────────────────────────────┘
```

周度在宽屏使用左侧四步、右侧每日来源的双栏；月度用四列；年度用十二行月份全景；窄屏统一改为单列并保留 sticky tab。深色模式全部使用现有 design token，不写死白色背景。

## 9. 实施与验证顺序

1. 建立跨 SQLite/PostgreSQL schema、repository、周期计算和迁移。
2. 先用单元测试保护日期边界、CRUD、来源链、AI 确认和 Markdown 幂等合并。
3. 实现服务、API、配置与 Obsidian 同步。
4. 接入一级导航，完成六个视图及搜索/来源/AI/帮助抽屉。
5. 运行模块测试、相关 UI/路由测试、全量单元测试，再做浏览器桌面、窄屏与深色验收。

## 10. 已知工程约束

- 当前工作区在本任务开始前已有大量未提交的 PostgreSQL 迁移改动；本模块只在必要文件上追加，不回退或覆盖这些改动。
- 单元测试基线为 `2377 passed, 1 skipped, 1 failed`；唯一失败是既有导航生成漂移（`focus-studio.html`、`history.html`），不是复盘模块引入。
- 收尾全量单元测试为 `2404 passed, 1 skipped`；JavaScript/Python 语法检查、导航同步检查与 `git diff --check` 均通过。
- GitNexus 当前提交索引未能定位 `create_app`，按项目规则执行增量重建时又遇到其 LadybugDB FTS 索引损坏；收尾 `detect_changes` 可执行，但它把工作区原有改动一起计入，聚合结果为 276 个符号、147 条受影响流程、79 个文件和 `critical` 风险级别，不能单独视为本模块的风险评级。

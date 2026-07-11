# 单节与全系列两层图解设计

日期：2026-07-11

## 1. 目标

现有内容工作台已经能够生成单节源内容解读和全系列解读，但纯文字解读仍要求用户自行建立内容结构。本次改动为两类解读增加同一套“两层图解”阅读模型：

1. **宏观层**：先展示当前单节或全系列的全局图解，说明主线、阶段、核心机制和关键关系。
2. **小节层**：再按主题小节展示文字解读与对应核心图，支持从图回到文字、从文字回到图，并可继续定位到 source 或原文依据。

成功标准：用户无需在全局视野和细节图解之间二选一；打开图解视图后，可以先建立整体心智模型，再沿同一主线逐节深入。

## 2. 已确认的产品决策

- 单节和全系列都使用“全局图解 + 小节图解”，不是只给全系列总览。
- 小节采用主题章节粒度，一段完整解读对应一张核心图；不为每句话生成碎片小图。
- 全局图解必须是解读的第一层正式内容，不是装饰性缩略图。
- 全局节点、小节图、文字解读和原文依据使用稳定引用关联。
- 沿用现有结构化 JSON + HTML/SVG 渲染，不在本次接入图片生成模型。
- 保留现有纯文字解读、知识地图和源内容入口，图解不覆盖原数据。
- 用户已经通过本地高保真原型确认两层阅读结构，可以进入实现阶段。

## 3. 范围

### 3.1 本次实现

- 单节学习页的图解标签连续展示：
  - 本节全局图解；
  - 逐主题文字解读与对应图解；
  - 查看原文依据和双向高亮。
- 全系列内容页新增图解视图，连续展示：
  - 跨 source 的全系列主线图；
  - 逐主题或阶段的文字解读与对应图解；
  - 查看对应 source、source 解读或原文依据。
- 两层内容分别保存和恢复状态；一层失败不阻塞另一层阅读。
- 首次进入图解视图时按需生成，未打开的历史内容不产生额外图解调用。
- 支持现有主题切换、SVG 导出和打印能力。

### 3.2 不在本次实现

- 图片模型生成的概念插画。
- 自由画布、拖拽排版或节点人工编辑。
- 新的视觉文档版本系统。
- 修改单节文字解读或全系列解读的生成逻辑。
- 把知识地图替换为两层图解；二者继续作为不同阅读入口存在。
- 为没有来源依据的内容补写或猜测事实。

## 4. 用户体验

### 4.1 单节图解

单节学习页保留 `AI 看 / 图解 / 文稿 / 问 AI`。用户第一次进入 `图解` 后：

1. 页面先请求 `overview`，展示“本节全局图解”。
2. 页面继续请求 `full_note`，并在全局图下方展示逐主题内容。
3. 每个主题使用左右对应布局：文字解读在一侧，核心图在另一侧；窄屏改为上下布局。
4. 点击文字主题或图中节点时，双方使用同一 section/page id 高亮。
5. 点击“查看依据”继续使用已有 source reference 行为：视频定位时间，文本定位段落。

如果 `overview` 已可用而 `full_note` 尚未完成，全局图保持可读，下方显示小节生成进度；反向同理。

### 4.2 全系列图解

全系列内容页在现有 `知识地图 / 全系列解读 / 源内容 / 导出笔记` 中增加 `图解`。进入后：

1. 顶部展示跨 source 的全系列全局图解，优先表达主线、阶段、依赖和核心机制。
2. 下方展示逐主题图解。主题按全系列解读结构组织，不简单按 17 个 source 逐个堆叠。
3. 每个全局节点显示其覆盖的主题或 source；点击后滚动到对应小节并高亮。
4. 每个小节保留 source 编号和依据入口；点击后选中左侧 source，并打开其解读或原文位置。

### 4.3 生成时机

两层图解只在用户进入 `图解` 视图后触发：

- 并行检查 `overview` 与 `full_note` 的已有状态。
- 缺失时先发起 `overview`，随后发起 `full_note`；已有成功结果立即复用。
- 两个请求和轮询彼此独立，避免一个失败让整个图解视图不可用。
- 用户离开页面不取消服务端任务；再次打开时恢复最新状态。
- “重新生成”按层执行，默认不同时废弃两个成功结果。

## 5. 架构与复用

### 5.1 复用现有视觉学习模块

继续使用：

- `visual_learning.schemas.VisualDocument`、`VisualPage` 和现有 block 类型；
- `overview` 作为宏观层，保持单页限制；
- `full_note` 作为小节层，保持 3–8 页限制；
- `VisualLearningRepository` 的 owner、document type、request key 和成功版本保留机制；
- `visual-learning.js` 的通用 HTML/SVG 渲染、主题和 source reference 渲染；
- 单节 `StudySourceResolver`、现有生成服务和 API。

现有数据库已经支持 `owner_type=study|collection` 和 `document_type=overview|full_note|diagram`，本次不新增表或迁移。

### 5.2 新增全系列 source resolver

在 `visual_learning` 模块增加聚焦的 collection resolver。它只负责把现有全系列数据整理为 `VisualLearningSource`，不复制全系列总结逻辑。输入优先级：

1. 全系列解读 `summary_markdown`；
2. 全系列知识地图；
3. 各 source 的 AI 解读；
4. 必要时使用各 source 的原文摘录。

引用 id 使用稳定格式：

- `collection:{collection_id}:summary`
- `collection:{collection_id}:knowledge-map`
- `collection:{collection_id}:source:{source_id}:summary`
- `collection:{collection_id}:source:{source_id}:paragraph:{index}`

resolver 只输出仓库中真实存在的内容；缺失项不生成占位事实。

### 5.3 服务与 API

在 `VisualLearningService` 增加与 study 对称的 collection 方法，内部复用同一生成、校验、幂等和持久化路径：

- `prepare_collection_generation`
- `generate_prepared_collection`
- `get_collection_state`

新增路由：

- `GET /api/visual-learning/collections/{collection_id}?document_type=overview|full_note`
- `POST /api/visual-learning/collections/{collection_id}/generate`

请求体沿用现有 `VisualGenerateRequest`。路由继续使用当前鉴权、后台任务和统一响应格式，不创建第二套视觉生成协议。

### 5.4 前端组合器

通用渲染器继续只渲染一份 `VisualDocument`。单节页和全系列页各自增加轻量组合器，负责：

- 获取并轮询 `overview` 与 `full_note`；
- 将两份文档按“宏观 → 小节”顺序放入同一连续阅读区；
- 用 `VisualPage.id`、block id 和 `source_ref_ids` 建立 DOM data 属性；
- 处理全局节点到小节、文字到图、图到文字的滚动与临时高亮；
- 分别显示两层状态和重新生成入口。

双向对应只增加 DOM 关联和交互，不修改后端 block schema。无法找到目标 id 时保持当前阅读位置并显示轻量提示，不抛出页面级错误。

## 6. 数据流

```text
单节 view token / 全系列 collection id
                 ↓
 StudySourceResolver / CollectionSourceResolver
                 ↓
       同一份真实解读与 source refs
            ↙                 ↘
 overview（宏观层）      full_note（小节层）
            ↘                 ↙
       VisualLearningRepository
                 ↓
     前端两层组合器 + 通用渲染器
                 ↓
 全局节点 ↔ 小节文字 ↔ 小节图 ↔ 原文依据
```

`overview` 和 `full_note` 拥有各自的 request key。原文、单节解读、全系列解读或知识地图变化后，source hash 改变，新请求自然生成新版本；旧成功结果在新版本成功前继续可读。

## 7. 内容约束

### 7.1 宏观层

- 单页，最多 5 个 block。
- 必须表达至少一条贯穿内容的关系，而不是罗列摘要卡片。
- 单节宏观图至少引用两个有效内容区段；内容不足时引用全部可用区段。
- 全系列宏观图在 source 数量允许时至少覆盖 3 个主题或 source。
- 节点标题短、关系标签明确，避免在 SVG 内放入大段中文。

### 7.2 小节层

- 3–8 个主题页，按内容结构而非固定 source 数量划分。
- 每页必须有文字解释、至少一个结构化图解 block 和有效 source references。
- 页 id 必须与生成大纲的 section id 一致，供前端双向定位。
- 同一主题的文字和图解共享该页 id，不新增不稳定的文本匹配逻辑。

## 8. 状态与错误处理

- source 尚未完成：显示现有解析进度，不创建空视觉文档。
- source 完成但解读缺失：返回明确“解读尚未就绪”，不退化为编造总结。
- `overview` 失败：小节层仍可展示和重试。
- `full_note` 失败：宏观层仍可展示和重试。
- LLM 返回无效 block 或引用：沿用现有规范化和引用校验，失败版本不覆盖上一个成功版本。
- 全系列某个 source 缺失：resolver 跳过该 source，并在可用信息不足时返回 source-not-ready。
- 页面重新打开：从 repository 恢复两层最新状态，不重复创建相同 request key。

## 9. 测试与验证

### 9.1 后端

- Collection resolver 按优先级读取真实数据并产生稳定 references。
- Collection resolver 不把缺失内容替换成占位事实。
- collection 的 `overview` 与 `full_note` 使用独立 request key，并可幂等复用。
- 两类文档生成、查询、失败保留旧成功版本的行为与 study 一致。
- 新路由的鉴权、参数校验、source-not-ready、404 和后台生成行为。
- 宏观层覆盖多个主题，小节层 page id 与大纲 section id 对齐。

### 9.2 前端

- 单节图解视图同时请求并渲染两层文档。
- 全系列页面包含图解入口，并使用 collection 视觉 API。
- 任一层失败时另一层仍保持可读。
- 点击全局节点能定位小节；点击文字或图解能高亮对应侧。
- source reference 继续触发视频时间或文本段落定位。
- 窄屏按“文字在上、图解在下”呈现，不产生横向溢出。
- 主题切换、SVG 导出和打印在组合视图中仍可用。

### 9.3 回归验证

- 运行视觉学习、study、collection 相关单元测试。
- 运行路由与主页静态资源测试。
- 使用本地真实单节和一个多 source 全系列进行浏览器验证。
- 验证工作区现有未提交改动没有被覆盖或格式化。

## 10. 实施边界

实现应优先扩展现有 `visual_learning` 模块，避免在 `collections.js` 或 `study.js` 复制生成逻辑。不得引入新依赖、数据库迁移或图片生成供应商。若现有未提交代码与本设计冲突，应停下并报告冲突，不得覆盖用户改动。

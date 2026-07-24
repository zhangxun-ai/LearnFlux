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
- 小节文字直接复用现有单节或全系列解读原文，图解生成不得改写一份平行解读。
- 全局图解必须是解读的第一层正式内容，不是装饰性缩略图。
- 全局主题入口、小节图、文字解读和原文依据使用稳定引用关联。
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
2. 页面继续请求 `full_note`，并在全局图下方展示逐主题内容。文字侧来自当前 `ai.overview` 的原文切分，`full_note` 提供与这些主题对应的结构化图解块；现有 schema 要求的 `review_questions` 保留为末尾复习区，不作为平行解读展示。
3. 每个主题使用左右对应布局：文字解读在一侧，核心图在另一侧；窄屏改为上下布局。
4. 点击文字主题或对应图解块时，双方使用同一 section/page id 高亮。首版不承诺图内单个节点与句子的精确映射。
5. 点击“查看依据”继续使用已有 source reference 行为：视频定位时间，文本定位段落。

如果 `overview` 已可用而 `full_note` 尚未完成，全局图保持可读，下方显示小节生成进度；反向同理。

### 4.2 全系列图解

全系列内容页在现有 `知识地图 / 全系列解读 / 源内容 / 导出笔记` 中增加 `图解`。进入后：

1. 顶部展示跨 source 的全系列全局图解，优先表达主线、阶段、依赖和核心机制。
2. 下方展示逐主题图解。文字侧逐字复用现有 `summary_markdown` 的对应主题内容；主题按全系列解读结构组织，不简单按 17 个 source 逐个堆叠。
3. 全局图中的主题入口显示其覆盖的主题或 source；点击入口后滚动到对应小节并高亮整个主题。普通图内节点仍按所在主题处理，不增加节点级映射协议。
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

### 5.2 解读主题切分

新增一个服务端共享的 `InterpretationSection` 视图模型，字段限定为 `id`、`title`、`markdown` 和 `source_ref_ids`。它不是新的持久化实体，负责把已有解读原文确定性地整理成 3–8 个主题：

1. 优先使用 Markdown 标题作为边界；标题下的正文保持原文，不让 LLM 重写。
2. 标题超过 8 个时按相邻顺序合并；不足 3 个时在自然段边界拆分较长主题。
3. 无标题时按非空自然段顺序分组。
4. 无法得到 3 个非空主题时返回 source-not-ready，不生成凑数内容。
5. id 使用当前文档内稳定的顺序 id（`section-01` 至 `section-08`）；解读变化由现有 source hash 触发新版本。

每个主题的引用按以下规则确定，不让 LLM 猜引用关系：

1. 为该主题原文创建一个稳定的解读引用：单节使用 `study:{view_token}:summary:section:{section_id}`，全系列使用 `collection:{collection_id}:summary:section:{section_id}`。它只表示“这段文字来自现有解读”，不伪装成 transcript 或 source 原文位置。
2. 复用现有 token-overlap evidence 选择逻辑，将主题标题和原文与真实 transcript、source 解读或原文 refs 比较；只保留交集大于 0 的结果，按现有排序最多取 6 个。
3. `source_ref_ids` 始终先包含主题解读引用，再包含匹配到的真实原文 refs。没有正向匹配时不补猜测引用。
4. 前端存在真实原文 ref 时显示“查看原文依据”；只有主题解读引用时显示“查看解读来源”，不提供虚假的精确跳转。
5. `full_note` 对应页面中的 block 引用必须是该主题 `source_ref_ids` 的子集，引用校验失败时沿用现有失败版本不覆盖规则。

单节和全系列状态 API 都返回同一份 `interpretation_sections`。前端只渲染这里的 `markdown` 作为文字侧；`VisualDocument` 中 LLM 生成的摘要文字不替代现有解读。`full_note.pages[*].id` 必须与这些 section id 一致。

### 5.3 新增全系列 source resolver

在 `visual_learning` 模块增加聚焦的 collection resolver。它只负责把现有全系列数据整理为 `VisualLearningSource`，不复制全系列总结逻辑。全系列 `summary_markdown` 是硬前置条件；其他输入只用于帮助图解理解结构、补充 source 级依据和建立跳转，不得在全系列解读缺失时替代它。补充输入优先级：

1. 全系列知识地图；
2. 各 source 的 AI 解读；
3. 必要时使用各 source 的原文摘录。

引用 id 使用稳定格式：

- `collection:{collection_id}:summary`
- `collection:{collection_id}:summary:section:{section_id}`
- `collection:{collection_id}:knowledge-map`
- `collection:{collection_id}:source:{source_id}:summary`
- `collection:{collection_id}:source:{source_id}:paragraph:{index}`

resolver 只输出仓库中真实存在的内容；缺失项不生成占位事实。

全系列图解可生成的最低条件是：存在非空 `summary_markdown`，并且至少一个 source 具有可读取的解读或原文依据。部分 source 缺失时跳过缺失项并继续；`summary_markdown` 缺失时一律返回 source-not-ready。

### 5.4 服务与 API

在 `VisualLearningService` 增加与 study 对称的 collection 方法，内部复用同一生成、校验、幂等和持久化路径：

- `prepare_collection_generation`
- `generate_prepared_collection`
- `get_collection_state`

新增路由：

- `GET /api/visual-learning/collections/{collection_id}?document_type=overview|full_note`
- `POST /api/visual-learning/collections/{collection_id}/generate`

请求体沿用现有 `VisualGenerationRequest`。路由继续使用当前鉴权、后台任务和统一响应格式，不创建第二套视觉生成协议。

单节和全系列状态响应增加 `interpretation_sections`，供组合视图显示现有解读原文。它由当前 source 即时派生，不写入 `visual_documents`。如果原 source 后续被移除，已经生成的图解仍可从文档详情接口打开，但文字侧显示“原解读已不可用”，不使用图解中的生成文字冒充原解读。

### 5.5 前端组合器

通用渲染器继续只渲染一份 `VisualDocument`。单节页和全系列页各自增加轻量组合器，负责：

- 获取并轮询 `overview` 与 `full_note`；
- 将两份文档按“宏观 → 小节”顺序放入同一连续阅读区；
- 用 `InterpretationSection.id`、`VisualPage.id`、block id 和 `source_ref_ids` 建立 DOM data 属性；
- 处理全局主题入口到小节、文字主题到图解块、图解块到文字主题的滚动与临时高亮；
- 分别显示两层状态和重新生成入口。
- 主题切换作用于两层共同的外层容器；打印输出完整连续视图。SVG 导出只导出当前聚焦的图解，默认是宏观层，用户点击某个小节后改为该小节图解，不尝试把多张 SVG 拼成一张。

双向对应只增加主题页和图解块级 DOM 关联，不修改后端 block schema，也不依赖文本模糊匹配。普通图内节点不建立句子级映射。无法找到目标 id 时保持当前阅读位置并显示轻量提示，不抛出页面级错误。

宏观 block 同时引用多个 section 时，其下方按 section 顺序展示多个可点击主题入口；点击入口定位对应小节。宏观图内部仍保持纯展示，不尝试从图形几何位置反推 section。

## 6. 数据流

```text
单节 view token / 全系列 collection id
                 ↓
 StudySourceResolver / CollectionSourceResolver
                 ↓
 InterpretationSection（现有解读原文）+ source refs
            ↙                 ↘
 overview（宏观层）      full_note（小节层）
            ↘                 ↙
       VisualLearningRepository
                 ↓
     前端两层组合器 + 通用渲染器
                 ↓
 全局主题入口 ↔ 小节文字 ↔ 小节图 ↔ 原文依据
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

- 3–8 个主题页，数量与确定性切分后的 `InterpretationSection` 完全一致，不按固定 source 数量划分。
- 文字解释由前端逐字显示 `InterpretationSection.markdown`；`full_note` 每页至少提供一个结构化图解 block 和有效 source references。最后一页继续保留 schema 强制的 `review_questions`，前端把它放在所有主题之后的复习区，不参与文字—图解高亮。
- 页 id 必须与 `InterpretationSection.id` 一致，供前端双向定位。
- 同一主题的原文文字和生成图解共享该页 id，不新增平行解读或不稳定的文本匹配逻辑。

## 8. 状态与错误处理

- source 尚未完成：显示现有解析进度，不创建空视觉文档。
- 单节 `ai.overview` 缺失，或全系列 `summary_markdown` 缺失：返回明确“解读尚未就绪”，不使用知识地图、source 摘要或原文替代主解读。
- `overview` 失败：小节层仍可展示和重试。
- `full_note` 失败：宏观层仍可展示和重试。
- LLM 返回无效 block 或引用：沿用现有规范化和引用校验，失败版本不覆盖上一个成功版本。
- 全系列某个 source 缺失：resolver 跳过该 source；只要 `summary_markdown` 存在且至少一个 source 仍有可读依据即可生成，否则返回 source-not-ready。
- 页面重新打开：从 repository 恢复两层最新状态，不重复创建相同 request key。

## 9. 测试与验证

### 9.1 后端

- Collection resolver 按优先级读取真实数据并产生稳定 references。
- Collection resolver 不把缺失内容替换成占位事实。
- 解读主题切分保持原文不变、稳定产生 3–8 个 section id，并在内容过短时返回 source-not-ready。
- 主题引用始终包含准确的解读 section ref；只有 token overlap 命中的真实依据才追加为原文 ref，未命中时不得伪造定位。
- collection 的 `overview` 与 `full_note` 使用独立 request key，并可幂等复用。
- 两类文档生成、查询、失败保留旧成功版本的行为与 study 一致。
- 新路由的鉴权、参数校验、source-not-ready、404 和后台生成行为。
- 宏观层覆盖多个主题，小节层 page id 与 `InterpretationSection.id` 对齐。

### 9.2 前端

- 单节图解视图同时请求并渲染两层文档。
- 全系列页面包含图解入口，并使用 collection 视觉 API。
- 任一层失败时另一层仍保持可读。
- 点击全局主题入口能定位小节；点击文字主题或图解块能高亮对应侧，不测试未承诺的节点到句子映射。
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

# 文字 / 图解沉浸阅读器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除解读中的 Markdown/YAML 噪音，并让全系列与单节解读都能在全屏阅读器中互斥切换文字和图解。

**Architecture:** 在 Python interpretation 边界规范化 Markdown，避免 front matter 成为伪章节；在 `visual-learning.js` 提供只负责布局与状态切换的共享沉浸阅读器。集合页和单节页继续各自负责 API、鉴权、生成与轮询，并通过 owner ID + reader generation 防止迟到响应污染。

**Tech Stack:** Python 3.11、FastAPI、原生 JavaScript、HTML/CSS、pytest。

---

### Task 1: 清理 Markdown 数据边界

**Files:**
- Modify: `src/video_transcript_api/visual_learning/interpretation.py`
- Modify: `src/video_transcript_api/visual_learning/source_resolver.py`
- Modify: `src/video_transcript_api/visual_learning/collection_source_resolver.py`
- Test: `tests/unit/test_visual_learning_interpretation.py`
- Test: `tests/unit/test_collection_visual_source.py`
- Test: `tests/unit/test_visual_learning_service.py`

- [ ] 新增真实失败用例：带 BOM、整文档 Markdown 围栏和开头 YAML front matter 的总结不能产生标题为 `---` 的 section；正文中的合法水平线保留。
- [ ] 运行上述两个聚焦用例并确认失败。
- [ ] 在 `interpretation.py` 增加单一 `normalize_interpretation_markdown()`，只清理文档级包装与开头 front matter。
- [ ] 让 study/collection resolver 的 summary、section 拆分和 source hash 使用同一份规范化文本。
- [ ] 增加一条 study resolver 接线用例：同一正文带/不带文档包装时，清理后的 summary、sections 与 source hash 一致。
- [ ] 运行 interpretation 与 collection source 聚焦套件。

### Task 2: 共享沉浸阅读器

**Files:**
- Modify: `src/web/static/js/visual-learning.js`
- Modify: `src/web/static/css/visual-learning.css`
- Test: `tests/unit/test_visual_learning_frontend_assets.py`
- Test: `tests/unit/test_visual_learning_reader_runtime.py`

- [ ] 写契约用例：共享 API 支持 `text/visual` 模式、全局/section 导航、互斥正文面板、关闭与模式/section 回调；共享 Markdown 渲染器防御性移除 front matter。
- [ ] 增加不依赖新包的轻量可执行 JS harness，验证 mode 切换保持 section、正文面板互斥，以及复习题只出现一个独立入口。
- [ ] 运行聚焦契约并确认失败。
- [ ] 实现 `renderImmersiveReader(container, model, options)`：薄顶部栏、模式 tab、章节轨道、单正文滚动区。
- [ ] 文字模式渲染全局 Markdown 或当前 section；图解模式渲染 overview 或 full_note 对应 page；stale full_note 显示更新提示而不配对；full_note 的 review_questions 汇总为末尾唯一“复习”入口。
- [ ] 添加全屏、响应式、键盘焦点与 reduced-motion 样式。
- [ ] 运行共享渲染器聚焦测试与 `node --check`。

### Task 3: 全系列页面接入

**Files:**
- Modify: `src/web/static/collections.html`
- Modify: `src/web/static/js/collections.js`
- Modify: `src/web/static/css/collections.css`
- Test: `tests/unit/test_visual_learning_frontend_assets.py`
- Test: `tests/unit/test_visual_learning_reader_runtime.py`

- [ ] 写主路径契约：集合“全系列解读”和“图解”都能打开同一沉浸层，并分别默认 text/visual；工作台不再渲染连续双层长页。
- [ ] 在轻量 JS harness 中写一个必要状态用例：生成中快速切换集合，旧 `collectionId + readerGeneration` 响应不能写入当前阅读器。
- [ ] 运行聚焦用例并确认失败。
- [ ] 增加集合阅读器 dialog/fixed layer、入口按钮与打开/关闭状态。
- [ ] 用共享阅读器替换 `renderTwoLayer` 主视图；overview/full_note 继续独立加载与重试。
- [ ] 在每次 owner/阅读器切换时递增 generation，并在所有异步返回落状态前校验。
- [ ] 打开时保存触发元素和滚动位置；关闭按钮或 Esc 退出时恢复焦点与位置。
- [ ] 运行集合前端聚焦测试与 `node --check`。

### Task 4: 单节解读页一键图解

**Files:**
- Modify: `src/web/templates/transcript.html`
- Create: `src/web/static/js/transcript-visual-reader.js`
- Test: `tests/unit/test_transcript_visual_reader_assets.py`
- Test: `tests/unit/test_visual_learning_reader_runtime.py`

- [ ] 写主路径契约：内容总结旁出现“一键图解/沉浸阅读”；在轻量 JS harness 中验证首次一键图解只请求 overview、显式“生成逐段图解”才请求 full_note，并验证 study reader generation race。
- [ ] 运行聚焦用例并确认失败。
- [ ] 在真实 `/view/{view_token}` 解读模板接入共享沉浸阅读器，文字复用现有 summary，图解复用 study visual API。
- [ ] 保存触发元素与滚动位置；Esc/关闭后恢复焦点与页面位置。
- [ ] 用 `viewToken + readerGeneration` 校验在途请求；关闭或切换会话后不渲染迟到结果。
- [ ] 运行 study 前端聚焦测试与 `node --check`。

### Task 5: 必要回归与真实体验验收

**Files:**
- No new files expected.

- [ ] 运行 Task 1–4 涉及的聚焦 pytest 套件，不扩展无关测试。
- [ ] 运行变更 Python 文件编译、两个页面 JS 语法检查和 `git diff --check`。
- [ ] 重启本地服务。
- [ ] 用真实“百里挑一之简历课”集合验收：无 front matter 噪音、文字/图解互斥、section 保持、唯一复习入口、Esc 后焦点与滚动位置恢复、控制台无错误。
- [ ] 用真实第 1 节解读页验收：一键 overview、文字/图解切换、显式 full_note 入口、Esc 恢复。
- [ ] 只读最终审阅 Critical/Important；不处理无关 Minor。

## 执行约束

- 当前工作区包含用户已有未提交修改，直接在当前工作区做外科式编辑，不创建隔离 worktree。
- 未经用户明确要求不提交、不暂存、不合并。
- 不新增依赖、不改数据库结构、不重写既有解读内容。

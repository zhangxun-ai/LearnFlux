# LearnFlux 正式上线 UI 加固实施计划

**目标：** 将当前 LearnFlux 从公开 Beta 水平提升到可正式上线的专业产品标准，优先消除已验证安全漏洞和核心移动端阻断，再完成认证、无障碍、状态、性能、PWA 与设计系统治理。

**实施原则：**

1. 严格按优先级逐项完成，不以大规模重写替代缺陷修复。
2. 每个任务先补失败契约或回归测试，再修改实现。
3. 每项完成后执行目标测试、相关单元测试、GitNexus 变更影响检查。
4. 不读取、打印、提交真实口令；不执行付费或破坏性外部调用。
5. 保持旧 URL 和现有 API 兼容；需要迁移时提供向后兼容路径。
6. 现有 `skill/`、`.gitignore` 等未提交改动不纳入本计划。

---

## 阶段 A：P0 上线阻断项

### Task A1：修复主页 URL 预览 DOM XSS 与候选质量

**状态：** 已完成（2026-09-01）

**修改范围：**

- `src/web/static/js/app.js`
- `tests/unit/test_home_url_input_security.py`

**实施内容：**

- 禁止将用户 URL 拼接进 `innerHTML`，改用 DOM API 和 `textContent`。
- 将动态 radio 与 label 正确关联。
- URL 解析只接受 HTTP/HTTPS，并返回浏览器规范化后的 URL。
- 对受支持平台的 `www.` 等价域名做候选去重。
- 隐藏内部“评分”数值，仅为首选候选显示“推荐”。
- 导出纯函数供 Node 单元测试验证，不在 Node 环境执行页面初始化。

**验收：**

- 恶意 URL-like 文本只能作为文本展示，不能创建 SVG/script/event DOM。
- 普通 YouTube `www` 链接只产生一个候选。
- 候选 radio 有可访问名称。
- `uv run --extra dev pytest tests/unit/test_home_url_input_security.py tests/unit/test_home_workbench_accessibility.py`

**完成记录：**

- 新增 3 个 URL 安全/无障碍回归测试，目标测试与主页相关测试共 26 项通过。
- 无害 DOM XSS 浏览器复测：事件标记未执行、SVG 节点为 0。
- YouTube 浏览器复测：候选数为 1、label 关联 `detected-url-0`、仅显示“推荐”。
- 完整单元套件结果：2435 通过、1 跳过；唯一失败是本任务前已存在的 `focus-studio.html` / `history.html` 导航生成漂移，与 A1 修改无关。

---

### Task A2：建立 Web 安全基线并迁移长期口令存储

**状态：** 已完成（2026-09-01）

**预期范围：**

- FastAPI 安全响应头中间件
- 认证路由/依赖与前端令牌适配层
- `app.js`、`settings.html`、`history.html`、`flywheel.html` 等令牌消费者
- 配置示例和安全回归测试

**实施内容：**

- 增加 CSP、`X-Content-Type-Options`、`Referrer-Policy`、`Permissions-Policy`、`frame-ancestors`。
- 收紧 CORS；默认只允许同源，跨域来源显式配置。
- 以短期 HttpOnly、Secure（HTTPS 时）、SameSite 会话 Cookie 替代长期管理口令 localStorage。
- 保留一次性旧令牌迁移，迁移成功后清理旧 key。
- 状态修改请求加入 CSRF 防护或严格同源校验。
- 审查其余动态 `innerHTML` sink；富文本仅允许经过现有 `nh3`/明确白名单的内容。

**验收：**

- localStorage/sessionStorage 中不存在明文或可逆管理口令。
- 未认证 API、过期会话、跨站请求均有确定状态码。
- 安全头集成测试通过；现有 API Token 客户端兼容性有明确迁移策略。

**完成记录：**

- 新增短期不透明 HttpOnly 会话、每会话 CSRF、精确同源校验、显式 CORS 白名单及安全响应头；Bearer Token 客户端保持兼容。
- 旧浏览器口令只在共享适配层读取一次，交换成功后清除全部敏感 localStorage/sessionStorage key；关键认证脚本已进入 PWA 预缓存并刷新缓存版本。
- 加固帖子洞察、主页状态、Focus Journal、结果页错误及远程链接等高风险 HTML sink；富文本仅消费服务端 `nh3` 合同或先转义再解析的受限 Markdown。
- source-file reveal 同时校验精确同源、客户端回环地址与 Host 回环地址，覆盖跨站请求和 DNS rebinding 回归。
- 受影响路由/安全/UI 契约 216 项通过；完整离线单元套件仅发现 3 个本次缓存版本/导航生成契约漂移，更新生成资源与契约后目标回归 13 项通过。
- 进程内会话仅适用于当前单进程运行模型；多 worker / 多副本的共享会话要求已写入 README，正式扩容前必须处理。

---

### Task A3：修复转录结果页移动端阅读布局

**状态：** 已完成（2026-09-01）

**修改范围：**

- `src/web/templates/transcript.html`
- `src/web/static/css/product-linear-system.css` 或独立结果页样式
- 结果页契约与浏览器回归测试

**实施内容：**

- 移除/覆盖移动端固定 `64px 80px` 卡片内边距。
- 将结果页样式放入稳定的页面作用域，避免后加载内联 CSS 覆盖。
- 处理超长标题、代码块、表格和目录在窄屏的重排。
- 保持桌面阅读版式不退化。

**验收：**

- 320/375/390px 下正文宽度合理，无逐字排版。
- 390px 下结果正文可用宽度不少于约 280px。
- 超长中文标题不会造成异常页面高度。
- 桌面端视觉截图无明显回归。

**完成记录：**

- 增加 `transcript-result-page` 页面作用域，并在晚于沉浸式纸张布局的位置提供最终移动断点，消除 `64px 80px` 对窄屏规则的覆盖。
- 320 / 375 / 390px 固定离线 fixture 的 Chromium 计算宽度分别为 288 / 335 / 350px，均无文档级横向溢出；未调用业务或云端 API。
- 超长标题可自然换行；表格和代码块局部横向滚动；图片/视频/SVG 自适应；操作按钮达到 44px；移动目录按钮缩至 52px 并适配 safe area。
- 1440px 离线截图正文宽度为 798px，标题、元数据、操作区和正文重新对齐；相关模板/路由/UI 回归 99 项通过。

---

### Task A4：统一首次使用认证与恢复路径

**状态：** 已完成（2026-09-01）

**实施内容：**

- 建立全局 AuthGate/会话状态组件。
- 单篇、文件、文字、系列、阅读、复盘、历史、Flywheel 共用认证入口。
- 删除已不存在的“高级设置”引用。
- 未认证时在执行前给出“连接管理会话”主操作，并保留输入与返回 URL。
- 全站统一“管理口令”术语，技术说明中再标注 Bearer Token。

**验收：**

- 新浏览器首次进入任一受保护功能都不会先发起注定失败的请求。
- 用户完成认证后可返回原操作，输入内容不丢失。
- 401、403、过期会话与网络错误有不同反馈。

**完成记录：**

- 新增共享、可访问且适配移动端/暗色模式的 AuthGate，统一提供短期 HttpOnly 会话探测、内联首次使用入口和按操作弹出的认证对话框。
- 首页单篇/文件/文字、系列、阅读、复盘、边播边学、图解生成、历史、Flywheel 与结果页受保护操作均改为认证后恢复；未认证初始化不再请求受保护数据。
- 修复会话探测期间提前暴露占位 Bearer Token 的竞态；旧口令只迁移一次，错误口令、会话过期、403 安全校验和网络错误分别提供明确反馈。
- PWA 缓存更新为 `learnflux-pwa-20260901-auth-gate-workspaces`，确保共享认证脚本和样式更新到现有安装。
- 390px 本地 Chromium 固定 fixture 验证：认证前受保护请求为 0，错误口令反馈正确，认证后原正文输入保留，仅加载预期历史 fixture；会话 Cookie 为 HttpOnly、SameSite=Strict，敏感 Web Storage key 均为空。
- A4 相关离线回归 80 项通过；完整 `tests/unit` 套件通过（1 项跳过）。全程未调用云端转录、LLM、TikHub 或其他付费 API。

---

## 阶段 B：P1 产品质量门槛

### Task B1：暗色模式和 WCAG AA 对比度

**状态：** 已完成（2026-09-01）

- 建立语义色契约测试。
- 修复暗色亮蓝按钮、系列学习活动标签、阅读错误条、侧栏分组文字。
- 保留 Editorial/Focus 子主题，但交互色使用统一 Token。

**完成记录：**

- 新增 `tests/unit/test_product_color_contrast.py`，按 WCAG 2.x 相对亮度算法校验亮/暗主题正文、次级文字、侧栏分组、主按钮及 info/success/warning/danger 语义色，普通文字门槛为 4.5:1。
- 主按钮前景统一为 `--product-on-accent`，暗色亮蓝按钮由白字 2.39:1 提升为深色字；侧栏浅色分组文字由 4.15:1 提升至 4.74:1。
- 系列页活动和摘要状态改用语义 Token，暗色计算对比度为 6.16–8.02:1；阅读错误条改用 danger 前景/背景，仅错误状态显示危险色，对比度为 6.16:1。
- 修复系列页暗色激活标签的硬编码白色表面，并将 PWA 缓存更新为 `learnflux-pwa-20260901-wcag-colors`。
- 本地 Chromium 固定 fixture 验证主按钮最低 5.66:1，相关页面级回归 115 项通过，完整 `tests/unit` 套件通过（1 项跳过）；未调用任何付费 API。

### Task B2：表单、Tabs 与键盘无障碍

**状态：** 已完成（2026-09-01）

- 补齐 Flywheel、历史、帖子、写作控件的程序化标签。
- 为 Study、Visual、Flywheel 添加完整 tab/tablist/tabpanel、`aria-controls` 和方向键交互。
- 修复 Visual Learning 的 skip link 与 `<base>` 冲突。
- 将关键移动触控目标统一到 44px 产品规范。

**完成记录：**

- 新增 `tests/unit/test_workspace_accessibility.py` 的 9 项失败优先契约，覆盖重点表单可访问名称、完整 Tabs 关系、方向键/Home/End 漫游焦点、动态历史控件、Skip Link 与 44px 触控目标。
- Flywheel、历史、帖子洞察和 Focus Studio 的 URL、筛选器、编辑区、提示词与动态复选框均获得程序化名称；历史频道选择由仅鼠标 `<div>` 改为原生按钮，并同步 `aria-expanded`。
- Study 双组 Tabs、Visual 来源 Tabs、Flywheel 五视图和 Focus Journal 均补齐 `tablist`/`tab`/`tabpanel`、`aria-controls`/`aria-labelledby`、单一漫游 `tabindex`、`aria-selected` 与 `hidden` 状态同步。
- Visual Learning 移除路由注入的 `<base href="/static/">`，静态资源改用 `/static/...` 绝对路径；Skip Link 保持在 `/visual-learning#main-content` 并聚焦主内容。
- App Shell 移动菜单、图标按钮和移动导航项统一为至少 44px；PWA 缓存更新为 `learnflux-pwa-20260901-accessibility-tabs`，并同步共享产品导航。
- 本地 390px Chromium 固定 fixture 验证 Visual、Study、Flywheel 的键盘切换、焦点、面板可见性和 Skip Link，菜单实测 44×44px、导航项高度 44px；相关 109 项回归通过。
- 完整 `tests/unit` 共 2480 项：2479 项通过、1 项跳过；GitNexus 对 Visual 路由和工作台 Tab 变更评估为 LOW。全程未调用云端转录、LLM、TikHub 或其他付费 API。

### Task B3：移动端与沉浸模式专项

- 修复 Flywheel 五标签逐字竖排。
- 优化设置页底部保存栏、键盘遮挡和 safe area。
- Focus Studio 默认提供沉浸模式，避免侧栏破坏写作空间。
- 自托管或非阻塞加载写作字体，消除冷启动完整侧栏闪烁。

### Task B4：任务反馈、上传与信任文案

- 为大文件上传加入进度、取消、失败恢复；评估分片/断点续传。
- 统一本地/云端默认策略；默认本地或要求显式选择。
- 在入口说明上传位置、报价确认时机和费用上限。
- 统一加载、处理中、等待确认、成功、失败、取消状态组件。

### Task B5：错误语义与 HTTP 状态

- `/view/{invalid_token}` 返回 404。
- 任务失败、取消、文件已清理映射到明确领域状态。
- 去除复盘/阅读重复错误提示，为错误状态提供设置、重试或返回动作。
- 设置页未认证时明确显示“未连接”，禁止伪装成已加载配置。

### Task B6：资源传输与 PWA 可靠性

- 增加 gzip/Brotli（应用或推荐反向代理层）。
- 对版本化静态资源设置长期 immutable 缓存；HTML 保持 no-cache/no-store。
- 生成精确版本化 PWA precache manifest。
- 覆盖 `/study`、`/review`、`/reading`、`/visual-learning` 等承诺离线页面。
- 统一 Manifest 品牌色并增加离线 fallback。

### Task B7：自动化 UI 上线门禁

- 引入 Playwright 浏览器测试与固定 fixture。
- 视口：320、390、768、1024、1440；主题：亮/暗。
- 状态：未认证、空、加载、成功、失败、超长标题、长正文、云端报价。
- 集成 axe-core；阻止 serious/critical 问题。
- 增加 Lighthouse 性能预算与 PWA 冷离线测试。

---

## 阶段 C：P2 架构与产品一致性

### Task C1：收敛设计系统与 CSS 级联

- 建立 `tokens → shell → components → pages → utilities` CSS Layers。
- 消除高风险全局 `.container`、`.header` 等选择器。
- 抽取 Button、Field、Tabs、Dialog、Status、EmptyState、AuthGate。
- 逐步迁移大型模板内联样式，不进行无验收标准的全量重写。

### Task C2：修复 App Shell 状态机

- 合并 `expanded`、`rail`、`floating` 为单一状态模型。
- 修复 floating 偏好刷新丢失、重复 toggle、无标签按钮和仅鼠标 resize。
- 增加桌面缩放、移动切换、键盘和状态持久化测试。

### Task C3：信息架构、路由与命名

- 统一“边播边学 / 本地视频学习 / 本地学习”。
- 增加产品工作台首页；产品壳 Logo 返回工作台，营销页保持独立。
- 为 `/add_task_by_web`、`/static/history.html`、`/static/focus-studio.html` 提供干净路由和兼容重定向。
- 将管理员系统配置与普通用户偏好分区。

### Task C4：前端模块化与体积治理

- 拆分 `collections.js` 等大型页面脚本。
- 将共享导航继续保持单一数据源，并增加生成漂移 CI。
- 清理兼容 Token、重复断点、硬编码颜色和无效旧样式。

---

## 全局发布门槛

所有任务完成后至少满足：

- 安全：已验证 DOM XSS 不可复现；无长期管理口令 Web Storage；CSP 可执行。
- 响应式：320–1440px 核心流程可用，无核心内容异常窄化。
- 无障碍：axe serious/critical 为 0，核心流程可全键盘操作，正文与 UI 对比度达到 WCAG AA。
- 状态：未认证、空、加载、成功、失败、取消、过期均有可恢复动作和正确 HTTP 状态。
- 性能：Slow 4G 下 LCP ≤ 2.5s、CLS ≤ 0.1、INP ≤ 200ms（以 CI 实测为准）。
- PWA：所有承诺离线页面冷启动可用；否则移除对应离线承诺。
- 回归：`uv run --extra dev pytest tests/unit` 和新增浏览器门禁全部通过。

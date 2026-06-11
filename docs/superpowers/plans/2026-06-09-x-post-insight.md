# X / Twitter 帖子精华提炼 实现计划

> **For agentic workers:** 用 superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 勾选跟踪。

**Goal:** 输入一条 X 推文链接，自动抓取作者完整 thread（正文）+ 高赞回复（评论区），LLM 审核分析提炼，输出含「可信度/存疑」判断的精华，并在交互良好的结果页呈现。

**Architecture:** 新建独立的轻量「帖子洞察」流程，**不改视频管线**。复用叶子单元：`generate_comment_insight`（接受自定义 analyzer + summary_text）、`selector`、LLM 客户端、Markdown→HTML、`task_progress`、`base.html`。X 数据经 TikHub 抓取（GenericDownloader 已具备 `make_api_request`），回复走 `comments/fetcher.py` 新增 twitter 分支，正文 thread 由新 `TwitterThreadFetcher` 抓取并作为 `summary_text` 注入。

**Tech Stack:** Python 3.12 / FastAPI / Jinja2 模板 / TikHub API / 现有 LLM 客户端 / pytest（.venv）。

> 参考 spec：`docs/superpowers/specs/2026-06-09-x-post-insight-design.md`
> 全程：先确认 `.venv` 激活；测试 console 输出纯英文、无 emoji/中文；测试置于 `tests/`。

---

## 📍 进度（2026-06-09）

- ✅ **阶段 0**：TikHub key 已配；端点/字段实测锁定。
- ✅ **阶段 1**：url_parser twitter 支持（含 netflix/react 误判防护）；`TwitterPostFetcher`（按作者切分 thread/回复）。
- ✅ **阶段 2**：`PostInsightAnalyzer`（可信度结构化 prompt，空回复可降级）。
- ✅ **阶段 3**：`generate_post_insight` 服务。
- ✅ **阶段 4**：`/post` 页 + `POST /api/post-insight`（线程池跑分析、复用 `verify_token` 鉴权）；结果页继承 base.html，可信度卡片视觉聚焦 + 标签转彩色徽章 + 一键复制 + 原文折叠 + 加载分阶段 + 空/错误态 + 响应式；首页加入口链接。`build_insight_sections` 纯函数拆段 + 徽章。
- ✅ **阶段 5**：47 单测全绿（含路由展示逻辑），零回归；`py_compile` 全通过（venv 无 mypy/pyright）；scratch/预览图清理；冒烟服务停止。
- ✅ **真实端到端验证**：(a) 服务层 Naval thread 经真实 TikHub + 真实 LLM 产五段结构化精华；(b) Web 层起服务实测：`GET /post`=200、无 token=401、带 token=200 ok 五段+徽章；(c) 浏览器截图确认结果页视觉（可信度卡为焦点）。
- 🔎 **实测发现的 v1 限制**：`fetch_post_comments` 对作者 thread 首页返回的是作者自接楼（→正文），第三方回复可能不在首页；要拿全回复需用 `cursor` 翻页。v1 先不翻页（正文+可信度已可用），翻页列为后续增强。
- ⏭️ **后续增强**：回复 `cursor` 翻页；引用转推纳入；小红书图文 / 公众号沿用同一管线接入（新增对应 fetcher + 平台识别即可）。

---

## 阶段 0：执行前核对（消除唯一风险）

- [ ] **0.1 确认 TikHub key 已配置（不打印密钥）**
  Run: `.venv/bin/python -c "from src.video_transcript_api.utils.logging import load_config; print('tikhub_key_set=', bool(load_config().get('tikhub',{}).get('api_key') and 'your-' not in str(load_config().get('tikhub',{}).get('api_key'))))"`
  预期：`tikhub_key_set= True`。若 True，则 0.2 实测真实响应形状；若 False，跳过实测、以文档形状写 fixture，并在执行小结里标注"未实测"。

- [ ] **0.2 实测 TikHub Twitter 端点形状（仅当 key 已配）**
  写一次性脚本 `tests/scratch_tikhub_twitter.py`（用后即删，不进 git）：用一条公开推文链接，调用候选端点（`/api/v1/twitter/web/fetch_tweet_detail`、`/api/v1/twitter/web/fetch_user_tweet_replies` 或文档实际端点），**只 print 响应顶层结构与示例条目字段名**（不 print 密钥）。据此锁定阶段 1 的端点名、参数名、字段别名与 fixture。
  > 端点/字段名以实测为准；下方代码中的端点名为占位，0.2 后用真实值校正。

---

## 阶段 1：X 数据入口（解析 + 正文/回复抓取）

> **✅ 阶段 0 实测结论（已锁定，2026-06-09）：**
> - 端点：`GET /api/v1/twitter/web/fetch_post_comments`，参数 `tweet_id`（必填）、`cursor`。一个端点同时返回主推文与会话链。
> - 主推文 = `data` 顶层：`text`(兜底 `display_text`)、`author.screen_name`、`author.name`、`likes`、`replies`、`id`、`conversation_id`。
> - 会话链 = `data.thread[]`，每条：`text`/`display_text`、`likes`、`replies`、`author.screen_name`、`id`、`created_at`、`views`。翻页 `data.cursor`。
> - **分离规则（实测验证）**：`thread` 中 `author.screen_name == data.author.screen_name` 的条目 = 作者自接 thread（→正文）；其余 = 他人回复（→评论区）。Naval 长 thread：30/30 为作者本人；tweet 20：0 为作者、其余为回复。
> - **设计简化**：原 Task 1.2（独立 thread 抓取器）+ Task 1.3（评论分支）合并为单个 `TwitterPostFetcher.fetch()`，一次调用 → 按作者切分返回 `(ThreadContent, list[CommentItem])`。不依赖 `fetch_tweet_detail`。
> - 字段映射直接构造 `CommentItem`（twitter 专用、~6 行、清晰），**不改**视频路径的 `_normalize_comment`，零回归。

### Task 1.1：url_parser 支持 twitter

**Files:**
- Modify: `src/video_transcript_api/utils/url_parser.py`（`PATTERNS` 加 `twitter`；`parse()` 平台判定）
- Test: `tests/unit/test_url_parser.py`

- [ ] **Step 1: 写失败测试**
```python
def test_parse_twitter_status_url():
    parsed = URLParser().parse("https://x.com/elonmusk/status/1790000000000000000")
    assert parsed.platform == "twitter"
    assert parsed.video_id == "1790000000000000000"

def test_parse_twitter_legacy_domain():
    parsed = URLParser().parse("https://twitter.com/jack/status/20?s=20")
    assert parsed.platform == "twitter"
    assert parsed.video_id == "20"
```
- [ ] **Step 2: 跑测试确认失败** — `.venv/bin/pytest tests/unit/test_url_parser.py -k twitter -v` 预期 FAIL。
- [ ] **Step 3: 最小实现** — 在 `PATTERNS` 增：
```python
'twitter': [
    r'(?:x|twitter)\.com/[^/]+/status/(\d+)',
],
```
确认 `parse()` 的平台循环会命中 twitter（沿用现有 youtube/douyin 同样的提取路径）；短链（t.co）由现有 HEAD 解析先展开再匹配，无需额外代码。
- [ ] **Step 4: 跑测试确认通过** — 同上命令，预期 PASS。
- [ ] **Step 5: commit** — `git add -A && git commit -m "feat(url-parser): recognize twitter/x status links"`（**仅当用户要求提交**；否则跳过 commit，连续推进）。

### Task 1.2：TwitterThreadFetcher（抓作者 thread 作为正文）

**Files:**
- Create: `src/video_transcript_api/comments/twitter_thread.py`
- Test: `tests/unit/test_twitter_thread_fetcher.py`

接口：
```python
@dataclass(frozen=True)
class ThreadContent:
    title: str        # 取首条推文首行（截断）
    author: str       # @handle 或显示名
    text: str         # 作者连续自接 thread 合并文本

class TwitterThreadFetcher:
    def __init__(self, downloader_factory=create_downloader): ...
    def fetch_thread(self, url: str, tweet_id: str) -> ThreadContent: ...
```
- [ ] **Step 1: 写失败测试**（fixture 驱动，依据 0.2 实测形状；下例为占位结构，0.2 后校正字段名）
```python
class _FakeDownloader:
    def __init__(self, response): self._r = response
    def make_api_request(self, endpoint, params=None): return self._r

def test_fetch_thread_merges_author_self_replies():
    resp = {  # 占位：以 0.2 实测为准
        "data": {"tweets": [
            {"id_str": "1", "full_text": "主张第一段", "user": {"screen_name": "alice"}, "in_reply_to_user_id_str": None},
            {"id_str": "2", "full_text": "作者自己接的第二段", "user": {"screen_name": "alice"}, "in_reply_to_status_id_str": "1"},
            {"id_str": "9", "full_text": "别人插的楼", "user": {"screen_name": "bob"}},
        ]}
    }
    fetcher = TwitterThreadFetcher(downloader_factory=lambda url: _FakeDownloader(resp))
    out = fetcher.fetch_thread("https://x.com/alice/status/1", "1")
    assert out.author in ("alice", "@alice")
    assert "主张第一段" in out.text and "作者自己接的第二段" in out.text
    assert "别人插的楼" not in out.text   # 只取作者连续自接
    assert out.title  # 非空
```
- [ ] **Step 2: 跑测试确认失败** — `.venv/bin/pytest tests/unit/test_twitter_thread_fetcher.py -v` 预期 FAIL（模块不存在）。
- [ ] **Step 3: 实现** — 调 tweet-detail 端点（0.2 实测名），从对话里筛出 root 作者、按回复链取其连续自接推文，合并 `full_text`；多字段兜底取 author/screen_name；title 取首条首行截断。校验响应 `code in (None,0,200)`，异常抛 `ValueError`，记录日志。
- [ ] **Step 4: 跑测试确认通过。**
- [ ] **Step 5: commit**（条件同上）。

### Task 1.3：comments/fetcher.py 增 twitter 回复分支 + 字段别名

**Files:**
- Modify: `src/video_transcript_api/comments/fetcher.py`（`_build_request` 加 twitter；`_normalize_comment` 补 twitter 别名）
- Test: `tests/unit/test_comment_fetcher.py`（已存在，追加用例）

- [ ] **Step 1: 写失败测试**
```python
def test_build_request_supports_twitter():
    f = TikHubCommentFetcher()
    endpoint, params = f._build_request("twitter", "1790", "https://x.com/a/status/1790", 50)
    assert "twitter" in endpoint
    assert params  # 含 tweet_id/cursor 等

def test_normalize_twitter_comment_aliases():
    f = TikHubCommentFetcher()
    item = f._normalize_comment(
        {"full_text": "有理有据的反驳", "favorite_count": 321, "reply_count": 4,
         "user": {"screen_name": "carol"}, "id_str": "55"}, 0)
    assert item.text == "有理有据的反驳"
    assert item.like_count == 321
    assert item.user_nickname in ("carol", "@carol")
    assert item.comment_id == "55"
```
- [ ] **Step 2: 跑测试确认失败** — `.venv/bin/pytest tests/unit/test_comment_fetcher.py -k twitter -v` 预期 FAIL。
- [ ] **Step 3: 实现** — `_build_request` 加：
```python
if platform == "twitter":
    return (
        "/api/v1/twitter/web/fetch_tweet_comments",  # 0.2 实测校正
        {"tweet_id": media_id, "cursor": "", "count": count},
    )
```
`_normalize_comment` 的 `_first_text` keys 增 `"full_text"`；`_first_int` like keys 增 `"favorite_count"`；nickname 取 `user.screen_name` 兜底（已有 user.nickname/name，补 screen_name）。`_extract_comment_list` 的 key 候选已含通用项，必要时加 twitter 专有键。
- [ ] **Step 4: 跑测试确认通过。**
- [ ] **Step 5: commit**（条件同上）。

---

## 阶段 2：帖子分析器（核心价值：可信度/存疑）

### Task 2.1：PostInsightAnalyzer + 帖子 prompt

**Files:**
- Create: `src/video_transcript_api/comments/post_analyzer.py`
- Test: `tests/unit/test_post_analyzer.py`

设计：复用 `format_comments_for_llm` 与 LLM 客户端 `call(...)` 约定（见 analyzer.py），**不改** `CommentInsightAnalyzer`。新 prompt 固定输出 spec §4 结构。
```python
POST_INSIGHT_SYSTEM_PROMPT = """你是专业的社交帖子审核分析助手。
分析一条 X 帖子的作者正文(thread)与高赞回复，提炼对读者有价值的精华，并显式做可信度判断。
要求：不臆测；信息不足要明说；输出中文 Markdown。
固定输出结构：
## 正文核心主张
## 可信度与存疑点
（逐条标注：[共识/可信] [单方面断言] [需外部核实] [回复区有反驳]）
## 评论区：共识 vs 争议
## 代表性高赞回复
## 对你的可行动启发
"""

class PostInsightAnalyzer:
    def __init__(self, llm_client, model, reasoning_effort=None): ...
    def analyze(self, title, author, summary_text, comments) -> str | None:
        # 与 CommentInsightAnalyzer.analyze 同签名，便于直接传给 generate_comment_insight
```
- [ ] **Step 1: 写失败测试**（mock llm_client，断言 system_prompt 用了帖子版、user_prompt 含正文与回复、空回复返回 None 之外仍可处理正文——见下）
```python
class _FakeLLM:
    def __init__(self): self.last=None
    def call(self, **kw): self.last=kw; import types; return types.SimpleNamespace(text="## 正文核心主张\nx")

def test_post_analyzer_uses_post_prompt_and_includes_thread():
    llm=_FakeLLM()
    a=PostInsightAnalyzer(llm, model="m")
    out=a.analyze(title="t", author="alice", summary_text="作者thread正文", comments=[CommentItem(text="高赞反驳", like_count=10, platform_rank=0)])
    assert "社交帖子" in llm.last["system_prompt"]
    assert "作者thread正文" in llm.last["user_prompt"]
    assert out.startswith("## 正文核心主张")
```
- [ ] **Step 2–4:** 跑失败 → 实现 → 跑通。`.venv/bin/pytest tests/unit/test_post_analyzer.py -v`。
- [ ] **Step 5: commit**（条件同上）。

> 注：thread 无回复时仍要能产出"正文+可信度"分析。因 `generate_comment_insight` 在无评论时返回 None，阶段 3 的 service 要在"无回复"分支单独调用 `PostInsightAnalyzer.analyze(..., comments=[])` 的兜底路径——为此给 analyzer 增加 `comments=[]` 也能基于正文输出的能力（修改：去掉 `if not comments: return None`，改为允许仅正文分析）。对应增测：
```python
def test_post_analyzer_works_without_comments():
    llm=_FakeLLM(); a=PostInsightAnalyzer(llm, model="m")
    out=a.analyze(title="t", author="alice", summary_text="只有正文", comments=[])
    assert out  # 仍产出
    assert "只有正文" in llm.last["user_prompt"]
```

---

## 阶段 3：帖子洞察服务（编排）

### Task 3.1：post_insight 服务

**Files:**
- Create: `src/video_transcript_api/api/services/post_insight.py`
- Test: `tests/unit/test_post_insight_service.py`

接口：
```python
@dataclass
class PostInsightResult:
    platform: str
    source_url: str
    author: str
    title: str
    thread_text: str
    insight_markdown: str
    comment_samples: list[dict]
    fetched_comment_count: int

def generate_post_insight(
    url: str, *, llm_client, model, reasoning_effort=None,
    thread_fetcher=None, comment_insight_runner=generate_comment_insight,
) -> PostInsightResult: ...
```
编排：parse(url) → 仅支持 platform=="twitter"（否则 ValueError）→ `thread = TwitterThreadFetcher().fetch_thread(...)` → 调 `comment_insight_runner(url, platform="twitter", media_id=tweet_id, title=thread.title, author=thread.author, summary_text=thread.text, analyzer=PostInsightAnalyzer(...))`。
- 若回复洞察返回非 None：`insight_markdown = result["insight_text"]`，`comment_samples = result["samples"]`。
- 若返回 None（无回复）：回退直接 `PostInsightAnalyzer.analyze(title, author, summary_text=thread.text, comments=[])`，samples=[]。
- [ ] **Step 1: 写失败测试**（注入 fake thread_fetcher + fake runner + fake analyzer/llm，断言两条分支都产出 `insight_markdown`，且无回复时 `fetched_comment_count==0`）。
- [ ] **Step 2–4:** 跑失败 → 实现 → 跑通。`.venv/bin/pytest tests/unit/test_post_insight_service.py -v`。
- [ ] **Step 5: commit**（条件同上）。

---

## 阶段 4：Web 入口 + 结果页（交互体验硬要求）

> UI 标记在执行时对照 `src/web/templates/base.html`、`transcript.html`、`styles.css` 现有风格编写并抬高；本计划给出结构与交互契约 + 验收点，不预写每行 HTML（避免与执行重复且偏离真实模板）。

### Task 4.1：提交入口 + 任务/进度

**Files:**
- Modify: `src/video_transcript_api/api/routes/tasks.py`（新增受理 X 链接的提交端点或在现有提交里识别 twitter 走帖子流程）
- Modify: `src/video_transcript_api/utils/task_progress.py`（加帖子流程阶段，如 `post_fetch`/`post_insight` 百分比与中文描述）
- Test: `tests/unit/test_post_insight_routes.py`

- [ ] 受理 twitter 链接 → 后台任务调用 `generate_post_insight` → 进度经 `task_progress` 上报（抓取→分析）。
- [ ] 测试：提交 twitter 链接返回任务 id；非法链接返回明确错误；用 fake service 断言落地结果结构。
- [ ] 跑测试 → 通过。

### Task 4.2：结果页模板 + 样式（交互契约）

**Files:**
- Create: `src/web/templates/post_insight.html`（extends `base.html`）
- Modify: `src/web/static/css/styles.css`（新增帖子洞察区样式；不动既有规则）
- Modify: `src/video_transcript_api/api/routes/views.py`（渲染路由 + `render_markdown_to_html` 复用）

交互验收点（逐条可见）：
- [ ] **来源头部**：作者、原推链接（`target=_blank rel=noopener`）、抓取时间、回复抓取数。
- [ ] **可信度区视觉优先**：[共识/可信]✓ [单方面断言]⚠ [需核实]❗ [有反驳]🔁 用色彩/徽章卡片化，置于显著位置。
- [ ] **正文/原文分离**：默认显示"核心主张"，原 thread 折叠（`<details>` 或 JS 折叠）。
- [ ] **评论区精华**：共识/争议分栏；代表性回复带 @作者 与点赞数。
- [ ] **一键复制**：复制整篇精华按钮（复用/参考 app.js 既有交互）。
- [ ] **加载/进度**：复用 `processing.html` 思路展示抓取+分析进度，不空白。
- [ ] **响应式**：窄屏（≤480px）可读，卡片纵向堆叠。
- [ ] **空/异常态**：无回复→"无可用回复，仅基于正文分析"；受保护/已删除/失败→明确文案，提供"返回/重试"。

### Task 4.3：路由注册与冒烟

**Files:**
- Modify: `src/video_transcript_api/api/app.py`（如需注册新路由/模板）

- [ ] 启动应用，提交一条真实公开推文链接，肉眼核对结果页满足 4.2 全部验收点（桌面 + 窄屏）。
- [ ] 截图留档。

---

## 阶段 5：集成验证与收尾

- [ ] **5.1 端到端测试（fakes，无网络）**：`tests/features/test_post_insight_e2e.py` —— 提交 twitter 链接 → 经 fake thread/comment/LLM → 得到含五段结构的 `insight_markdown` 与样本。
- [ ] **5.2 类型检查**：按项目既有方式（如 `mypy` 或 `pyright`，先查项目用哪个）对改动模块跑一遍，零新增错误。
- [ ] **5.3 跑相关测试子集**（非全量）：`.venv/bin/pytest tests/unit/test_url_parser.py tests/unit/test_comment_fetcher.py tests/unit/test_twitter_thread_fetcher.py tests/unit/test_post_analyzer.py tests/unit/test_post_insight_service.py -v` 全绿。
- [ ] **5.4 删除 0.2 的 scratch 脚本**；确认 `.gitignore` 不漏临时/data 产物。
- [ ] **5.5 执行小结**：列出改了什么、验证了什么、TikHub 是否实测、已知限制（v1 不含 quote tweet / 仅 X）。

---

## 风险与回归保护
- 视频链路（transcription/llm_ops/views 的视频路径）**不修改**，仅新增并联流程 → 零回归。
- TikHub 字段名以阶段 0.2 实测锁定；归一化多字段兜底降低脆弱性。
- thread 组装只取作者连续自接，规则明确，复杂对话树留作后续增强。

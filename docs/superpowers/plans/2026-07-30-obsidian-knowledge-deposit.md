# LearnFlux Obsidian Knowledge Deposit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在单篇结果页和合集页提供手动、可预览、可增量重试的 Obsidian 知识沉淀能力，把原材料和 AI 解读分别写入镜像的 `raw` 与 `processed` 目录。

**Architecture:** 保留现有 Study 逐字稿/个人笔记同步不变，新增独立的 knowledge source resolver、repository、Markdown renderer、category recommender 和 sync service。单篇缓存与合集服务先被适配为统一 `KnowledgeItem`，再由同步服务生成无副作用预览；apply 在锁内复核哈希前置条件后写盘并记录同步基线。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、SQLite、Jinja2、原生 JavaScript/CSS、pytest、现有 LLM 与 Obsidian path/atomic-write helpers。

---

## 实施约束

- 设计依据：`docs/superpowers/specs/2026-07-30-obsidian-knowledge-deposit-design.md`
- 开始前使用 `superpowers:systematic-debugging` 复核当前入口缺失的证据；实现各任务使用 `superpowers:test-driven-development`；宣告完成前使用 `superpowers:verification-before-completion`。
- 当前工作区已有用户需要保留的未提交修改：
  - `src/web/static/js/app.js`
  - `tests/unit/test_home_page.py`
- 不还原、覆盖或顺手重写上述修改。
- 未经用户明确授权，不执行 `git commit`、`git push`、部署或真实 Vault 写入。
- 自动化测试只使用 `tmp_path` 下的临时 Vault 和 SQLite。
- 每次修改共享函数或路由前，使用 GitNexus `context` + upstream `impact`；完成后使用 `detect_changes`。

## 文件结构

### 新建

- `src/video_transcript_api/obsidian/knowledge_models.py`：统一内容、预览、前置条件和结果数据结构。
- `src/video_transcript_api/obsidian/knowledge_repository.py`：新绑定与同步基线的 SQLite 持久化。
- `src/video_transcript_api/obsidian/knowledge_markdown.py`：raw/analysis frontmatter 与 Markdown 渲染。
- `src/video_transcript_api/obsidian/knowledge_sources.py`：单篇缓存、合集分集到 `KnowledgeItem` 的适配。
- `src/video_transcript_api/obsidian/knowledge_categories.py`：一级分类列举、LLM 推荐与回退。
- `src/video_transcript_api/obsidian/knowledge_service.py`：预览、前置条件复核、单项/批量写盘。
- `src/web/static/js/obsidian-knowledge.js`：单篇知识沉淀弹窗交互。
- `src/web/static/css/obsidian-knowledge.css`：单篇和可复用弹窗样式。
- `tests/unit/test_obsidian_knowledge_repository.py`
- `tests/unit/test_obsidian_knowledge_markdown.py`
- `tests/unit/test_obsidian_knowledge_sources.py`
- `tests/unit/test_obsidian_knowledge_categories.py`
- `tests/unit/test_obsidian_knowledge_service.py`
- `tests/unit/test_obsidian_knowledge_routes.py`
- `tests/unit/test_obsidian_knowledge_frontend.py`

### 修改

- `src/video_transcript_api/obsidian/paths.py`：增加一级分类列举、受管知识文件恢复和安全镜像目录 helper。
- `src/video_transcript_api/api/routes/obsidian.py`：增加 knowledge API 模型、依赖工厂和路由。
- `src/web/templates/transcript.html`：挂载单篇入口、弹窗和静态资源。
- `src/web/static/collections.html`：挂载合集入口和批量选择弹窗。
- `src/web/static/js/collections.js`：合集推荐、预览、确认和逐项结果交互。
- `src/web/static/css/collections.css`：合集同步弹窗和状态样式。
- `config/config.example.jsonc`：记录可选 `knowledge_raw_root`、`knowledge_processed_root` 默认值。
- `tests/unit/test_obsidian_sync.py`：更新示例配置断言，继续锁定空 Vault 占位符。
- `tests/unit/test_obsidian_paths.py`：覆盖一级分类与镜像路径安全。
- `tests/unit/test_home_page.py`：只在现有改动基础上增加必要断言，不覆盖当前语法回归测试。

## Task 1：建立知识项和新仓储契约

**Files:**

- Create: `src/video_transcript_api/obsidian/knowledge_models.py`
- Create: `src/video_transcript_api/obsidian/knowledge_repository.py`
- Test: `tests/unit/test_obsidian_knowledge_repository.py`

- [x] **Step 1: 用失败测试固定绑定与同步基线**

测试至少覆盖：

```python
def test_collection_binding_is_shared_by_all_sources_and_revision_guarded(tmp_path):
    repo = ObsidianKnowledgeRepository(tmp_path / "study.db")
    created = repo.save_binding(
        owner_user_id="u1",
        scope_type="collection",
        scope_id="c1",
        vault_id="v1",
        category="屠龙胭脂井",
        collection_directory="屠龙胭脂井-创业 100 件事",
        expected_revision=None,
    )
    assert created["revision"] == 1
    assert repo.get_binding("u1", "collection", "c1", "v1")["id"] == created["id"]
```

以及：

- revision 不一致抛出专用冲突；
- 单篇和合集绑定隔离；
- 合集重试后新 `view_token` 复用同一 `context_key`、路径和哈希；
- 改分类只清空该 scope 的新知识同步基线，不改旧 Study 表；
- 在已有本地数据库上重复初始化幂等。

- [x] **Step 2: 运行测试并确认按预期失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_repository.py -q
```

Expected: FAIL，原因是模块或类型尚不存在。

- [x] **Step 3: 定义小而稳定的数据结构**

`knowledge_models.py` 至少包含：

```python
@dataclass(frozen=True)
class KnowledgeItem:
    owner_user_id: str
    view_token: str
    title: str
    raw_content: str
    analysis_content: str
    source_kind: str
    source_access: str
    collection_id: str = ""
    source_id: str = ""
    collection_title: str = ""
    collection_creator: str = ""

    @property
    def context_key(self) -> str:
        return build_study_context_key(
            self.view_token, self.collection_id, self.source_id
        )
```

并定义 `KnowledgeDocumentPreview`、`KnowledgeItemPreview`、`KnowledgeApplyPrecondition`。字段按设计文档第 10 节，不在模型中保存 Vault 绝对路径。apply 请求还必须携带预览时的 binding revision，并在读取文件前校验绑定未变化。

- [x] **Step 4: 实现独立仓储**

`knowledge_repository.py`：

- 接受现有数据库路径，但自己创建 `obsidian_knowledge_bindings` 与 `obsidian_knowledge_sync`；
- 复用 `build_study_context_key`；
- 公开 `get_binding`、`save_binding`、`get_sync_state`、`update_sync_state`；
- 使用参数化 SQL；
- 定义 `KnowledgeRevisionConflict`；
- 目录绑定变化时只清空新表中对应 scope 的路径和哈希。

- [x] **Step 5: 运行仓储测试**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_repository.py -q
```

Expected: PASS。

## Task 2：实现 raw / processed Markdown 契约

**Files:**

- Create: `src/video_transcript_api/obsidian/knowledge_markdown.py`
- Test: `tests/unit/test_obsidian_knowledge_markdown.py`

- [x] **Step 1: 写 renderer 失败测试**

覆盖：

- 单篇 raw frontmatter 省略合集字段；
- 合集 raw 包含稳定 collection/source identity；
- analysis 包含指向 raw 的 `raw_note` wikilink；
- `source_access` 同时支持 URL、本地路径和 LearnFlux 路由；
- hash 排除 `synced_at`，相同正文重复渲染保持相同 managed hash；
- frontmatter `content_hash` 只表示规范化正文哈希，不包含 frontmatter；
- managed document hash 排除 `synced_at` 与 `content_hash`，杜绝自引用；
- 用户提供的 Markdown 中的 `---` 不会破坏受管 frontmatter。

- [x] **Step 2: 验证测试失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_markdown.py -q
```

Expected: FAIL，renderer 尚不存在。

- [x] **Step 3: 实现两个纯函数 renderer**

核心接口：

```python
def render_raw_knowledge_markdown(
    item: KnowledgeItem,
    *,
    category: str,
    relative_path: str,
    synced_at: str,
) -> str: ...


def render_analysis_knowledge_markdown(
    item: KnowledgeItem,
    *,
    category: str,
    raw_relative_path: str,
    relative_path: str,
    synced_at: str,
) -> str: ...
```

要求：

- raw 正文只有标题和“原文 / 逐字稿”；
- analysis 正文只有标题和“AI 解读”；
- 用 `yaml.safe_dump(..., allow_unicode=True, sort_keys=False)`；
- frontmatter identity 使用 `learnflux_context_key`，合集额外使用 collection/source ID；
- `content_hash` 对规范化正文做 SHA-256；
- managed document hash 对解析后的完整 frontmatter 和正文做规范化 SHA-256，但排除 `synced_at` 与 `content_hash`；
- existing 文件中额外的 frontmatter 字段参与 managed document hash，以便识别外部修改。

- [x] **Step 4: 运行 Markdown 测试**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_markdown.py -q
```

Expected: PASS。

## Task 3：扩展安全路径能力

**Files:**

- Modify: `src/video_transcript_api/obsidian/paths.py`
- Modify: `tests/unit/test_obsidian_paths.py`

- [x] **Step 1: 为一级分类和镜像目录写失败测试**

新增测试：

```python
def test_list_raw_categories_returns_only_direct_visible_directories(tmp_path):
    vault = tmp_path / "vault"
    (vault / "raw" / "AI" / "某合集").mkdir(parents=True)
    (vault / "raw" / ".private").mkdir()
    assert list_raw_categories(vault, raw_root="raw") == ["AI"]
```

并覆盖：

- `processed` 不存在时预览只计算相对路径，不创建目录；
- apply 可安全创建 `processed/分类/合集`；
- symlink、`..`、绝对路径和点目录被拒绝；
- 受管知识文件在目标目录中重命名后可恢复；
- 多个文件声明相同 identity 时安全失败。

- [x] **Step 2: 运行路径测试并确认失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_paths.py -q
```

Expected: FAIL，新 helper 尚不存在。

- [x] **Step 3: 最小实现**

新增：

```python
def list_raw_categories(vault_root: str | Path, *, raw_root: str = "raw") -> list[str]: ...

def build_knowledge_directory(
    *,
    root: str,
    category: str,
    collection_directory: str = "",
) -> str: ...

def ensure_vault_directory_tree(
    vault_root: str | Path,
    relative_directory: str,
) -> Path: ...
```

只复用现有 `_relative_parts`、`resolve_vault_path`、`find_managed_markdown_files`、`atomic_write_text`，不要复制安全逻辑。

- [x] **Step 4: 运行路径相关测试**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_paths.py tests/unit/test_obsidian_knowledge_markdown.py -q
```

Expected: PASS。

## Task 4：适配单篇与合集内容来源

**Files:**

- Create: `src/video_transcript_api/obsidian/knowledge_sources.py`
- Test: `tests/unit/test_obsidian_knowledge_sources.py`

- [x] **Step 1: 写来源解析失败测试**

单篇覆盖：

- `llm_calibrated` 优先于 `transcript_data`；
- 结构化 `transcript_data` 必须通过现有转录格式化能力转换为可读文本，不能直接写入 Python `dict/list` 字符串；
- `llm_summary` 作为 AI 解读；
- 在线任务保留原始 URL；
- 本地任务优先保留实际 `source_file_path`；
- 本地文件缺失时回退 `/view/{token}`；
- 原文或 AI 解读为空分别抛 `transcript_not_ready`、`analysis_not_ready`。

合集覆盖：

- `get_source_detail()` 的 `transcript` 与 `summary` 被映射；
- `source_access.kind=online_url` 使用原 URL；
- `local_file` 通过现有 `get_source_file_path()` 获取本地路径；
- `local_missing` 或本地路径失效时使用 `source_access.view_url`，通常为 `/view/{view_token}`；
- 没有外部 URL、本地文件和 view URL 时写空字符串，且不阻止同步；
- collection creator/title 组合成默认合集目录名；
- collection/source ID 和 owner 校验上下文被保留；
- 批量解析按 source position 稳定排序。

- [x] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_sources.py -q
```

Expected: FAIL，resolver 尚不存在。

- [x] **Step 3: 实现 resolver，不重复业务查询**

建议接口：

```python
class ObsidianKnowledgeSourceResolver:
    def resolve_single(self, owner_user_id: str, view_token: str) -> KnowledgeItem: ...

    def resolve_collection(
        self,
        owner_user_id: str,
        collection_id: str,
        source_ids: Sequence[str] | None,
    ) -> tuple[dict[str, Any], list[KnowledgeItem], list[dict[str, str]]]: ...
```

依赖通过构造器注入：

- `cache_manager`
- `collection_service`
- 单篇所有权校验 callable

不要从 resolver 导入 FastAPI `HTTPException`；使用稳定领域异常，由路由映射状态码。

合集 `source_access` 映射固定为：

```python
if access["kind"] == "online_url":
    source_access = access.get("url") or ""
elif access["kind"] == "local_file":
    source_access = collection_service.get_source_file_path(
        collection_id, source["id"]
    ) or access.get("view_url") or ""
else:
    source_access = access.get("view_url") or ""
```

- [x] **Step 4: 运行来源适配测试和相关合集测试**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_sources.py \
  tests/unit/test_learning_collections.py \
  tests/unit/test_history_routes.py -q
```

Expected: PASS。

## Task 5：实现分类推荐与可靠回退

**Files:**

- Create: `src/video_transcript_api/obsidian/knowledge_categories.py`
- Create: `tests/unit/test_obsidian_knowledge_categories.py`
- Modify: `config/config.example.jsonc`
- Modify: `tests/unit/test_obsidian_sync.py`

- [x] **Step 1: 写推荐器失败测试**

测试使用 fake LLM callable，覆盖：

- prompt 只包含候选分类和受限内容摘录；
- 合法返回得到 `category/confidence/reason`；
- 非候选分类、JSON 错误、异常和空响应回退“其他”；
- 没有“其他”时回退稳定排序第一项；
- 候选为空返回 `category_not_configured`，不调用 LLM。
- 合集推荐聚合合集标题、creator、description、`summary_markdown` 摘录和按 position 排序的若干分集标题/AI 摘录，而不是任选一篇分集。

- [x] **Step 2: 验证测试失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_categories.py -q
```

Expected: FAIL，推荐器尚不存在。

- [x] **Step 3: 实现推荐器**

```python
class ObsidianCategoryRecommender:
    def recommend(
        self,
        *,
        candidates: Sequence[str],
        title: str,
        analysis_excerpt: str,
        raw_excerpt: str,
    ) -> CategoryRecommendation: ...

    def recommend_collection(
        self,
        *,
        candidates: Sequence[str],
        collection: Mapping[str, Any],
        items: Sequence[KnowledgeItem],
    ) -> CategoryRecommendation: ...
```

约束：

- excerpt 在服务端截断；
- `recommend_collection()` 为整个合集构造一次受限聚合摘录，保留合集级信息和分集顺序；
- JSON schema 只允许候选字符串；
- LLM 调用走现有 `call_llm_api` 适配；
- 记录故障类型，不记录正文；
- 回退结果带 `recommended_by="fallback"`。

- [x] **Step 4: 增加可选配置默认值**

示例：

```json
"obsidian": {
  "enabled": false,
  "vault_id": "",
  "vault_path": "",
  "knowledge_raw_root": "raw",
  "knowledge_processed_root": "processed"
}
```

更新现有严格配置断言。运行时缺少新键时仍使用默认值，不能要求用户立即修改真实 `config/config.jsonc`。

- [x] **Step 5: 运行推荐与配置测试**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_categories.py \
  tests/unit/test_obsidian_sync.py -q
```

Expected: PASS。

## Task 6：实现无副作用预览和安全 apply

**Files:**

- Create: `src/video_transcript_api/obsidian/knowledge_service.py`
- Create: `tests/unit/test_obsidian_knowledge_service.py`

- [x] **Step 1: 写预览行为失败测试**

覆盖：

- preview 不创建目录、不写文件、不改数据库；
- 首次同步得到两个 `new` 文件；
- 重复同步得到 `unchanged`；
- LearnFlux 内容变化且文件仍是基线时得到 `changed`；
- Obsidian 文件偏离基线时得到 `externally_modified`；
- 用户重命名受管文件后得到 `relocated` 和真实相对路径；
- diff 有长度上限，且不包含 Vault 根绝对路径；
- raw/analysis 目标路径严格镜像。

- [x] **Step 2: 写 apply 前置条件失败测试**

覆盖：

- apply 在预览后源内容变化时返回 `stale_preview`；
- apply 在预览后 Obsidian 文件变化时返回 `stale_preview`；
- apply 在预览后 binding revision 变化时返回 `stale_preview`；
- apply 创建缺失的 `processed` 目录树；
- 每个文件用原子写 helper；
- raw 成功、analysis 失败返回 truthful partial；
- 成功后逐文件更新同步基线；
- 重试 partial 不创建重复文件；
- `force=True` 可把 unchanged 项纳入确认，但写后仍返回真实状态。

- [x] **Step 3: 运行测试并确认失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_service.py -q
```

Expected: FAIL，service 尚不存在。

- [x] **Step 4: 实现同步服务**

核心接口：

```python
class ObsidianKnowledgeService:
    def preview(
        self,
        *,
        items: Sequence[KnowledgeItem],
        binding: Mapping[str, Any],
        force: bool = False,
    ) -> dict[str, Any]: ...

    def apply(
        self,
        *,
        items: Sequence[KnowledgeItem],
        binding: Mapping[str, Any],
        expected_binding_revision: int,
        preconditions: Sequence[KnowledgeApplyPrecondition],
        force: bool = False,
    ) -> dict[str, Any]: ...
```

实现细节：

- 每个 `context_key` 使用进程内 `RLock`；批量按排序后的 context key 获取锁，避免死锁；
- 先确定 raw path，再让 analysis renderer 生成 raw wikilink；
- 用 `difflib.unified_diff` 生成受限预览；
- apply 先重新读取 binding 并比较 `expected_binding_revision`；
- apply 重新渲染和重新读取文件后比较前置条件；
- `atomic_write_text` 成功后立即更新对应路径和哈希；
- 单文件失败不回滚其他已成功文件；
- 未变化且非 force 不调用 `atomic_write_text`。

- [x] **Step 5: 运行 service 测试**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_service.py \
  tests/unit/test_obsidian_paths.py \
  tests/unit/test_obsidian_knowledge_markdown.py -q
```

Expected: PASS。

## Task 7：增加 authenticated knowledge API

**Files:**

- Modify: `src/video_transcript_api/api/routes/obsidian.py`
- Create: `tests/unit/test_obsidian_knowledge_routes.py`

- [x] **Step 1: 用失败测试固定路由契约**

测试 FastAPI app，覆盖：

- 未认证返回 401；
- 单篇与合集越权统一返回 404；
- Vault 未配置返回 503；
- categories 只返回 raw 一级目录；
- recommend 不接受客户端正文；
- binding 使用 optimistic revision；
- preview 返回路径、状态、diff 和 preconditions；
- apply 缺前置条件为 422；
- stale preview 为 409；
- selected collection 只解析请求 source IDs；
- all 增量返回 unchanged 计数和未就绪列表；
- force all 必须显式 `force=true`。

- [x] **Step 2: 运行路由测试并确认失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_knowledge_routes.py -q
```

Expected: FAIL，新路由不存在。

- [x] **Step 3: 增加请求模型和依赖工厂**

请求模型建议：

```python
class KnowledgeBindingRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=120)
    collection_directory: str = Field(default="", max_length=160)
    expected_revision: int | None = Field(None, ge=1)


class KnowledgeCollectionSelectionRequest(BaseModel):
    source_ids: list[str] | None = None
    sync_all: bool = False
    force: bool = False


class KnowledgeApplyRequest(KnowledgeCollectionSelectionRequest):
    expected_binding_revision: int
    preconditions: list[KnowledgeApplyPreconditionModel]
```

在路由层：

- 复用 `_configured_settings()`；
- 用当前 cache DB path 构造 `ObsidianKnowledgeRepository`；
- 本地 import collection service factory，避免模块循环；
- 复用现有用户/合集归属判断；
- 把领域错误映射为稳定 HTTP 状态与 `detail.code`。

- [x] **Step 4: 实现设计文档第 12 节全部路由**

路由必须在 preview 后才允许 apply。binding 保存前实时验证 category 是 raw 一级分类，合集 scope 要求非空 `collection_directory`。

- [x] **Step 5: 运行路由和既有 Obsidian API 测试**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_routes.py \
  tests/unit/test_study_routes.py \
  tests/unit/test_obsidian_sync.py -q
```

Expected: PASS。

## Task 8：在单篇结果页恢复明确入口

**Files:**

- Modify: `src/web/templates/transcript.html`
- Create: `src/web/static/js/obsidian-knowledge.js`
- Create: `src/web/static/css/obsidian-knowledge.css`
- Create: `tests/unit/test_obsidian_knowledge_frontend.py`
- Modify: `tests/unit/test_home_page.py`

- [x] **Step 1: 写单篇静态资产失败测试**

断言：

- 成功结果页存在 `id="obsidian-knowledge-open"`；
- 按钮不受 `study_available` 或 source-file 条件包围；
- 弹窗包含分类推荐、手动 select、raw/processed 路径、diff、确认按钮；
- JS 调用 recommend → binding → preview → apply；
- apply 请求携带 preconditions；
- apply 请求携带预览时的 binding revision；
- `409 stale_preview` 自动刷新预览并要求再次确认；
- 直接打开弹窗不会写盘；
- 加载失败显示可行动错误且恢复按钮状态；
- HTML 引用了独立 CSS/JS。

- [x] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_frontend.py \
  tests/unit/test_home_page.py -q
```

Expected: FAIL，入口和资产尚不存在。

- [x] **Step 3: 实现单篇弹窗**

交互顺序固定：

1. 点击按钮加载 categories/recommendation/binding；
2. 用户选择分类；
3. “生成同步预览”调用 preview；
4. 展示两个文件路径和 diff；
5. 用户确认后调用 apply；
6. 展示逐文件结果，不自动关闭失败结果。

按钮文案使用“沉淀到 Obsidian”，避免与边播边学中的“同步课程笔记”混淆。

- [x] **Step 4: 执行 JS 语法与静态测试**

Run:

```bash
node --check src/web/static/js/obsidian-knowledge.js
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_frontend.py \
  tests/unit/test_home_page.py -q
```

Expected: syntax check 与 pytest 均 PASS。

## Task 9：实现合集选择、增量全部与强制全部

**Files:**

- Modify: `src/web/static/collections.html`
- Modify: `src/web/static/js/collections.js`
- Modify: `src/web/static/css/collections.css`
- Modify: `tests/unit/test_obsidian_knowledge_frontend.py`
- Modify: `tests/unit/test_learning_collections.py`

- [x] **Step 1: 写合集 UI 失败测试**

断言：

- 合集工作区有“沉淀到 Obsidian”入口；
- 对话框含分类 select、合集目录、source checkbox、全选、预览所选；
- 存在“增量同步全部”；
- “强制重新同步全部”位于高级操作并有二次确认；
- selected 请求只发送勾选 source IDs；
- sync all 发送 `sync_all=true, force=false`；
- force all 发送 `sync_all=true, force=true`；
- UI 展示未就绪、unchanged、created、updated、failed 的逐项结果；
- 分类变化后必须重新 preview，旧 preconditions 被清空。

- [x] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_frontend.py \
  tests/unit/test_learning_collections.py -q
```

Expected: FAIL，合集入口尚不存在。

- [x] **Step 3: 实现合集弹窗**

复用现有：

- `currentCollection`
- source 排序与 display title helper
- `apiJSON`
- action dialog 的 focus/escape 处理模式

不要把同步状态写回 `exported_at`。默认勾选当前分集；“增量同步全部”不要求用户手工全选。

- [ ] **Step 4: 执行 JS 语法和合集测试**

Run:

```bash
node --check src/web/static/js/collections.js
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_frontend.py \
  tests/unit/test_learning_collections.py -q
```

Expected: PASS。

执行记录：JS 语法检查与知识沉淀前端测试通过；既有
`test_learning_collections.py` 仍有 2 项与本功能无关的后端失败，
因此本步骤保留未勾选。

## Task 10：集成回归与文档核对

**Files:**

- Modify only if evidence requires: files already listed above

- [x] **Step 1: 运行知识沉淀专项测试**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_knowledge_repository.py \
  tests/unit/test_obsidian_knowledge_markdown.py \
  tests/unit/test_obsidian_knowledge_sources.py \
  tests/unit/test_obsidian_knowledge_categories.py \
  tests/unit/test_obsidian_knowledge_service.py \
  tests/unit/test_obsidian_knowledge_routes.py \
  tests/unit/test_obsidian_knowledge_frontend.py -q
```

Expected: PASS。

- [ ] **Step 2: 运行受影响的既有回归**

Run:

```bash
uv run --extra dev pytest \
  tests/unit/test_obsidian_sync.py \
  tests/unit/test_obsidian_paths.py \
  tests/unit/test_obsidian_markdown.py \
  tests/unit/test_study_routes.py \
  tests/unit/test_study_frontend_assets.py \
  tests/unit/test_learning_collections.py \
  tests/unit/test_history_routes.py \
  tests/unit/test_home_page.py -q
```

Expected: PASS。

执行记录：除 `test_learning_collections.py` 的上述 2 项既有失败外，
本步骤列出的其余回归均通过；未修改对应合集后端或失败测试。

- [x] **Step 3: 运行前端语法和格式检查**

Run:

```bash
node --check src/web/static/js/app.js
node --check src/web/static/js/obsidian-knowledge.js
node --check src/web/static/js/collections.js
git diff --check
```

Expected: 全部 exit 0。

- [x] **Step 4: 执行 GitNexus 变更影响检查**

对 `ObsidianKnowledgeService`、新增 knowledge routes、修改过的 path helper 运行 `context` 和 upstream `impact`，然后：

```text
detect_changes(repo=<current repo path>, scope=all)
```

Expected: 变更只影响 Obsidian knowledge、单篇结果页、合集页和明确列出的测试；若发现高风险未覆盖调用方，先补针对性测试。

- [x] **Step 5: 人工验证只使用临时 Vault**

启动带临时 Vault 配置的本地服务，验证：

1. 单篇：推荐分类 → 修改分类 → 预览 → 确认；
2. 合集：勾选两篇 → 预览 → 确认；
3. 再次执行增量同步全部，未变化项不重写；
4. 手改临时 Vault 文件，重新预览显示 `externally_modified`；
5. 预览后再改文件，apply 返回 `stale_preview`；
6. `raw` 和 `processed` 路径镜像，analysis wikilink 可回到 raw。

禁止把自动化或人工测试目标指向 `/Users/zhanghanting/Obsidian`。

- [x] **Step 6: 报告结果，不发布**

向用户报告：

- 修改文件；
- 实际运行的命令和结果；
- 仍未验证的项目；
- 真实 Vault 尚未写入；
- 当前未提交修改仍保留。

除非用户随后明确授权，否则停在已验证、未提交、未推送状态。

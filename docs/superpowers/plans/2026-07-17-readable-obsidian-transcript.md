# Readable Obsidian Transcript Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Obsidian 文字稿从逐片段逐时间戳列表改为带段首时间戳的确定性自然段，同时保持原文顺序、同步幂等和笔记隔离。

**Architecture:** 在现有 `obsidian/markdown.py` 内增加纯函数式段落构建逻辑，由 `render_transcript_markdown` 负责组装标题、`## 文字稿` 和段落。同步服务继续使用现有 managed hash 与原子写入路径，因此旧文字稿会在下一次同步时原位更新，无需迁移器或新配置。

**Tech Stack:** Python 3.11、PyYAML、pytest、现有 Obsidian sync service。

**Authorization note:** 本计划不包含 commit、push 或 merge；用户未授权这些 Git 外部动作。

---

## File map

- Modify `src/video_transcript_api/obsidian/markdown.py`: 纯函数段落构建、标点连接、段尾规范化和 Markdown 渲染。
- Modify `tests/unit/test_obsidian_markdown.py`: 分段算法的边界与格式测试。
- Modify `tests/unit/test_obsidian_sync.py`: 旧格式被原位更新、新格式同步幂等且笔记不受影响的服务级测试。

### Task 1: 文字稿自然段渲染器

**Files:**
- Modify: `src/video_transcript_api/obsidian/markdown.py`
- Test: `tests/unit/test_obsidian_markdown.py`

- [ ] **Step 1: 写入失败测试，锁定基础格式与时间戳密度**

新增测试，输入多个短片段后断言：

```python
document = parse_markdown_document(render_transcript_markdown(metadata, lines))
assert document.body.startswith("# 第01课：核心概念\n\n## 文字稿\n\n")
assert document.body.count("**00:00**") == 1
assert "\n[00:02]" not in document.body
assert "第一段，第二段" in document.body
```

- [ ] **Step 2: 写入失败测试，覆盖完整规格边界**

参数化或分组测试必须覆盖：

- 中英文连接标点与句末标点（包括 ASCII `.`）；
- 180 字后的自然句尾；
- 260 字目标上限；
- 有 `end_seconds`/`start_seconds` 时的 8 秒静音边界；
- 预计超过 320 字时的加入前边界；
- `79 字短段 + 321 字单片段` 的超长片段隔离；
- `HH:MM:SS` 时间戳；
- 全部不可定位时不输出时间戳；
- 空文本被忽略、单个超长片段不被截断。

- [ ] **Step 3: 运行新测试并确认因旧逐行格式失败**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_markdown.py -q
```

Expected: 新增的自然段格式断言 FAIL；现有测试继续通过。

- [ ] **Step 4: 实现最小纯函数段落构建逻辑**

在 `markdown.py` 内增加私有帮助函数，职责保持分离：

```python
@dataclass(frozen=True)
class TranscriptParagraph:
    timestamp_seconds: float | None
    text: str


def _ends_with_punctuation(text: str, punctuation: str) -> bool: ...
def _join_transcript_text(current: str, fragment: str) -> str: ...
def _finish_paragraph_text(text: str) -> str: ...
def _build_transcript_paragraphs(lines: list[Mapping[str, Any]]) -> list[TranscriptParagraph]: ...
```

实现循环严格遵循规格优先级：

1. 忽略空片段并规范化首尾空白；
2. 超过 320 字的单片段先隔离；
3. 在加入当前片段前检查可靠 8 秒静音；
4. 在加入当前片段前检查预计 320 字硬上限；
5. 加入完整片段并记录本段第一个有效时间；
6. 加入后检查 260 字目标上限；
7. 未达 260 时检查 180 字后的自然句尾；
8. 输入结束后完成剩余段落。

字符计数使用去除空白后的 Unicode 字符数。片段只做连接标点和段尾标点处理，不拆分、不重排、不改写词语。

- [ ] **Step 5: 修改 Markdown 组装并运行格式测试**

`render_transcript_markdown` 输出：一级标题、空行、`## 文字稿`、空行、以空行分隔的自然段。段首时间戳格式为 `**MM:SS** ` 或 `**HH:MM:SS** `。

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_markdown.py -q
```

Expected: PASS。

### Task 2: 同步更新与幂等回归

**Files:**
- Modify: `tests/unit/test_obsidian_sync.py`
- Verify: `src/video_transcript_api/obsidian/service.py`（预计无需代码修改）

- [ ] **Step 1: 写入服务级 GREEN 回归测试**

Task 1 已完成新 renderer，因此本步骤不再要求 RED。创建绑定和笔记，首次同步后将 transcript 文件改写为旧的逐行格式，再次同步并断言现有同步架构自动提供更新与幂等：

```python
updated = service.sync(context)
assert updated["transcript"]["status"] == "updated"
assert "## 文字稿" in transcript_path.read_text(encoding="utf-8")
assert "**00:00**" in transcript_path.read_text(encoding="utf-8")
assert service.load_note(context)["document"]["body"] == original_note
assert service.sync(context)["transcript"]["status"] == "unchanged"
```

- [ ] **Step 2: 运行服务回归测试**

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_sync.py -q
```

Expected: PASS，证明 renderer 变化会通过 managed hash 原位更新旧文件，且不会改动笔记。

- [ ] **Step 3: 验证现有同步服务自动满足更新与幂等**

不增加迁移逻辑。新 renderer 改变 managed hash，现有 `_write_transcript` 应将旧文件标记为 `updated`；第二次同步应为 `unchanged`。只有测试暴露真实缺口时才对 `service.py` 做最小修复。

Run:

```bash
uv run --extra dev pytest tests/unit/test_obsidian_sync.py tests/unit/test_obsidian_markdown.py -q
```

Expected: PASS。

### Task 3: 全量验证与测试实例交付

**Files:**
- Verify only: all changed files

- [ ] **Step 1: 运行格式、同步和完整单元测试**

```bash
uv run --extra dev pytest tests/unit/test_obsidian_markdown.py tests/unit/test_obsidian_sync.py -q
uv run --extra dev pytest tests/unit
```

Expected: 全部 PASS，无新增失败。

- [ ] **Step 2: 运行静态与差异检查**

```bash
uv run python -m compileall -q src/video_transcript_api
node --check src/web/static/js/study-player-runtime.js
node --check src/web/static/js/study.js
git diff --check
```

Expected: exit code 0。

- [ ] **Step 3: 运行 GitNexus 变更影响检查**

对当前 worktree 执行 `detect_changes(scope="all")`，确认新增影响只来自预期的 Markdown renderer 和测试；整体分支已有的 Obsidian/学习页高影响由完整单元测试覆盖。

- [ ] **Step 4: 验证 8001 实例并通知用户复测**

确认 8001 服务仍可用。Python 模块由运行进程加载，需通过精确的 launchd 标签 `com.vta.obsidian-test-8001` 重启测试实例，使新 renderer 生效。重启前使用只读 SQLite 查询确认 `data/cache/cache.db` 的 `task_status` 表中不存在 `queued`、`processing` 或 `calibrating` 状态：

```sql
SELECT COUNT(*) FROM task_status
WHERE status IN ('queued', 'processing', 'calibrating');
```

若结果非 0，不重启、不影响在途任务，向用户报告需等待任务结束；若结果为 0，才通过该精确 launchd 标签重启 8001 并验证状态接口。随后让用户对刚才课程再次点击同步，检查原文件被更新为自然段格式且笔记未变化。

# LearnFlux Obsidian 知识沉淀设计

## 1. 文档状态

本文记录 2026-07-30 已确认的产品需求和实现边界。目标是让用户从“单篇深度学习”和“系列深度学习”中，手动挑选值得长期保留的内容，沉淀到本机 Obsidian，供后续检索、AI 创作、决策和 Skill 提炼使用。

本文授权后续任务实现代码，但不授权提交、推送、部署，也不授权向真实 Vault 写入测试数据。自动化测试必须使用临时目录。

## 2. 背景与问题

LearnFlux 已有一套 Obsidian 同步能力，但入口只存在于“边播边学”的用户笔记区域，且语义是：

- 同步学习页逐字稿；
- 双向同步用户持续编辑的课程笔记；
- 处理 LearnFlux 与 Obsidian 同时修改笔记时的冲突。

这与本次需求不同。本次要沉淀的是已经生成完成的知识材料：

- 原文、校对文本或逐字稿；
- AI 解读；
- 来源访问路径；
- 分类、合集和稳定身份等机器可读元数据。

这些内容主要供 AI 使用，不是用户在 Obsidian 中持续手写的笔记。因此，新能力必须与现有 `study-note` 同步并存，不能复用其双向编辑和冲突合并语义。

## 3. 目标

1. 单篇结果页提供始终可见的“沉淀到 Obsidian”入口，不依赖本地媒体文件是否保留，也不依赖“边播边学”是否可用。
2. 合集页允许勾选一篇、多篇，或增量同步全部内容。
3. AI 从现有 `raw` 一级分类中推荐一个分类，用户可在确认前修改。
4. 合集的所有分集统一进入一个合集目录。
5. 原材料和 AI 解读物理分层、路径镜像、稳定关联。
6. 每次同步都由用户手动发起；覆盖已有文件前先预览差异并再次确认。
7. 重复同步幂等；“同步全部”默认只处理新增或内容已变化的分集。
8. 生成的 Markdown 对人可读，也具有稳定、明确的 frontmatter，方便 AI 和后续工具使用。

## 4. 非目标

- 不自动监控内容完成状态并后台同步。
- 不把尚未生成完的原文或 AI 解读同步到 Vault。
- 不在本阶段自动生成 Codex/Claude Skills。
- 不在本阶段提供用户个人笔记编辑器或双向合并。
- 不迁移、重排或删除 Vault 中现有文件。
- 不把合集级“主线解读”混入分集材料。分集仍只同步各自原文与 AI 解读；合集级索引以独立的 `00-合集总览.md` 写入（raw/processed 镜像），供 AI 先建立全局视角再下钻章节。
- 不复用合集现有 `exported_at` 字段；它仍只表示旧的 Markdown 下载行为。

## 5. 知识分层与目录约定

Vault 根目录来自本地 `obsidian.vault_path`。知识沉淀使用两个并行根目录：

- 原材料层：`raw`
- AI 加工层：`processed`

两个根目录支持可选本地配置覆盖，但默认值固定为上述名称。示例配置不包含用户绝对路径。

### 5.1 单篇内容

```text
Obsidian/
├── raw/
│   └── 高效学习/
│       └── 如何建立高质量反馈回路.md
└── processed/
    └── 高效学习/
        └── 如何建立高质量反馈回路.md
```

### 5.2 合集内容

合集目录名使用用户在 LearnFlux 中确认的合集展示名。现有数据通常为“IP 名称 + 专题名称”，例如：

```text
Obsidian/
├── raw/
│   └── 屠龙胭脂井/
│       └── 屠龙胭脂井-创业 100 件事/
│           ├── 01 为什么要做难而正确的事.md
│           └── 02 如何判断真实需求.md
└── processed/
    └── 屠龙胭脂井/
        └── 屠龙胭脂井-创业 100 件事/
            ├── 01 为什么要做难而正确的事.md
            └── 02 如何判断真实需求.md
```

规则：

1. `raw` 与 `processed` 路径保持镜像。
2. 合集的分类与合集目录是合集级绑定；合集内分集不能各自落到不同分类。
3. 文件名使用现有安全文件名规则，并通过受管身份解决同名冲突。
4. 用户在 Obsidian 内重命名受管文件后，LearnFlux 可在绑定目录内通过 frontmatter 身份恢复路径。
5. 修改分类或合集目录绑定不会移动、删除旧文件；只影响后续同步，并在确认界面明确提示。

## 6. 内容与 Markdown 契约

### 6.1 原材料文件

原材料优先级：

1. LLM 校对后的完整文本；
2. 原始逐字稿；
3. 内容为空则判定 `content_not_ready`，禁止同步。

示例：

```markdown
---
type: learnflux-raw
source: LearnFlux
learnflux_context_key: "collection|..."
learnflux_view_token: "view_xxx"
learnflux_collection_id: "collection_xxx"
learnflux_source_id: "source_xxx"
category: 屠龙胭脂井
collection: 屠龙胭脂井-创业 100 件事
source_kind: online_url
source_access: https://example.com/original
content_hash: sha256:...
synced_at: 2026-07-30T14:00:00+08:00
---

# 01 为什么要做难而正确的事

## 原文 / 逐字稿

……
```

单篇省略 `learnflux_collection_id`、`learnflux_source_id` 和 `collection`。

### 6.2 AI 解读文件

```markdown
---
type: learnflux-analysis
source: LearnFlux
learnflux_context_key: "collection|..."
learnflux_view_token: "view_xxx"
learnflux_collection_id: "collection_xxx"
learnflux_source_id: "source_xxx"
category: 屠龙胭脂井
collection: 屠龙胭脂井-创业 100 件事
raw_note: "[[raw/屠龙胭脂井/屠龙胭脂井-创业 100 件事/01 为什么要做难而正确的事]]"
source_access: https://example.com/original
content_hash: sha256:...
synced_at: 2026-07-30T14:00:00+08:00
---

# 01 为什么要做难而正确的事

## AI 解读

……
```

AI 解读必须存在且非空才允许同步。`raw_note` 使用 Vault 相对路径生成 Obsidian wikilink，使 AI 和用户都能回到原材料。

### 6.3 哈希语义

为避免哈希自引用，固定使用两类不同哈希：

- frontmatter `content_hash`：只对该文件的规范化业务正文计算 SHA-256，不包含任何 frontmatter。raw 与 analysis 分别计算自己的正文哈希。
- `desired_hash`、`existing_hash`、`last_synced_hash`：对“规范化 frontmatter + 规范化正文”计算受管文档哈希，但计算前必须排除 `synced_at` 和 `content_hash`。因此时间变化不会制造更新，`content_hash` 也不会参与自己的计算。

现有文件中的其他 frontmatter 字段不被排除；用户手动增加或修改字段会改变 `existing_hash`，从而被识别为 `externally_modified`。

### 6.4 来源访问路径

`source_access` 按以下顺序选择：

1. 在线内容：原始外部 URL；
2. 已保留的本地文件：本地文件绝对路径；
3. 原文件不可用但 LearnFlux 结果仍可访问：`/view/{view_token}`；
4. 无任何路径：空字符串，并在预览中显示“来源路径不可用”，但不阻止同步。

来源路径只作为元数据写入，不复制音视频文件。

### 6.5 所有权

- `learnflux-raw` 和 `learnflux-analysis` 均由 LearnFlux 管理。
- 用户在这些文件中直接修改的内容不会被合并；再次同步前必须展示差异，并由用户确认是否覆盖。
- 后续个人笔记必须使用其他文件或目录，LearnFlux 永不自动覆盖。

## 7. 分类推荐

1. 分类候选只来自 `raw` 根目录的直接子目录，不递归把合集目录当分类。
2. 推荐输入由服务端从标题、AI 解读和原文短摘构造，客户端不能提交任意全文作为提示词。
3. LLM 只能从候选分类中选一个，并返回：
   - `category`
   - `confidence`
   - `reason`
4. LLM 返回非法分类、超时或失败时，回退到已存在的“其他”；若“其他”不存在，则回退到排序后的第一个分类。
5. 推荐只是默认值。用户必须能从现有分类列表中手动选择其他分类。
6. 单篇按内容推荐；合集按合集标题、简介、主线解读短摘和若干分集摘要整体推荐一次。
7. 合集推荐输入由服务端聚合，至少包含合集标题、creator、description、`summary_markdown` 受限摘录，以及按 position 排序的若干分集标题与 AI 摘录；不能拿某一篇分集代表整个合集。

## 8. 单篇交互

单篇结果页 `/view/{view_token}` 在导出操作附近增加“沉淀到 Obsidian”按钮。

点击后：

1. 服务端校验原文和 AI 解读均已完成。
2. 获取 `raw` 一级分类并给出 AI 推荐。
3. 用户确认或修改分类。
4. 请求同步预览。
5. 弹窗显示：
   - 两个目标相对路径；
   - `new / unchanged / changed / externally_modified` 状态；
   - 新文件显示摘要，更新文件显示受限长度的 unified diff；
   - 来源访问路径；
   - 明确的覆盖提示。
6. 用户点击“确认同步”后才写入。
7. 成功后显示两个文件的状态和相对路径。

该入口不依赖 `study_available`，因此在线链接、本地文档、未保留媒体文件的历史结果都可使用，只要缓存中的原文和 AI 解读仍存在。

## 9. 合集交互

合集页增加“沉淀到 Obsidian”入口。弹窗包含：

- AI 推荐分类及手动分类选择；
- 合集目录名预览；
- 分集复选列表；
- “全选 / 取消全选”；
- “预览所选”；
- “增量同步全部”；
- 折叠在高级操作中的“强制重新同步全部”。

规则：

1. “预览所选”只处理当前勾选的分集。
2. “增量同步全部”比较当前内容哈希与最后成功同步哈希：
   - 新增或已变化：进入预览；
   - 未变化：标记 `unchanged`，不写盘。
3. “强制重新同步全部”把所有已就绪分集纳入预览，即使内容哈希未变化；仍需用户确认后执行。
4. 未就绪分集返回稳定原因，如 `transcript_not_ready`、`analysis_not_ready`；它们不会被静默创建为空文件。
5. 批量写盘不承诺跨文件事务。响应按分集、按 `raw/analysis` 返回 `created / updated / unchanged / failed`，允许安全重试。
6. 分类或合集目录变化时，预览必须把所有目标视为新路径；旧路径文件保留。

## 10. 预览与确认协议

预览不是纯 UI 效果，而是写入前置条件。

每个待写文件的预览项至少包含：

- `document_type`
- `relative_path`
- `desired_hash`
- `existing_hash`，不存在时固定为 `__absent__`
- `last_synced_hash`
- `state`
- `diff`

预览顶层还必须包含当前 binding `revision`。应用请求必须回传 binding revision 和每个文件的预览前置条件。服务端在目标上下文锁内重新：

1. 重新读取 binding 并校验 revision；
2. 加载当前 LearnFlux 内容；
3. 重新计算目标内容哈希；
4. 重新读取目标文件；
5. 校验 `desired_hash` 和 `existing_hash`；
6. 任一变化则返回 `409 stale_preview` 和最新预览，不能使用旧确认覆盖后来变化。

`state` 定义：

- `new`：目标文件不存在；
- `unchanged`：当前目标内容与期望内容相同；
- `changed`：目标文件与上次 LearnFlux 同步基线一致，但新的 LearnFlux 内容发生变化；
- `externally_modified`：目标文件偏离上次 LearnFlux 同步基线；
- `relocated`：通过受管身份在绑定目录内恢复到重命名后的文件。

`externally_modified` 不禁止写入，但确认按钮必须明确写“覆盖 Obsidian 中的修改”。

## 11. 数据模型

新能力使用独立仓储，不修改现有 `obsidian_bindings`、`obsidian_source_sync` 或 `study_note_documents` 语义。

### 11.1 `obsidian_knowledge_bindings`

```text
id                    TEXT PRIMARY KEY
owner_user_id         TEXT NOT NULL
scope_type            TEXT NOT NULL  # single | collection
scope_id              TEXT NOT NULL  # view_token | collection_id
vault_id              TEXT NOT NULL
category              TEXT NOT NULL
collection_directory  TEXT NOT NULL DEFAULT ''
revision              INTEGER NOT NULL DEFAULT 1
created_at            TIMESTAMP
updated_at            TIMESTAMP
UNIQUE(owner_user_id, scope_type, scope_id, vault_id)
```

### 11.2 `obsidian_knowledge_sync`

```text
id                      TEXT PRIMARY KEY
owner_user_id           TEXT NOT NULL
context_key             TEXT NOT NULL
current_view_token      TEXT NOT NULL
collection_id           TEXT NOT NULL DEFAULT ''
source_id               TEXT NOT NULL DEFAULT ''
raw_relative_path       TEXT
raw_synced_hash          TEXT
analysis_relative_path  TEXT
analysis_synced_hash     TEXT
synced_at                TIMESTAMP
UNIQUE(owner_user_id, context_key)
```

`context_key` 复用现有 `build_study_context_key`，保证合集分集重试后 `view_token` 变化仍对应同一知识项。

数据库初始化必须使用 `CREATE TABLE IF NOT EXISTS` 和向后兼容迁移，不破坏已有本地数据库。

## 12. API

全局能力放在 `/api/obsidian/knowledge` 下，继续使用现有认证。

### 12.1 通用

- `GET /api/obsidian/knowledge/categories`
- `POST /api/obsidian/knowledge/single/{view_token}/recommend-category`
- `POST /api/obsidian/knowledge/collections/{collection_id}/recommend-category`

### 12.2 单篇

- `GET /api/obsidian/knowledge/single/{view_token}/binding`
- `PUT /api/obsidian/knowledge/single/{view_token}/binding`
- `POST /api/obsidian/knowledge/single/{view_token}/preview`
- `POST /api/obsidian/knowledge/single/{view_token}/apply`

### 12.3 合集

- `GET /api/obsidian/knowledge/collections/{collection_id}/binding`
- `PUT /api/obsidian/knowledge/collections/{collection_id}/binding`
- `POST /api/obsidian/knowledge/collections/{collection_id}/preview`
- `POST /api/obsidian/knowledge/collections/{collection_id}/apply`

所有单篇和合集接口必须复用现有归属校验。越权和不存在统一返回 404；未配置 Vault 返回 503；内容未就绪返回 409；绑定 revision、预览前置条件或受管身份冲突返回 409。

## 13. 组件边界

### 13.1 `ObsidianKnowledgeRepository`

只负责新绑定和同步基线的 SQLite 持久化。

### 13.2 `ObsidianKnowledgeSourceResolver`

把单篇缓存或合集分集转换成统一的 `KnowledgeItem`：

- 稳定身份；
- 标题、分类推荐摘录；
- 原文；
- AI 解读；
- 来源访问路径；
- 合集信息。

它复用现有缓存和合集服务，不重复实现转录、总结或所有权判断。

### 13.3 `ObsidianKnowledgeService`

负责：

- 校验分类和路径；
- 确定或恢复镜像文件路径；
- 渲染 Markdown；
- 计算内容与文件哈希；
- 生成 diff 预览；
- 校验预览前置条件；
- 单篇和批量原子写文件；
- 更新同步基线；
- 返回逐项结果。

它不调用 LLM。

### 13.4 `ObsidianCategoryRecommender`

只负责从现有候选分类中推荐一个分类。LLM 故障不能影响手动选择和同步。

### 13.5 前端

- `transcript.html` 负责单篇入口和对话框挂载点；
- 独立 JS/CSS 组件负责单篇同步交互，避免继续扩大内联脚本；
- `collections.html`、`collections.js`、`collections.css` 负责合集入口与选择列表；
- 现有 `study.html` 中的课程笔记同步保持不变。

## 14. 路径与写盘安全

- Vault 根目录是唯一允许的文件系统根。
- 客户端只提交分类名、合集目录名和稳定 ID，不提交绝对目标文件路径。
- 拒绝绝对路径、空字节、`.`、`..`、点目录和符号链接逃逸。
- 分类必须来自服务端实时列出的 `raw` 一级目录。
- `processed` 镜像目录不存在时，只能在用户确认应用后创建；预览不得写盘。
- 文件使用同目录临时文件和 `os.replace` 原子替换。
- 日志使用相对路径和稳定错误码，不输出完整 Vault 根路径。

## 15. 验收标准

1. 单篇结果不保留本地媒体时，仍可从 `/view/{token}` 打开知识沉淀弹窗。
2. 单篇必须经过“分类确认 → 预览 → 确认同步”才写入。
3. `raw` 文件只含来源元数据和原文；`processed` 文件含 AI 解读并链接 raw 文件。
4. 合集可同步任意勾选分集，也可一键增量同步全部。
5. 同一合集所有分集进入同一个合集目录。
6. 重复增量同步不重写未变化文件。
7. 强制同步全部仍需预览和确认。
8. Obsidian 文件在预览后变化时，应用返回 `409 stale_preview`。
9. 现有边播边学课程笔记同步测试继续通过。
10. 测试不读写 `/Users/zhanghanting/Obsidian`，只使用临时 Vault。

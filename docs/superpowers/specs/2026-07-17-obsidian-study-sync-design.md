# 边播边学：Obsidian 文字稿与课程笔记同步设计

## 1. 文档状态

本文描述已确认的产品设计，范围仅包括本机 VideoTranscriptAPI 与本机 Obsidian Vault 之间的文字稿和课程笔记同步。本文不授权实现、提交或修改 Obsidian 中的真实文件。

## 2. 背景与目标

用户会在边播边学页面观看单个音视频或合集中的某一节，并持续记录该节内容的自由笔记。当前系统能够保存 Study 笔记并下载整篇 Markdown，但仍需手动把文字稿和笔记移动到 Obsidian。

本功能要实现：

- 一键把当前音视频的完整文字稿写入绑定的 Obsidian `raw` 课程目录。
- 一节内容只维护一份持续编辑的课程笔记，并写入绑定课程目录下的“笔记”目录。
- 再次打开同一内容时继续显示最新笔记，可以在学习页或 Obsidian 中修改。
- 合集只在第一次同步时绑定目录，合集内其他内容自动继承。
- 单独学习内容拥有自己的独立绑定。
- 播放进度与笔记完全分离，继续沿用现有浏览器播放进度恢复逻辑。

## 3. 已确认的产品决策

1. 采用后端直接读写本机 Obsidian Vault，不使用浏览器目录句柄，也不开发 Obsidian 插件。
2. Vault ID 为 `faccc16bf91c3d30`，本机根路径为 `/Users/zhanghanting/Obsidian`。真实路径写入本地配置，不写入示例配置或提交到仓库。
3. 首次同步时由用户明确选择文字稿目录和笔记目录，不根据相似课程名猜测映射。
4. 合集绑定以 `collection_id` 为作用域；单独内容绑定以 `view_token` 为作用域。
5. 每节内容固定对应一个文字稿 Markdown 和一个课程笔记 Markdown，不按每次记录拆分文件。
6. 课程笔记是不绑定播放时间的自由 Markdown；播放进度独立保存。
7. 学习页编辑先保存到应用数据库，点击“一键同步到 Obsidian”后才写 Vault。
8. `raw` 文字稿是系统管理的生成产物，允许同步时覆盖更新；课程笔记需要保护双边修改。
9. 打开内容时自动采用唯一发生修改的一边；仅在应用草稿和 Obsidian 文件都基于上次同步发生修改时提示冲突。
10. 现有合集“导出 Markdown”只是下载合集 AI 总结。本功能是逐节文件系统同步，二者保持独立，不能复用或改写现有 `exported_at` 语义。

本地配置键固定为：

```json
{
  "obsidian": {
    "enabled": true,
    "vault_id": "faccc16bf91c3d30",
    "vault_path": "/Users/zhanghanting/Obsidian"
  }
}
```

真实值只写本机 `config/config.json`。可提交的示例配置只保留空值或通用占位符，不能包含用户绝对路径。

## 4. 目标目录与文件

一次合集绑定示例：

```text
Vault: /Users/zhanghanting/Obsidian
文字稿目录: raw/高效学习
笔记目录: 学习底层方法论/笔记
```

每节内容同步为：

```text
/Users/zhanghanting/Obsidian/
├── raw/高效学习/
│   └── 第01课：反战毒鸡汤.md
└── 学习底层方法论/笔记/
    └── 第01课：反战毒鸡汤.md
```

文件名取音视频标题去掉扩展名后的安全形式。文件名把 `/ : * ? " < > |`、空字节和 ASCII 控制字符替换为下划线，去除首尾空白和前导点，正文 stem 最长保留 120 个 Unicode 字符；结果为空时使用“未命名内容”。首次同步确定并持久化实际相对路径，在绑定不变时，即使标题变化也继续更新原文件。若同目录已有同名但不属于当前 source 的文件，则追加短 source 标识，不能覆盖陌生文件。

如果持久化路径上的文件消失，服务端必须在读取 Obsidian 正文和执行冲突算法之前，先在当前绑定目录内按受管 frontmatter 中的稳定身份查找，以支持用户在 Obsidian 中重命名文件。只找到一个匹配文件时恢复路径；找到多个匹配文件时安全失败并提示人工处理，不能任意选择；找不到时才把文件状态标记为“不存在”。“文件不存在”和“文件存在但正文为空”是两个不同状态，不能共用空字符串表示。

受管文件身份规则固定为：

- 合集文字稿：`type=transcript + vta_collection_id + vta_source_id`。
- 合集笔记：`type=study-note + vta_collection_id + vta_source_id`。
- 单篇文字稿：`type=transcript + vta_view_token`，且没有合集标识。
- 单篇笔记：`type=study-note + vta_view_token`，且没有合集标识。

合集中的 `view_token` 只是当前转录任务元数据，不参与文件身份判断，因为同一 source 重试后可能获得新 token。恢复搜索只在当前绑定目录内进行，不递归扫描整个 Vault。

## 5. Markdown 格式

### 5.1 文字稿

```markdown
---
type: transcript
source: VideoTranscriptAPI
vta_view_token: view_xxx
vta_collection_id: collection_xxx
vta_source_id: source_xxx
course: 高效学习
lesson: 第01课
synced_at: 2026-07-17T12:00:00+08:00
---

# 第01课：反战毒鸡汤

[00:00] 第一段文字……
[00:12] 第二段文字……
```

单独内容省略 `vta_collection_id` 和 `vta_source_id`。文字稿由应用完整生成；重新同步时可更新受管 frontmatter 和正文。

### 5.2 课程笔记

```markdown
---
type: study-note
source: VideoTranscriptAPI
vta_view_token: view_xxx
vta_collection_id: collection_xxx
vta_source_id: source_xxx
course: 高效学习
lesson: 第01课
synced_at: 2026-07-17T12:00:00+08:00
tags:
  - learning
---

这里是用户持续编辑的自由 Markdown。
```

学习页编辑器只编辑正文。系统更新自己管理的 frontmatter 字段，但必须保留用户在 Obsidian 中添加的其他属性，例如 `tags`、`aliases` 和自定义字段。笔记正文为空且从未创建过受管笔记文件时，一键同步仍同步文字稿，但不强制创建空笔记文件；响应明确返回 `note: skipped_empty`。如果受管笔记文件已经存在，而用户在学习页清空正文，同步必须把该文件原子更新为“保留 frontmatter、正文为空”，不能留下旧正文，否则旧内容会在下次打开时被错误导回。

## 6. 组件边界

### 6.1 `ObsidianSyncService`

新增独立服务，职责限定为：

- 读取已配置 Vault 并验证可用性。
- 列出和创建 Vault 内目录。
- 解析合集或单条内容的目录绑定。
- 为当前 source 确定稳定文件路径。
- 渲染文字稿 Markdown。
- 解析、合并并写入笔记 Markdown。
- 计算内容哈希、判断同步状态和处理冲突选择。
- 使用同目录临时文件和原子替换写盘。

该服务不负责转录、合集归属判定、播放进度或 Study 页面渲染。

### 6.2 Study 服务

现有 `StudyService` 继续负责构建当前单篇或合集 source 的学习会话。新增课程笔记文档读写入口，并向 `ObsidianSyncService` 提供经过归属校验的上下文、规范化文字稿和标题。

现有多条 `study_notes` CRUD 暂时保留兼容，不直接删除。新版页面只使用单文档接口。

### 6.3 前端

边播边学右侧新增“笔记”标签页：

- 自由 Markdown 编辑区。
- `已保存`、`尚未同步`、`已同步`、`存在冲突`状态。
- “同步到 Obsidian”按钮。
- “修改目录绑定”入口。
- 冲突时的学习页版本、Obsidian 版本预览和明确选择按钮。

## 7. 数据模型

### 7.1 `obsidian_bindings`

```text
id                    TEXT PRIMARY KEY
owner_user_id         TEXT NOT NULL
scope_type            TEXT NOT NULL  # collection | single
scope_id              TEXT NOT NULL  # collection_id | view_token
vault_id              TEXT NOT NULL
transcript_directory  TEXT NOT NULL  # Vault 内相对路径
note_directory        TEXT NOT NULL  # Vault 内相对路径
revision              INTEGER NOT NULL DEFAULT 1
created_at            TIMESTAMP
updated_at            TIMESTAMP
UNIQUE(owner_user_id, scope_type, scope_id, vault_id)
```

合集 source 只读取 `scope_type=collection, scope_id=collection_id` 的绑定，不允许静默退回同一 `view_token` 的单篇绑定。同一 `view_token` 出现在多个合集时，按当前路由中的合集上下文分别同步。

### 7.2 `study_note_documents`

```text
id                    TEXT PRIMARY KEY
owner_user_id         TEXT NOT NULL
context_key           TEXT NOT NULL
current_view_token    TEXT NOT NULL
collection_id         TEXT NOT NULL DEFAULT ''
source_id             TEXT NOT NULL DEFAULT ''
body                  TEXT NOT NULL DEFAULT ''
revision              INTEGER NOT NULL DEFAULT 1
created_at            TIMESTAMP
updated_at            TIMESTAMP
UNIQUE(owner_user_id, context_key)
```

`context_key` 是服务端统一通过 `build_study_context_key` 生成、客户端不可提交的稳定键。精确格式为：单篇 `single|{token长度}|{view_token}`；合集分集 `collection|{collection_id长度}|{collection_id}|{source_id长度}|{source_id}`。长度按 UTF-8 字节数计算，避免分隔符碰撞。合集重试只更新 `current_view_token`，不能创建新文档；因此一节始终只有一份数据库笔记。

### 7.3 `obsidian_source_sync`

```text
id                       TEXT PRIMARY KEY
owner_user_id            TEXT NOT NULL
context_key              TEXT NOT NULL
current_view_token       TEXT NOT NULL
collection_id            TEXT NOT NULL DEFAULT ''
source_id                TEXT NOT NULL DEFAULT ''
transcript_relative_path TEXT
transcript_synced_hash   TEXT
note_relative_path       TEXT
note_body_synced_hash    TEXT
note_managed_hash        TEXT
synced_at                TIMESTAMP
UNIQUE(owner_user_id, context_key)
```

同步状态使用与笔记文档相同的稳定 `context_key`。合集重试只刷新 `current_view_token` 和下次生成的非身份 frontmatter，继续沿用原文件路径和冲突基线。

`note_body_synced_hash` 只作为双边正文冲突的共同基线。`note_managed_hash` 基于受管 frontmatter、标题和正文计算，用于判断文件是否需要更新；用户自定义 frontmatter 不参与该哈希。所有哈希均排除每次同步变化的 `synced_at`，避免时间字段制造假变更。`transcript_synced_hash` 同样基于排除 `synced_at` 后的规范化受管内容计算。

## 8. 绑定解析

```text
当前页面是否为 /study/collections/{collection_id}/sources/{source_id}？
├── 是：按 owner_user_id + collection + collection_id 查绑定
└── 否：按 owner_user_id + single + view_token 查绑定
```

只有找不到当前作用域绑定时才弹出首次绑定。绑定记录包含递增 `revision`。修改合集绑定会影响该合集后续所有 source，但不自动移动已经同步的旧文件；修改前必须显示影响。

用户确认修改绑定后，服务端在同一数据库事务中更新绑定并清空该作用域下所有 `obsidian_source_sync` 的文件路径和同步哈希。合集作用域按 `owner_user_id + collection_id` 清空，单篇按 `owner_user_id + view_token` 且合集上下文为空清空。下一次同步只能在新目录重新恢复或分配路径，不能继续使用旧路径。旧目录中的文件保留，不删除、不移动，也不再参与新绑定的冲突判断。

## 9. 笔记版本与冲突算法

定义：

- `A`：应用数据库当前笔记正文哈希。
- `O_exists`：完成路径恢复后，Obsidian 受管笔记文件是否存在。
- `O`：仅当 `O_exists=true` 时计算的 Obsidian 当前笔记正文哈希；空正文拥有正常的空正文哈希。
- `B`：上次成功同步的笔记正文哈希，即 `note_body_synced_hash`。

打开页面或同步前按下表判断：

| 条件 | 状态 | 行为 |
| --- | --- | --- |
| `A = B` 且 `O = B` | clean | 显示应用内容，标记已同步 |
| `A != B` 且 `O = B` | app_dirty | 显示应用草稿，标记尚未同步 |
| `A = B` 且 `O != B` | obsidian_dirty | 自动导入 Obsidian 正文到数据库并显示 |
| `A != B` 且 `O != B` 且 `A = O` | converged | 更新同步基线，标记已同步 |
| `A != B` 且 `O != B` 且 `A != O` | conflict | 不写文件，要求用户选择版本 |

首次同步没有 `B` 时：

- `O_exists=false`：应用正文是待同步草稿；应用正文也为空时为 `skipped_empty`。
- 应用正文为空而 `O_exists=true`：采用 Obsidian 正文，包括 Obsidian 正文为空的情况。
- 两边正文相同：建立同步基线。
- 两边均非空且不同：进入冲突，不能按修改时间自动覆盖。

已有同步基线 `B`、完成路径恢复后仍确认 `O_exists=false` 时，状态为 `external_deleted`，不能把它当作空正文，也不能在页面打开时自动清空数据库或自动重建。前端明确提示“Obsidian 笔记文件已删除”，并提供：

- “用学习页笔记重建文件”：保留数据库正文，在当前绑定目录重新分配路径并写入。
- “接受 Obsidian 删除”：显式清空数据库正文，清除笔记文件路径和笔记同步哈希，不创建空文件。

即使 `A = B`，外部删除也必须显式确认，因为文件可能是误删或被移动到绑定目录之外。若 `A != B`，同样进入该确认流程并展示当前学习页正文。

解决冲突：

- “采用学习页版本”：显式覆盖 Obsidian 笔记并建立新基线。
- “采用 Obsidian 版本”：更新数据库正文并建立新基线。

前端提交 `revision` 做乐观锁。保存时数据库 revision 已变化则返回 `409` 和最新正文，防止两个学习页标签页互相覆盖。

冲突响应必须返回预览时的 `expected_revision`、`expected_obsidian_hash`（文件不存在固定使用 `__absent__`）和 `expected_baseline_hash`。解决冲突请求必须回传这三个前置条件以及选择结果。服务端在当前 source 的进程内互斥锁中重新读取数据库 revision、恢复并读取 Obsidian 文件、重新读取同步基线；任一值与预览不符时再次返回 `409` 和最新冲突状态，不能用旧预览覆盖后来发生的修改。

## 10. 一键同步数据流

1. 使用现有认证和上下文归属检查解析当前单篇或合集 source。
2. 解析当前作用域绑定；缺失时返回 `binding_required`。
3. 校验 Vault、两个目录和所有真实路径。
4. 在当前绑定目录中确定或恢复当前 source 的两个稳定文件路径；多匹配时安全失败。
5. 加载规范化文字稿、数据库笔记、恢复路径后的 Obsidian 笔记和同步基线，并保留“文件不存在/空正文”的区别。
6. 执行冲突算法；冲突时在任何写盘前返回 `409`。
7. 在目标目录分别生成临时文件，完成编码、frontmatter 和内容校验。
8. 原子替换文字稿；笔记正文非空或受管笔记文件已经存在时原子替换笔记。只有正文为空且从未存在受管笔记文件时才 `skipped_empty`。
9. 每个文件原子替换成功后，立即单独持久化该文件的路径、对应哈希和同步时间，然后再处理下一个文件。
10. 返回每个文件的 `created | updated | unchanged | skipped_empty | failed` 状态与相对路径或稳定错误码。

两个文件无法获得跨文件系统事务保证，因此接口按文件返回准确状态。全部成功或无需写入时返回 HTTP 200；至少一个文件成功、另一个写入失败时返回 HTTP 207 和 `overall=partial`；没有文件成功且发生 I/O 错误时返回 HTTP 500。已经成功替换的文件不回滚，其状态必须已持久化；所有操作幂等，部分写入后重试只会收敛到相同内容，不创建重复文件。如果文件已替换但同步状态持久化失败，后续重试必须通过受管身份和内容哈希重新收敛，日志记录稳定错误码但不暴露绝对路径。

## 11. API 设计

### 11.1 Vault 目录

- `GET /api/obsidian/status`：返回已配置 Vault ID、可用性和脱敏后的显示路径。
- `GET /api/obsidian/directories?root=raw|vault&q=`：只列出 Vault 内目录，忽略点目录。
- `POST /api/obsidian/directories`：在用户明确操作下创建目录；请求只接受父相对路径和单个目录名。

### 11.2 单篇内容

- `GET /api/study/{view_token}/note-document`
- `PUT /api/study/{view_token}/note-document`
- `GET /api/study/{view_token}/obsidian-binding`
- `PUT /api/study/{view_token}/obsidian-binding`
- `POST /api/study/{view_token}/obsidian-sync`
- `POST /api/study/{view_token}/obsidian-conflict/resolve`

### 11.3 合集内容

- `GET /api/study/collections/{collection_id}/sources/{source_id}/note-document`
- `PUT /api/study/collections/{collection_id}/sources/{source_id}/note-document`
- `GET /api/study/collections/{collection_id}/obsidian-binding`
- `PUT /api/study/collections/{collection_id}/obsidian-binding`
- `POST /api/study/collections/{collection_id}/sources/{source_id}/obsidian-sync`
- `POST /api/study/collections/{collection_id}/sources/{source_id}/obsidian-conflict/resolve`

绑定更新请求携带当前绑定 `revision`；revision 不匹配时返回 409，避免两个页面覆盖目录选择。冲突解决请求体包含 `choice=app|obsidian`、`expected_revision`、`expected_obsidian_hash` 和 `expected_baseline_hash`，并执行第 9 节定义的重新校验。

所有接口先复用现有单篇或合集归属校验。越权和不存在继续统一返回 404；认证失败返回 401；revision、双边内容冲突、受管身份多匹配或冲突前置条件变化返回 409。

## 12. 路径安全与写盘约束

- 本地配置中的 Vault 根目录是唯一允许的文件系统根。
- 所有客户端路径必须是相对路径，拒绝绝对路径、空字节、`..` 和保留字符。
- 使用解析后的真实路径验证目标仍位于 Vault 根目录内。
- 拒绝任何使最终真实路径逃逸 Vault 的符号链接。
- 目录浏览默认忽略 `.obsidian`、`.git`、`.claude`、`.claudian` 等点目录。
- 不能覆盖不满足第 4 节对应单篇或合集稳定身份元组的陌生同名文件；合集身份不要求 `vta_view_token` 匹配。
- 写盘使用目标目录内临时文件、刷新内容后执行原子替换；失败时清理临时文件。
- API 错误和日志不返回完整 Vault 绝对路径，只返回 Vault ID 和相对路径。

## 13. 异常行为

- Vault 不存在或不可写：停止同步并提示检查本地配置。
- 已绑定目录被删除或重命名：停止同步并提示重新绑定，不自动创建同名目录。
- 文字稿尚未生成：同步按钮显示“文字稿未就绪”，数据库笔记仍正常保存。
- 受管文件被重命名：按 frontmatter 稳定标识恢复路径。
- 已同步笔记文件在恢复后仍不存在：进入 `external_deleted` 确认，不自动清空或重建。
- 双边笔记修改：在写盘前返回冲突，不允许静默选择“更新较晚”的文件。
- 写盘部分失败：按第 10 节返回 HTTP 207、逐文件真实状态并持久化已成功文件；保留数据库草稿并允许幂等重试。全部 I/O 写入失败返回 HTTP 500。
- 绑定被修改：后续同步写新目录，旧文件不删除、不移动。

## 14. 现有笔记兼容

第一次读取新版 `study_note_documents` 时，如果文档不存在但当前上下文存在旧 `study_notes`：

1. 先完成现有单篇或合集归属校验，再读取遗留记录。
2. 单篇上下文读取相同 `view_token`、合集字段为空，且 `owner_user_id` 为当前用户、空字符串或 `NULL` 的旧记录；只有归属校验已经证明当前用户拥有该 view 时，才能认领空 owner 记录。
3. 合集上下文只读取完整匹配当前 `owner_user_id + collection_id + source_id` 的旧记录，不能认领空/NULL owner 的合集记录。
4. 严格沿用现有查询排序：`ORDER BY COALESCE(time_seconds, 999999999), created_at`，即有时间的记录先按播放时间，无时间记录最后，再按创建时间。
5. 去除空正文，用两个换行合并为一篇自由 Markdown，然后创建稳定 `context_key` 的单文档记录。
6. 保留旧记录，不删除、不回写时间标签。

迁移必须在同一事务内幂等完成。以后只读取单文档记录，避免旧记录重复合并。

## 15. 验证策略

### 15.1 单元测试

- 合集与单篇绑定解析。
- Unicode 标题、安全文件名和同名冲突后缀。
- 相对路径、`..`、绝对路径和符号链接逃逸校验。
- frontmatter 解析、受管字段更新和用户自定义字段保留。
- 文字稿渲染与无时间戳回退。
- 五种哈希状态、首次同步状态和两种冲突选择。
- revision 乐观锁。
- 原子写入失败后的临时文件清理。
- 旧多条笔记到单文档的幂等迁移。

### 15.2 集成测试

使用 `tmp_path` 创建临时 Vault，不读写真实 `/Users/zhanghanting/Obsidian`：

- 合集首次绑定后其他 source 自动继承。
- 单独内容拥有独立绑定。
- 同一 `view_token` 位于不同合集时写入各自目录。
- 每节只产生一份文字稿和一份笔记。
- 重复同步不产生重复文件。
- 合集 source 重试并更换 `view_token` 后仍读取同一笔记文档、文件路径和同步基线。
- Obsidian 单边修改自动回显到前端数据。
- 已同步笔记文件被删除时不会自动丢失数据库正文，只有显式选择后才重建或接受删除。
- 应用单边修改保持尚未同步。
- 双边修改返回 409 且文件未被覆盖。
- 外部重命名后按稳定标识找回文件。
- 部分写入失败后重试收敛。
- 所有路由继续执行当前用户归属校验。

### 15.3 前端测试

- 笔记标签、保存状态、同步状态和绑定窗口渲染。
- 合集只在无 collection 绑定时弹首次绑定。
- 单篇不读取合集绑定。
- 409 冲突显示两个版本且不能误触普通同步。
- 修改绑定前显示影响，取消不会改变当前绑定。

## 16. 完成条件

在不修改真实 Vault 的自动化测试中证明：用户可以为合集绑定一次目录或为单篇绑定独立目录；每节内容能稳定、幂等地同步一份文字稿和一份自由笔记；学习页与 Obsidian 的单边修改自动收敛，双边修改不会丢失；所有磁盘写入都被限制在配置的 Vault 内。

## 17. 明确不做

- 不开发 Obsidian 插件或使用 Obsidian URI。
- 不支持远程 Vault、云端双向同步或多台机器协调。
- 不把播放时间写入课程笔记，也不从笔记跳转播放位置。
- 不自动根据模糊课程名绑定目录。
- 不自动移动或删除修改绑定前生成的旧文件。
- 不让 Obsidian 监控事件实时推送到网页；仅在打开内容、刷新笔记或同步前读取最新文件。
- 不改变现有合集 AI 总结 Markdown 下载和 `exported_at` 行为。

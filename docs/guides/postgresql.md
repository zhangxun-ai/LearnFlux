# PostgreSQL 持久化与 SQLite 数据迁移

LearnFlux 默认仍可使用 SQLite；需要更强并发、部署扩展或统一备份时，推荐切换到 PostgreSQL。当前实现会把业务表和解析产物统一保存到 PostgreSQL，原始音视频只保留路径或哈希引用，不会复制进数据库。

## 存储边界

| 数据 | PostgreSQL | 本地文件 |
| --- | --- | --- |
| 任务、合集、笔记、审计、阅读、飞轮等业务记录 | 保存 | SQLite 仅作为迁移前回滚副本 |
| 原始转录、校对、总结、翻译、结构化结果、说话人映射 | 按原始字节保存并校验 SHA-256 | 切换后不再新增对应解析文件 |
| 原始音视频和用户已有资源 | 不复制，仅保留路径/哈希 | 保持原位置 |
| 下载或处理中的临时文件 | 不保存 | 仍由现有清理策略管理 |

## 新安装

先创建项目独占数据库，再从环境模板生成本地配置：

```bash
createdb learnflux
cp .env.example .env
chmod 600 .env
```

在 `.env` 中设置：

```dotenv
LEARNFLUX_PERSISTENCE_BACKEND=postgres
DATABASE_URL=postgresql:///learnflux
```

启动时会在事务中自动执行 `src/video_transcript_api/persistence/migrations/postgres/` 下尚未应用的版本化迁移。已执行迁移的文件带有校验和保护，不应原地修改；结构变化应新增编号文件。

## 从现有 SQLite 安全迁移

迁移脚本读取以下旧库：

- `data/cache/cache.db`
- `data/audit.db`（存在时）
- `data/flywheel/flywheel.db`（存在时）
- `data/config.db`（存在时）

切换步骤：

1. 停止会写入旧库的 LearnFlux 进程。
2. 备份上述 SQLite 文件及 `data/cache/` 下的解析产物。
3. 创建一个空的 PostgreSQL 项目库。
4. 保持 `.env` 的后端仍为 `sqlite`，执行迁移并核对报告。
5. 报告为 `migration_status=verified` 后，才把后端改为 `postgres` 并启动服务。

```bash
createdb learnflux
uv run python scripts/migrate_sqlite_to_postgres.py \
  --data-dir data \
  --database-url postgresql:///learnflux
```

脚本具有三道完整性保护：

- 目标业务表非空时拒绝导入，避免重复或覆盖数据。
- 对每张表进行行数和规范化内容摘要比对。
- 对每一份解析产物重新计算 SHA-256，并核对总清单摘要。

在 PostgreSQL 尚未开放业务写入前，可重复执行严格的逐行只读校验：

```bash
uv run python scripts/migrate_sqlite_to_postgres.py \
  --data-dir data \
  --database-url postgresql:///learnflux \
  --verify-only
```

成功输出至少包含：

```text
tables=<table count>
business_rows=<row count>
artifact_rows=<artifact count>
artifact_manifest_sha256=<sha256>
migration_status=verified
```

该命令会要求 PostgreSQL 与迁移源 SQLite 逐行完全一致。正式切换后，正常的任务、审计日志或 `updated_at` 更新都会产生预期差异，因此不要把切换后的严格校验失败直接判断为数据丢失；此时应以切换前的成功报告和只读备份为基线，检查旧主键是否仍存在、解析产物 SHA-256 是否仍一致。

## 切换验收

切换后至少检查：

```bash
curl -s http://localhost:8000/health
```

`checks.sqlite.backend` 会显示 `postgres`；这里保留 `sqlite` 这个键名是为了兼容旧健康检查客户端。还应打开一条迁移前的历史记录，分别查看页面、原始转录和总结导出，再重启一次服务重复检查。

## 回滚

在完成重启验收前，不要删除旧 SQLite 数据和旧解析目录。若 PostgreSQL 验收失败：

1. 停止 LearnFlux。
2. 将 `.env` 中 `LEARNFLUX_PERSISTENCE_BACKEND` 改回 `sqlite`。
3. 确认原 SQLite 文件与解析目录仍在原路径。
4. 重新启动并检查历史记录。

PostgreSQL 切换成功后，旧解析文件只是离线回滚副本，不会再被运行服务读取。建议经过一段可接受的观察期并完成独立备份后，再按明确文件清单清理；不要直接删除整个 `data/`，其中仍可能包含日志、用户资源和临时任务状态。

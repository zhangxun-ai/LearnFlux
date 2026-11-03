# PostgreSQL 持久化与 SQLite 数据迁移

本指南使用 PostgreSQL 作为业务数据库；SQLite 仍是可选的本地后端。当前实现会把业务表和解析产物统一保存到 PostgreSQL，原始音视频只保留路径或哈希引用，不会复制进数据库。不同用户的数据库地址、账号、密码和库名应保存在各自的私有环境配置中。

## 存储边界

| 数据 | PostgreSQL | 本地文件 |
| --- | --- | --- |
| 任务、合集、笔记、审计、阅读、飞轮等业务记录 | 保存 | SQLite 仅作为迁移前回滚副本 |
| 原始转录、校对、总结、翻译、结构化结果、说话人映射 | 按原始字节保存并校验 SHA-256 | 切换后不再新增对应解析文件 |
| 原始音视频和用户已有资源 | 不复制，仅保留路径/哈希 | 保持原位置 |
| 下载或处理中的临时文件 | 不保存 | 仍由现有清理策略管理 |

## 新安装

### 1. 准备数据库服务与专用账号

先完成项目依赖安装。PostgreSQL 是单独运行的服务，`bash scripts/bootstrap.sh` 不会安装或启动它，也不会创建数据库。让安装 Agent 先识别系统、已有服务和权限，再选择本机安装或复用已有 PostgreSQL；不要重复安装、修改其他项目的数据库，或自动购买云数据库。

用数据库管理身份为 LearnFlux 创建一个**专用空数据库**与拥有该库的应用角色。示例命令如下，仅适用于已能以管理身份连接 PostgreSQL 的终端；角色名和库名应按本机实际情况调整：

```bash
createuser --pwprompt --no-superuser --no-createdb --no-createrole learnflux_app
createdb --owner=learnflux_app --encoding=UTF8 --template=template0 learnflux
```

`--pwprompt` 会在终端私密输入新角色密码，不把密码写进命令历史。管理连接需要密码时使用工具的交互式密码提示，或已配置的私有 `PGSERVICEFILE`；不要把带密码的连接 URL 放到命令参数、聊天或日志里。Linux 软件包安装的管理角色、macOS 本机安装的管理角色和托管数据库的权限可能不同，上述命令不替代各环境的管理身份配置。

应用角色需要连接专用库并在应用 schema 中建表、建索引及执行后续迁移的权限，不应授予超级用户或创建其他数据库的权限。已有同名角色或数据库时先核对用途，不覆盖、不清空；复用已有 LearnFlux 数据库时进入后面的升级与验收步骤。

### 2. 在本机填写环境配置

在项目根目录复制模板；已有 `.env` 时保留原文件，不重复覆盖：

```bash
test -e .env || cp .env.example .env
chmod 600 .env
```

在自己的编辑器中设置后端和连接信息。下面的 URL 仅示意格式，尖括号内容必须在本机替换，不能直接运行：

```dotenv
LEARNFLUX_PERSISTENCE_BACKEND=postgres
DATABASE_URL=postgresql://<应用角色>:<URL编码后的密码>@<数据库主机>:<端口>/<专用库名>?sslmode=<连接所需模式>
```

运行时读取完整 `DATABASE_URL`；模板中的 `POSTGRES_*` 为辅助参数，不会自动拼装应用连接串。密码含 `@`、`:`、`/`、`#`、`%` 等 URL 特殊字符时必须正确编码。仅受信任的本机连接可按实际安装方式使用 `sslmode=disable`；远程连接按服务商要求配置 TLS，不能照搬本机设置。不要把模板中的示例账号和密码当作真实可用配置。

从 `main.py` 启动会自动加载项目根 `.env`，已有进程环境变量优先。数据库凭据不填写到网页的 LLM Key 字段，也不写入公开配置模板。已有用户应保留原本的 PostgreSQL 连接，不因更新安装步骤而切换成 SQLite。

### 3. 启动并自动创建表结构

在项目根目录运行：

```bash
bash server.sh start
bash server.sh status
```

新库首次连接时，`get_persistence_database()` 会调用 `migrate_postgres_schema()`，在事务中自动执行 `src/video_transcript_api/persistence/migrations/postgres/` 下尚未应用的版本化迁移。**新安装不需要运行 SQLite 数据迁移脚本，也不需要手工逐个执行 SQL 文件。**

当前仓库包含 `0001_initial.sql` 至 `0008_image_diagrams.sql` 共 8 个迁移。执行记录保存在 `learnflux_schema_migrations`，包含版本、文件名、SHA-256 校验和及执行时间；事务级 advisory lock 避免多个实例同时应用同一迁移。升级时只应用缺少的版本，已执行文件的校验和必须匹配；结构变化应新增编号文件，不原地修改已应用迁移。遇到校验和不符、权限不足或连接失败时保留现有数据，查看具体原因后修复，不以删库重建代替升级。

### 4. 核对连接与表结构

先检查 `/health` 的 `checks.sqlite.backend` 为 `postgres` 且该项 `healthy` 为 `true`。这里沿用 `sqlite` 键名是为了兼容旧客户端；它只用 `SELECT 1` 验证连接，不能单独证明所有表结构已就绪。

让安装 Agent 在本机临时 Python 进程中调用 `load_project_dotenv()` 读取 `.env`，再用 `os.environ["DATABASE_URL"]` 建立连接。该检查应设为只读事务，只报告检查结果，不打印连接 URL、环境字典或密码。也可使用预先配置的私有 `PGSERVICEFILE` 与 `psql "service=learnflux" -W`，通过密码提示连接后执行：

```sql
BEGIN READ ONLY;
SELECT version, name, checksum
FROM learnflux_schema_migrations
ORDER BY version;

SELECT table_name
FROM information_schema.tables
WHERE table_schema = current_schema()
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
COMMIT;
```

将账本的版本、文件名和校验和逐项与当前仓库 `load_postgres_migrations()` 的结果核对，并确认迁移声明的表均存在。当前 SQL 共创建 56 张业务表，加迁移账本后是 57 张，作为**全新专用库的核对参考**；已有数据库可能有其他表，不能仅因总表数不等于 57 就判定失败。验收以后续实际功能可用、迁移记录匹配及必要表存在为准，不对已有库强制要求精确总表数。

最后完成一份无隐私短文字的学习、打开结果并重新访问，确认任务和学习结果能持久保存。只有在已有可用模型配置且用户允许调用时才执行 AI 验证；不要为测数据库调用收费 ASR。`tests/integration/test_postgres_persistence_contract.py` 会写入和删除测试记录，只能配合独立临时测试库的 `TEST_DATABASE_URL` 使用，不能把实际用户库当作测试夹具。

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

迁移脚本**不会自动加载根 `.env`**。先在本机 `.env` 配好目标库的 `DATABASE_URL`，保留 `LEARNFLUX_PERSISTENCE_BACKEND=sqlite`，再用下列临时进程加载环境并运行脚本；连接密码不会进入命令参数：

```bash
uv run python - <<'PY'
import runpy
import sys
from dotenv import load_dotenv

load_dotenv(".env", override=False)
sys.argv = ["scripts/migrate_sqlite_to_postgres.py", "--data-dir", "data"]
runpy.run_path(sys.argv[0], run_name="__main__")
PY
```

不要对没有旧 SQLite 数据的新安装执行这个命令：它要求 `data/cache/cache.db` 存在。仅需要创建新库表结构时，按前面的首次启动流程处理。

脚本具有三道完整性保护：

- 目标业务表非空时拒绝导入，避免重复或覆盖数据。
- 对每张表进行行数和规范化内容摘要比对。
- 对每一份解析产物重新计算 SHA-256，并核对总清单摘要。

在 PostgreSQL 尚未开放业务写入前，可重复执行严格的逐行只读校验：

```bash
uv run python - <<'PY'
import runpy
import sys
from dotenv import load_dotenv

load_dotenv(".env", override=False)
sys.argv = [
    "scripts/migrate_sqlite_to_postgres.py", "--data-dir", "data", "--verify-only"
]
runpy.run_path(sys.argv[0], run_name="__main__")
PY
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

# 日志系统指南

本文档介绍视频转录API的日志系统，包括基本使用、配置、以及特定模块的日志说明。

---

## 1. 快速开始

### 1.1 基本用法

```python
# 方式 1: 直接使用全局 logger（推荐）
from video_transcript_api.utils import logger

logger.info("This is an info message")
logger.warning("This is a warning")
logger.error("This is an error")
logger.debug("This is a debug message")

# 方式 2: 使用 setup_logger（兼容旧代码）
from video_transcript_api.utils import setup_logger

log = setup_logger("module_name")
log.info("This is an info message")
```

### 1.2 日志级别

loguru 支持以下日志级别（从低到高）：

- `logger.trace()` - 最详细的调试信息
- `logger.debug()` - 调试信息
- `logger.info()` - 一般信息
- `logger.success()` - 成功信息（loguru 特有）
- `logger.warning()` - 警告信息
- `logger.error()` - 错误信息
- `logger.critical()` - 严重错误

---

## 2. 系统架构

### 2.1 日志系统迁移

本项目已成功将日志系统从 Python 标准 `logging` 模块迁移到 `loguru`。

**迁移优势**：
1. **彩色控制台输出**: 不同日志级别使用不同颜色，便于快速识别
2. **更详细的上下文**: 自动包含模块名、函数名和行号
3. **异步文件写入**: 使用 `enqueue=True` 提高性能
4. **自动日志轮转**: 基于文件大小自动轮转

### 2.2 日志格式

**控制台输出**（彩色）:
```
2025-10-21 14:37:14 | INFO     | module:function:42 - message
```

**文件输出**（纯文本）:
```
2025-10-21 14:37:14 | INFO     | video_transcript_api.utils.module:function:42 - message
```

---

## 3. 配置说明

### 3.1 基本配置

日志配置在 `config/config.json` 中的 `log` 部分：

```json
{
  "log": {
    "level": "INFO",           // 日志级别: DEBUG, INFO, WARNING, ERROR
    "file": "./data/logs/app.log",  // 日志文件路径
    "max_size": 10485760,      // 单个文件最大大小（字节）
    "backup_count": 5          // 保留的备份文件数量
  }
}
```

### 3.2 日志级别配置

| 级别 | 说明 | 使用场景 |
|------|------|----------|
| DEBUG | 详细的调试信息 | 开发环境、问题排查 |
| INFO | 重要的流程信息 | 生产环境默认级别 |
| WARNING | 警告信息，不影响主流程但需要注意 | 需要关注的非错误情况 |
| ERROR | 错误信息 | 错误发生时 |
| CRITICAL | 严重错误，导致无法继续 | 致命错误 |

**生产环境（推荐）**：
```json
{
  "log": {
    "level": "INFO"
  }
}
```
**显示内容**：
- ✅ 关键流程信息
- ✅ 警告和错误
- ❌ 详细的 DEBUG 信息

**开发/调试环境**：
```json
{
  "log": {
    "level": "DEBUG"
  }
}
```
**显示内容**：
- ✅ 所有级别的日志
- ✅ 详细的执行步骤
- ✅ 每个句子的映射细节

---

## 4. 使用方法

### 4.1 带上下文的日志

```python
# 使用 f-string 格式化
user_id = 12345
logger.info(f"User {user_id} logged in")

# loguru 会自动包含调用位置信息
# 输出: 2025-10-21 14:37:14 | INFO | module:function:42 - User 12345 logged in
```

### 4.2 异常日志

```python
try:
    risky_operation()
except Exception as e:
    # 自动记录完整的异常堆栈
    logger.exception("Operation failed")
    # 或者
    logger.error(f"Operation failed: {e}")
```

### 4.3 FunASR 兼容格式日志

FunASR 格式生成过程使用了分层的日志系统，不同级别的日志提供不同详细程度的信息。

**成功场景**：
```
[INFO] 开始生成 FunASR 兼容格式 JSON...
[INFO] 输入数据: text=243 字符, tokens=205, timestamps=205
[DEBUG] 开始创建 segments: text=243, tokens=205, timestamps=205
[DEBUG] Token 位置映射完成: reconstructed length=217
[DEBUG] 按标点分句: 6 个句子
[DEBUG] 对齐检查通过: diff=0
[DEBUG] 句子 1: 12 字符 -> tokens[0:11] -> 0.08s-1.50s
[DEBUG] 初始分段完成: 6 个 segments
[DEBUG] 长度优化完成: 3 个 segments
[INFO] Segments 生成完成: 3 个片段, 2/3 在目标范围内
[INFO] 成功创建 3 个 segments
[INFO] Segments 统计: 总时长=38.86s, 平均长度=81.0字符
[INFO] ✓ 已生成 FunASR 兼容文件: transcript_capswriter.json (3 个片段)
```

**异常场景**：
```
[WARNING] 警告: 文本为空，跳过 FunASR 格式生成
[WARNING] ✗ 生成 FunASR 兼容格式失败: text is empty
[WARNING]   提示: 主要转录文件（txt）已正常生成，可忽略此警告
```

---

## 5. 最佳实践

### 5.1 ✅ 推荐

```python
# 1. 使用描述性的日志消息
logger.info("User authentication successful", user_id=user_id)

# 2. 在关键操作前后记录日志
logger.info("Starting video download...")
download_video(url)
logger.info("Video download completed")

# 3. 记录异常时使用 exception()
try:
    process_data()
except Exception:
    logger.exception("Failed to process data")
```

### 5.2 ❌ 避免

```python
# 1. 避免在循环中过度记录
for item in large_list:
    logger.debug(f"Processing {item}")  # 太多日志

# 2. 避免记录敏感信息
logger.info(f"User password: {password}")  # 危险！

# 3. 避免使用 print() 代替日志
print("This is bad")  # 应该使用 logger.info()
```

---

## 6. 性能考虑

1. **日志级别**: 生产环境使用 INFO 或 WARNING
2. **异步写入**: loguru 已配置异步文件写入 (`enqueue=True`)
3. **条件日志**: 只在必要时记录详细信息

```python
if logger.level("DEBUG").no >= logger._core.min_level:
    expensive_debug_info = compute_debug_info()
    logger.debug(f"Debug info: {expensive_debug_info}")
```

---

## 7. 调试技巧

### 7.1 临时启用调试日志

```python
from loguru import logger

# 临时添加调试级别的控制台输出
debug_id = logger.add(
    sys.stdout,
    level="DEBUG",
    format="{time} | {level} | {message}"
)

# 调试完成后移除
logger.remove(debug_id)
```

### 7.2 查看最近的日志

```bash
# Linux/Mac
tail -f data/logs/app.log

# Windows
Get-Content data/logs/app.log -Tail 50 -Wait

# 查看特定模块的日志
grep "FunASR" logs/app.log

# 查看警告和错误
grep -E "WARNING|ERROR" logs/app.log
```

---

## 8. 常见问题

### Q1: 如何改变日志级别？
A: 修改 `config/config.json` 中的 `log.level` 配置。

### Q2: 日志文件在哪里？
A: 默认在 `data/logs/app.log`。

### Q3: 如何禁用彩色输出？
A: 修改 `src/video_transcript_api/utils/logger.py` 中的 `colorize=True` 为 `False`。

### Q4: 旧代码需要修改吗？
A: 不需要。`setup_logger()` 已经兼容，返回 loguru logger。

### Q5: FunASR 文件未生成？
A: 查看日志中的警告信息，检查是否有 "文本为空" 或 "tokens 为空" 警告。主流程不受影响，txt 文件会正常生成。

---

## 9. 向后兼容性

- 所有使用 `setup_logger("name")` 的代码无需修改
- `setup_logger()` 现在返回 loguru 的全局 logger 实例
- 支持多次调用 `setup_logger()`，但只配置一次

---

## 10. 参考资料

- [Loguru 官方文档](https://loguru.readthedocs.io/)
- [FunASR 日志指南](../guides/api/funasr_spk_server_client_api.md)

---

## 更新日志

### 2025-10-21
- 完成从 Python logging 到 loguru 的迁移
- 新增彩色控制台输出
- 新增详细的上下文信息（模块名、函数名、行号）
- 配置异步文件写入提升性能

### 早期版本
- 使用 Python 标准 logging 模块
- 基本的文件日志功能

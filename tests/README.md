# 测试说明

项目使用 pytest。开发、测试和输出规则以根目录的 [AGENTS.md](../AGENTS.md) 为唯一事实来源。

## 默认验证

```bash
# verify-fast：快速单元测试
uv run --extra dev pytest tests/unit

# verify-full：全部默认离线测试
uv run --extra dev pytest
```

运行单个测试文件或用例：

```bash
uv run --extra dev pytest tests/unit/test_downloader.py
uv run --extra dev pytest tests/unit/test_downloader.py::test_name
```

## 显式外部检查

`features/`、`integration/`、`llm/`、`manual/`、`performance/` 和 `platforms/` 不参与默认收集。它们包含遗留场景或可能需要凭据、可访问的外部服务、网络、本地媒体及数据写入，只运行当前任务需要的具体文件：

```bash
uv run --extra dev pytest tests/integration/<test_file>.py -s
uv run --extra dev pytest tests/llm/<test_file>.py -s
uv run --extra dev pytest tests/platforms/<test_file>.py -s
uv run python tests/performance/test_concurrent.py
uv run python tests/manual/test_transcribe.py <audio_path>
```

测试输出保持英文 ASCII。临时媒体写入 `tests/cache/`，验证后清理。

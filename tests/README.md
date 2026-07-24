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

## 百炼 Fun-ASR 真实验收（显式付费）

该验收默认只做离线 dry-run，并用生产 `MediaSnapshotter` 锁定样本文件、manifest、规范化快照 SHA-256/大小/时长、价格日期和单次费用上限；dry-run 的 staged 文件在写入私密 receipt 后立即清理。真实 `execute` / `resume` 仅在显式设置 `LEARNFLUX_ALIYUN_ASR_EXECUTE_PAID=1` 时触达生产 Provider；`submission_unknown` 不得重试，`polling_unknown` 只能用 `resume` 恢复同一持久 task。`resume` 使用持久事件里的模型、快照和 task，只受独立轮询时限约束，不重新通过当前价格或新提交预算门。

百炼密钥只通过以下三个环境变量提供，不写入配置、命令输出或测试产物：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_WORKSPACE_ID`
- `DASHSCOPE_API_HOST`

控制变量为 `LEARNFLUX_ALIYUN_ASR_MODE`（`dry-run` / `execute` / `resume`）、`LEARNFLUX_ALIYUN_ASR_SAMPLE`、`LEARNFLUX_ALIYUN_ASR_MAX_CNY` 和付费守卫 `LEARNFLUX_ALIYUN_ASR_EXECUTE_PAID`。固定预算只有两项：`zh_terms_clean_15s = 0.00330 CNY`，`long_natural_20_60m = 0.31966 CNY`。

```bash
# 离线选择与预算门（remote_calls=0）
LEARNFLUX_ALIYUN_ASR_MODE=dry-run LEARNFLUX_ALIYUN_ASR_SAMPLE=zh_terms_clean_15s \
  LEARNFLUX_ALIYUN_ASR_MAX_CNY=0.00330 \
  uv run --extra dev pytest tests/integration/test_aliyun_funasr_acceptance.py -q -s
LEARNFLUX_ALIYUN_ASR_MODE=dry-run LEARNFLUX_ALIYUN_ASR_SAMPLE=long_natural_20_60m \
  LEARNFLUX_ALIYUN_ASR_MAX_CNY=0.31966 \
  uv run --extra dev pytest tests/integration/test_aliyun_funasr_acceptance.py -q -s

# 仅在已获付费授权、相同样本 dry-run 成功后执行一次
LEARNFLUX_ALIYUN_ASR_MODE=execute LEARNFLUX_ALIYUN_ASR_SAMPLE=zh_terms_clean_15s \
  LEARNFLUX_ALIYUN_ASR_EXECUTE_PAID=1 LEARNFLUX_ALIYUN_ASR_MAX_CNY=0.00330 \
  uv run --extra dev pytest tests/integration/test_aliyun_funasr_acceptance.py -q -s

# 仅当上一步安全状态为 polling_unknown 时恢复同一 task；不提供新预算
LEARNFLUX_ALIYUN_ASR_MODE=resume LEARNFLUX_ALIYUN_ASR_SAMPLE=zh_terms_clean_15s \
  LEARNFLUX_ALIYUN_ASR_EXECUTE_PAID=1 \
  uv run --extra dev pytest tests/integration/test_aliyun_funasr_acceptance.py -q -s
```

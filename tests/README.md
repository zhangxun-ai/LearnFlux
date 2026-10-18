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

## 单篇导入与历史浏览回归

以下检查均离线执行，不上传真实文件、不调用付费模型、不写入实际任务库。Python 测试使用临时 SQLite 或模拟 PostgreSQL 适配器；前端行为测试需要 Node.js。

```bash
uv run --extra dev pytest tests/unit/test_history_routes.py tests/unit/test_audit_history_marks.py tests/unit/test_history_browser_behavior.py tests/unit/test_single_study_behavior.py tests/unit/test_local_upload_history.py
node tests/frontend/history_browser_behavior.cjs
node tests/frontend/single_study_behavior.cjs
```

历史检查覆盖用户归属、旧审计兼容、去重计数、日期/状态/精华过滤、只读查询、口令轮换后的摘要权限、迟到响应、行内预览关闭、分页与查询缓存隔离，以及卡片/表格封面映射、状态一致性和滚动容器恢复。单篇检查覆盖文件预选后开始、取消上传、防重复提交、失败保留输入与草稿隔离。

页面约定：单篇只显示最近 4 条任务；完整历史提供每页 20/50/100 条与最多 1000 条的全部浏览，选择仅作用于当前页，打开状态以当前浏览器为准。记录缓存按当前用户与会话隔离，保留 60 秒；筛选元数据缓存 5 分钟，点击“刷新记录”可主动更新。

## 视频解析完整性回归

`test_summary_quality.py`、`test_summary_completion.py`、`test_summary_model_fallback.py` 和 `test_summary_compensation.py` 覆盖长访谈只有概述、短内容自然段、API 非正常结束、备用端点、Qwen Plus 推理参数适配及预算、仅解析重试、保存失败、重复重试，以及原文没有的技术引用和伪引语触发一次自动修订。全部使用离线模拟，不调用付费模型。`test_comment_cache_policy.py`、`test_llm_ops_helpers.py` 覆盖历史残缺总结不能直接复用。

```bash
uv run --extra dev pytest tests/unit/test_summary_quality.py tests/unit/test_summary_completion.py tests/unit/test_summary_model_fallback.py tests/unit/test_summary_compensation.py tests/unit/test_comment_cache_policy.py tests/unit/test_llm_ops_helpers.py
```

## Obsidian 同步回归

`tests/unit/test_obsidian_knowledge_*.py` 覆盖临时 Vault 中的路径、内容筛选、文件冲突、Markdown 与 API 契约，不写入个人知识库。前端行为检查由 `test_obsidian_knowledge_frontend.py` 调用，也可独立执行：

```bash
node tests/frontend/obsidian_sync_behavior.cjs
```

该检查覆盖完整目录刷新、嵌套路径、内容勾选、外部修改二次确认、选项变化使预览失效、读取失败清除旧目录。未安装 Node.js 时 pytest 会跳过这项行为检查。

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

## 首页任务状态回归

`test_cloud_pricing.py`、`test_cloud_asr_config.py` 覆盖官方价格解析、后台刷新失败沿用旧值、旧核验日期正常报价；`test_asr_retry.py`、`test_cloud_retry_retention.py` 覆盖音频身份、24 小时保留、并发重试、任务归属、防重复云端提交和真实任务存储的重试标记；`test_local_whisper_runtime.py` 覆盖长音频时限与安全错误提示。均使用离线模拟，不提交付费任务。

`tests/unit/test_task_status_frontend.py` 调用 Node.js DOM 行为检查，覆盖阶段与进度、缺失进度、任务链接编码、远端文本安全、刷新时保留详情及焦点、费用确认、本地切换、失败重试和转录方式偏好。所有 API 均为模拟，不产生转录费用。

```bash
node tests/frontend/task_status_behavior.cjs
```

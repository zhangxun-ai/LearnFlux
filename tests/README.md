# 测试说明

本机日报离线回归：`uv run --extra dev pytest tests/unit/test_briefings.py -q`。覆盖所有者与本机限制、动态授权范围、文件完整性、只读预览、同步确认与防覆盖，以及期号与内容日期适配、跨年/历史重生成、Markdown 下载与预览日期一致、微信界面去重时保留内容和出处。不会连接真实飞书或写入用户笔记库。2026-10-31 V2 实测 22 项通过；导航检查 `uv run python scripts/sync_product_navigation.py --check` 通过，依赖仍有 deprecation 警告。接入、来源项目验证和浏览器实测边界见 [日报指南](../docs/guides/daily-briefings.md) 与 [发布准备验证](../docs/release-readiness.md)。

手动 GPT Image 图解的离线回归：`uv run --extra dev pytest tests/unit/test_image_diagram*.py`；浏览器交互模型：`node tests/frontend/image_diagrams_behavior.cjs`。覆盖短文直接一次生图、长文一次提炼、方案复用、彻底取消看图模型调用、来源完整性、权限、去重、未知结果不重发、历史版本与两阶段进度。真实 API 调用不包含在离线测试里，参见 [图解指南](../docs/guides/image-diagrams.md)。

项目使用 pytest。开发、测试和输出规则以根目录的 [AGENTS.md](../AGENTS.md) 为唯一事实来源。

## 公共导航与缓存回归

`uv run --extra dev pytest tests/unit/test_frontend_asset_cache.py tests/unit/test_unified_product_shell.py tests/unit/test_product_linear_ui.py tests/unit/test_transcript_mobile_layout.py -q` 验证统一资源版本、公共主题接入、历史页不覆盖导航、旧侧栏状态迁移、静态 200/304/HEAD 再验证，以及 Service Worker 的旧 HTTP 缓存与断网回退。缓存模型可单独运行 `node tests/frontend/service_worker_cache_behavior.cjs`；导航生成后运行 `uv run python scripts/sync_product_navigation.py --check`。这些检查离线运行，不清除实际浏览器缓存、不调用模型。

## 默认验证

SQLite 新安装的隔离全流程回归：

```bash
uv run --extra dev pytest --noconftest -p no:cacheprovider tests/integration/test_sqlite_learning_flow.py -q
```

该测试使用临时源码、私有配置、空数据与随机本机端口，阻止外部网络。仅模拟 LLM 的返回结果，真实验证文字提交、后台任务、SQLite 与文件产物、页面、导出、笔记、合集、纯文本阅读及第二进程重启后的持久化；不使用实际 PostgreSQL、用户资料或付费服务，不代表已验证所有音视频 / OCR / 模型与平台。

配置环境变量与私密文件保护的隔离回归（不加载根 `tests/conftest.py` 的通知初始化）：

```bash
PYTHONPATH=src uv run --extra dev pytest --noconftest tests/unit/test_config_env.py tests/unit/test_config_overrides.py tests/unit/test_public_configuration.py tests/unit/test_settings_service.py tests/unit/test_server_script.py -q
```

覆盖环境变量优先级、模型统一与单独覆盖、配置不落库、设置页脱敏 / 只读、dotenv 端口一致性、不执行环境文件中的 Shell 文本，以及私密 `.env` 变体 / 配置备份 / Cookie 忽略规则。测试使用临时配置和数据库；`tests/test_view_token_fix.py` 已改为临时缓存测试，不再访问真实缓存。企业微信通知已移除，旧兼容入口只返回未发送；三个旧手动脚本仅提示已退役。真实飞书通知测试仅在显式提供 `LEARNFLUX_TEST_FEISHU_WEBHOOK` 时运行；不自动加载根 `.env`，未配置时跳过，不能在默认离线验证中发送消息。

首次安装与开源图文工具的离线检查：

```bash
uv run --extra dev pytest tests/unit/test_init_config.py tests/unit/test_bootstrap_script.py tests/unit/test_readme_demo.py -q
uv run --extra dev pytest tests/integration/test_fresh_install.py -q
```

安装回归在临时目录生成随机配置，验证不覆盖已有设置；隔离启动使用新配置与空数据，并阻止外部请求。截图工具检查未知接口与私有路径无回退、处理和删除被禁用、演示时间与视频跳转契约。截图复现命令与来源见[截图说明](../docs/images/readme-20261103-cases/README.md)，浏览器验收和真实模型调用分别报告。

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

`test_cloud_progress_display.py` 和 `tests/frontend/processing_quote_behavior.cjs` 覆盖确认后清除旧报价阶段、提交结果未知时明确暂停且不重复计费、查看接口按持久云端状态只读展示、报价失败稳定显示及进度请求不重入、不递归。以下检查不提交云端任务：

```bash
uv run --extra dev pytest tests/unit/test_cloud_progress_display.py tests/unit/test_task_state_template_ui.py
```

X 视频分流由 `test_twitter_video.py` 覆盖：帖子含视频、`/video/N`、引用视频、TikHub 两种媒体结构、纯文字帖、播放地址缺失、旧正文缓存隔离及本地/云端转写分流。全部离线模拟；云端流程验证停在费用确认前，不调用付费转写。

```bash
uv run --extra dev pytest tests/unit/test_twitter_video.py tests/unit/test_twitter_deep_learning.py tests/unit/test_twitter_post_fetcher.py
```

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

## 飞书自动归档回归

`uv run --extra dev pytest tests/unit/test_feishu_archive.py` 使用模拟本地 API 和 CLI，覆盖完整正文、安全转义、只处理启用时间后成功的任务、重启去重、回读失败重试、授权拒绝、未知写入结果核对以及截断检测。不会调用飞书或产生解析费用。真实验收需独立授权目标知识库，使用已有完整解析结果创建文档并回读全文，再重复运行确认不产生第二篇。

`test_feishu_delivery.py` 覆盖结果页交付状态、任务与归档身份隔离、安全重试；归档回归还覆盖原生链接语义、更新基准版本、文字/格式/图片保护，以及未知更新结果不可认领人工富内容。测试只用临时数据库和模拟 CLI。

## 核心质量回归

```bash
uv run --extra dev pytest tests/unit/test_task_queue_reliability.py tests/unit/test_cache_task_recovery.py tests/unit/test_study_evidence.py tests/unit/test_study_body_search.py tests/unit/test_history_routes.py tests/unit/test_study_routes.py tests/unit/test_feishu_archive.py tests/unit/test_feishu_delivery.py tests/unit/test_evidence_delivery_browser_behavior.py
```

任务用例覆盖乱序失败归属、有界队列、满载拒绝、最多三次本地恢复、身份/取消/付费保护。检索用例覆盖长课尾部、片段上下文上限、无依据问题、实际来源编号、2–5份资料对照、正文分页与缓存失效。前端用例覆盖来源定位、远端文字安全、身份切换后的旧请求隔离和有限重试。全部为离线模拟，不调用模型或外部内容平台；真实生成质量和模型耗时应单独说明。

`uv run --extra dev pytest tests/unit/test_feishu_documents.py tests/unit/test_url_parser.py` 覆盖飞书 Wiki/Docx 身份、可信主机、完整读取及原始快照、视觉内容提示、CLI/权限失败、缓存前身份限制，以及正文直接进入文字学习而不进入下载/ASR。全部使用模拟 CLI 和临时数据，不登录或调用飞书，也不调用 AI 模型。

## 首页任务状态回归

`test_cloud_pricing.py`、`test_cloud_asr_config.py` 覆盖官方价格解析、后台刷新失败沿用旧值、旧核验日期正常报价；`test_asr_retry.py`、`test_cloud_retry_retention.py` 覆盖音频身份、24 小时保留、并发重试、任务归属、防重复云端提交和真实任务存储的重试标记；`test_local_whisper_runtime.py` 覆盖长音频时限与安全错误提示。均使用离线模拟，不提交付费任务。

`tests/unit/test_task_status_frontend.py` 调用 Node.js DOM 行为检查，覆盖阶段与进度、缺失进度、任务链接编码、远端文本安全、刷新时保留详情及焦点、费用确认、本地切换、失败重试和转录方式偏好。所有 API 均为模拟，不产生转录费用。

```bash
node tests/frontend/task_status_behavior.cjs
```


## 小红书解析回归

以下离线用例覆盖登录页包装的短链接、签名保留、可信主机校验、App V2 视频/图文识别、签名 Web V3 备用接口、HTTP 200 内的上游错误，以及统一的笔记身份和缓存。不会触达 TikHub 或付费转录服务。

```bash
uv run --extra dev pytest tests/unit/test_xiaohongshu_urls.py tests/unit/test_xiaohongshu_api.py tests/unit/test_xiaohongshu_downloader.py tests/unit/test_url_parser.py tests/unit/test_xiaohongshu_deep_learning.py tests/unit/test_xiaohongshu_post_fetcher.py tests/unit/test_flywheel_url_normalization.py
```

真实验收须另行检查可访问的原链接、视频下载、非空逐字稿和 AI 解读；通过模拟用例不代表远端接口始终可用。

## 北京时间回归

```bash
uv run --extra dev pytest tests/unit/test_timezone.py tests/unit/test_api_routes.py tests/unit/test_history_routes.py tests/unit/test_learning_collections.py
node tests/frontend/timezone_behavior.cjs
```

覆盖无时区 UTC、`Z`、正负偏移、微秒、北京时间跨日、近期任务相对时间及“今天”筛选；前端用北京、UTC、洛杉矶和基里蒂马蒂四种宿主时区重复验证，不调用付费服务。

## 历史记录清理

`uv run --extra dev pytest tests/unit/test_history_removal.py tests/unit/test_history_delete_client.py tests/unit/test_history_browser_behavior.py tests/unit/test_transcription_control_store.py -q` 使用临时数据库或浏览器行为模型，覆盖单条 / 批量移除、归属校验、整批失败不写入、重复提交共用结果链接、刷新与分页、会话缓存失效、取消及失败保留。首页行为可单独运行 `node tests/frontend/home_history_removal_behavior.cjs`。删除确认由两个页面共用 `history-confirm.js` / `history-confirm.css`，使用原生 dialog 焦点隔离、自定义外观和异步确认；默认聚焦取消，Esc、取消和遮罩点击均不得提交删除。历史删除通过 `/api/audit/history/remove` 保存按用户、任务编号隔离的可见性状态，保留解析结果、原始文件和审计记录；与旧的任务及共享缓存清理接口不同。

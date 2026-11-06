# LearnFlux 验证指引

以仓库的 [AGENTS.md](../../../../AGENTS.md) 为准。下面按受影响的链路选检查。回看旧提交时，路径和测试行为以所选快照为准。测试初始化也会加载配置，确认环境隔离后再从仓库根目录运行。

| 链路 | 优先查看 | 有针对性的验证 |
| --- | --- | --- |
| 单篇学习、PDF 提交和重试、资料归属 | `api/routes/study.py`、`api/services/study_access.py` 与实际入口 | `uv run --extra dev pytest tests/unit/test_study_routes.py tests/unit/test_image_diagram_routes.py` |
| 图解和飞书归档 | `image_diagrams/service.py`、`exports/delivery.py`、`exports/feishu.py` 和[飞书归档指南](../../../../docs/guides/feishu-archive.md) | `uv run --extra dev pytest tests/unit/test_image_diagram_service.py tests/unit/test_feishu_archive.py tests/unit/test_feishu_delivery.py` |
| 退役功能及文档 | [文档中心](../../../../docs/README.md)、现行 API 示例、配置模板和退役说明 | 从现行入口找旧字段，按需校验 JSON 和链接。企业微信退役和历史接口脱敏用 `uv run --extra dev pytest tests/unit/test_wechat_notifier.py tests/unit/test_notification_router.py tests/unit/test_history_routes.py` |
| Web 入口和资源缓存 | 共享导航和资源版本规则 | `uv run python scripts/sync_product_navigation.py --check`，相关浏览器行为检查见 [tests/README.md](../../../../tests/README.md) |

Python 模块路径相对 `src/video_transcript_api/`。共享 API、权限、存储或任务逻辑改动前，按项目规则做 GitNexus 影响检查。涉及多个链路的改动完成后，用默认离线套件做合并验证。

项目的三类兼容边界值得在清理时优先确认：

- 任务有持久所有者时使用该字段，历史任务缺少所有者时可按精确审计关联判断。飞书文档身份检查覆盖提交、复用结果链接和后台读取缓存。
- 图解生成和飞书写入结果不明时先核对原结果。飞书正文覆盖依赖已验证的版本，真实文档读回与新写入分别验收。
- 企业微信通知已退役。旧导入、参数和数据库列有兼容职责，现行指南和请求示例只描述可用功能。

# 通知标题与作者的敏感词处理

`risk_control` 默认关闭。启用后，服务启动时会按配置加载敏感词表，飞书任务状态通知可对标题和作者显示文本做敏感词处理。处理时保护链接，转录结果、原文和知识库归档内容保持原样。

配置项 `sensitive_word_urls` 指定词表来源，`cache_file` 指定本机词表缓存。配置格式见[主配置模板](../../config/config.example.jsonc)。

此前用于企业微信通知的流程已退役。旧通知行为见[退役说明](../guides/wechat_notification.md)。

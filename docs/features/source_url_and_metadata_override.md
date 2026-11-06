# 来源链接与元数据覆盖

当原平台链接仍可用于识别视频，但你希望从另一个公开地址下载同一份媒体时，可以在 `POST /api/transcribe` 中同时提供 `url` 和 `download_url`。文件只在本机时，从[单篇深度学习](../guides/product-tour.md)选择「本地文件」上传。

## 请求示例

将示例地址替换成原平台链接和可公开访问的同一份媒体直链。认证方式和响应见 [API 快速开始](../guides/api/quickstart.md#1-提交转录任务)。

```json
{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "download_url": "https://cdn.example.com/video.mp4",
  "metadata_override": {
    "title": "自定义标题",
    "author": "原作者",
    "description": "内容说明"
  }
}
```

- `url` 用于识别来源、读取平台元数据和复用同源缓存。
- `download_url` 可省略。提供时，媒体由该地址下载，跳过平台字幕获取和平台下载路径。直链必须是公开的 HTTP(S) 地址，服务会拦截本机和内网地址。
- `metadata_override` 可单独使用。填写的非空字段会覆盖平台返回的同名字段，也可以补上缺失字段。平台元数据读取失败时，已填写的字段仍可作为来源信息。

同一个平台来源可能复用已有转录结果。请让 `url` 与 `download_url` 指向同一份内容，避免给不同媒体复用同一个来源标识。

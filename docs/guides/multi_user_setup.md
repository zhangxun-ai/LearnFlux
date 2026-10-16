# 多用户 Token 配置

LearnFlux 支持通过本机 `config/users.json` 为调用方配置独立的静态 Bearer Token，适用于个人自托管实例中的少量可信使用者。此模式只提供静态 Token 管理，不含用户注册、计费或团队角色功能。

## 1. 创建用户文件

复制仓库提供的空模板：

```bash
cp config/users.example.json config/users.json
```

在 `users` 对象中，为每位调用方添加一条配置。对象键就是对方使用的 API Token：

```json
{
  "users": {
    "REPLACE_WITH_A_RANDOM_TOKEN": {
      "user_id": "user_001",
      "name": "使用者名称",
      "enabled": true
    }
  }
}
```

将占位键替换成随机 Token，例如使用 `openssl rand -hex 32` 生成。`user_id` 和 `name` 必填；`enabled` 默认为启用。不要把示例占位符当成真实 Token 使用。

`config/users.json` 含有可直接访问 API 的凭据。它默认被 Git 忽略，应限制本机文件权限，且不要提交到仓库或发到聊天、截图和日志中。轮换 Token 时，替换对应对象键并重启服务。

## 2. API 调用

客户端通过标准 Bearer Token 认证。将 `<USER_TOKEN>` 替换成该用户的随机 Token：

```bash
curl -X POST "http://localhost:8000/api/transcribe" \
  -H "Authorization: Bearer <USER_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=VIDEO_ID"}'
```

每位用户的任务会按 `user_id` 记录。

## 3. 单 Token 回退

`config/config.jsonc` 中的 `api.auth_token` 仍用于 Web 管理和兼容旧客户端；当前用户管理器也会接受它作为回退 Token。因此，创建 `users.json` 后这个管理口令仍可访问 API，不要分发给普通调用方。当前配置不支持单独关闭它的 API 回退能力。

如果没有 `config/users.json`，服务继续使用 `api.auth_token` 的单 Token 模式。空的 `users` 对象也会回退到单 Token 模式。

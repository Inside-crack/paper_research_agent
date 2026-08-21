# P36 Chat CLI 与 HTTP API

**目标**：提供真正的持续对话入口。

## 范围

- `chat` CLI：持续读取用户消息并维护 session。
- HTTP `POST /sessions`、`POST /sessions/{id}/messages`、`GET /sessions/{id}`。
- SSE 或 WebSocket 事件流。
- request_id 幂等、session 隔离、鉴权扩展点。
- 保留现有一次性 `run` CLI 兼容。

## 验收标准

- [ ] 用户可连续发送多条消息。
- [ ] session 可恢复并继续关联 task。
- [ ] 消息接口可返回澄清、等待、运行和完成状态。
- [ ] 客户端可订阅 Workflow 进度。
- [ ] 重复 request_id 不重复执行 Workflow。

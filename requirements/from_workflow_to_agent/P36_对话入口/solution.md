# P36 对话入口

## 一、目标和意义

P31-P35 已经提供了 Session、Router、ApplicationService、Workflow、事件流和
回复编排，但这些能力还主要存在于进程内服务和 CLI 中。P36 将它们暴露为稳定的
持续对话入口，使用户可以在同一个 Session 中多轮交互，并在断线后恢复任务。

核心闭环：

```text
创建 Session
  -> 发送消息
  -> 澄清/选择/确认
  -> 创建或恢复 Task
  -> 接收 Workflow 进度
  -> 查询状态和 Artifact
  -> 暂停/恢复/取消
```

P36 的目标是**最小可用闭环**，不是一次完成生产级分布式平台。多进程任务队列、
分布式锁、正式用户体系、限流和部署编排属于后续需求。

## 二、职责边界

```text
ConversationApplicationService：会话和任务业务编排
EventPublisher/EventStore：事件发布、持久化和查询
ResponseComposer：事件到用户回复的转换
P36 Gateway：HTTP/CLI 协议、连接生命周期、请求幂等和鉴权扩展点
```

P36 不直接调用 Workflow、Capability 或 Tool，不重复实现 Session 状态机，也不
重新定义 P35 的事件格式。

## 三、子需求清单

### P36-1：持续 Chat CLI

**意义**：提供无 HTTP 依赖的端到端交互入口，验证多轮 Session 和控制命令。

**技术方案**：

- 保留现有 `run` CLI，不改变一次性任务行为；
- `chat` 持续读取多条消息并复用同一个 `session_id`；
- 支持 `/status`、`/confirm`、`/pause`、`/resume`、`/cancel`、`/events`；
- 使用 `CliProgressSubscriber` 输出 P35 安全进度事件；
- 支持通过 `--session-id` 恢复已有 Session；
- 每次输入都调用 `ConversationApplicationService`，CLI 不直接操作 Task。

### P36-2：Session API

**意义**：为 Web、脚本和后续 UI 提供统一的会话生命周期入口。

**接口**：

```text
POST /sessions
GET  /sessions/{session_id}
DELETE /sessions/{session_id}       可选关闭会话
```

`POST /sessions` 返回：

```json
{
  "session_id": "session-1",
  "status": "active",
  "created_at": "...",
  "active_task_id": null
}
```

`GET` 返回 Session 状态、当前 Task 引用、上下文摘要和最近消息，但不返回密钥、
内部绝对路径、完整 Prompt 或未经授权的其他 Session 数据。

### P36-3：Message API 和多轮对话

**意义**：让用户可以在同一个 Session 中连续发送检索、选择、确认、查询和控制
消息，形成真正的多轮闭环。

**接口**：

```text
POST /sessions/{session_id}/messages
```

请求：

```json
{
  "content": "处理第 2 篇论文",
  "request_id": "req-123"
}
```

响应复用 P34/P35 结构：

```json
{
  "session_id": "session-1",
  "task_id": "task-1",
  "status": "waiting_confirmation",
  "reply": "该操作将启动完整论文处理流程，请确认后继续。",
  "confirmation_token": "...",
  "correlation_id": "req-123"
}
```

响应至少覆盖：

```text
waiting_user_input
waiting_confirmation
running
paused
cancelled
completed
failed
```

### P36-4：request_id 幂等

**意义**：客户端重试、网络超时或 SSE 重连不能导致重复消息、重复 Task 或重复
Workflow 执行。

**技术方案**：

- `request_id` 在同一 Session 内必须唯一；
- 持久化 `session_id + request_id -> response`；
- 首次请求成功或失败后都保存最终响应；
- 相同 request_id 和相同请求内容直接返回原响应；
- 相同 request_id 但请求内容不同返回 `409 request_id_reused`；
- 持久化检查和首次执行需要进程内锁；
- 当前阶段使用 JSON 持久化，后续多进程部署迁移到数据库唯一约束。

幂等范围覆盖 `messages`、`confirm`、`pause`、`resume` 和 `cancel`。

### P36-5：Session 隔离与鉴权扩展点

**意义**：HTTP 入口不能因为知道另一个 Session ID 就读取或控制其任务。

**技术方案**：

- Gateway 提取 `principal_id`，当前阶段允许使用匿名 principal；
- 持久化 Session owner/principal 字段或通过扩展接口解析；
- 每个请求校验 `principal_id -> session_id`；
- Task 操作继续复用 P34 的 Session/Task 双向绑定；
- 未授权访问统一返回 `404` 或 `403`，不泄露目标 Session 是否存在；
- 抽象 `Authenticator` Protocol，后续接入 JWT/API Key 不修改应用服务。

### P36-6：SSE Workflow 事件流

**意义**：长任务需要实时反馈，而不是让客户端轮询或等待最终结果。

**接口**：

```text
GET /sessions/{session_id}/events
GET /sessions/{session_id}/tasks/{task_id}/events
```

**技术方案**：

- 使用 `text/event-stream`；
- 首次连接先从 EventStore 按 `Last-Event-ID` 补发历史事件；
- 然后订阅进程内 `EventPublisher`；
- 事件内容直接使用 P35 `AgentEvent.model_dump(mode="json")`；
- 服务端发送 `event: agent_event`、`id: event_id` 和 `data: ...`；
- 心跳注释定期发送，断开连接自动解绑；
- Session/Task 校验后才能订阅；
- 事件过滤和敏感信息过滤仍由 P35 负责。

WebSocket 不作为 P36 第一阶段必需项，避免同时维护两套事件协议。

### P36-7：HTTP 错误和状态映射

**意义**：客户端需要区分用户输入错误、状态冲突、鉴权失败、服务异常和任务失败。

**统一错误结构**：

```json
{
  "error": "invalid_state_transition",
  "message": "当前任务无法恢复",
  "request_id": "req-123",
  "correlation_id": "corr-123"
}
```

**建议映射**：

```text
400 invalid_request / invalid_content
401 authentication_required
403 session_forbidden
404 session_not_found / task_not_found
409 request_id_reused / invalid_state_transition / duplicate_execution
422 invalid_confirmation
500 internal_error
503 event_stream_unavailable
```

内部异常只记录到服务日志和错误 Artifact，不能直接返回 traceback。

### P36-8：异步任务和连接生命周期

**意义**：HTTP 请求不能因为 Workflow 长时间执行而一直占用连接，也不能因为
客户端断开就丢失任务。

**技术方案**：

- `POST messages` 负责持久化消息并返回 `running`；
- Workflow 在应用服务管理的后台执行句柄中运行；
- SSE 只订阅事件，不拥有 Task 的执行权；
- HTTP 连接断开不取消 Task；
- pause/resume/cancel 通过应用服务发出协作式控制请求；
- 服务重启后通过 Session 的 active task 和 checkpoint 恢复；
- 当前阶段限定为单进程生命周期，生产多 worker 需要外部任务执行器。

### P36-9：CLI/API 兼容与运行配置

**意义**：增加 HTTP 入口不能破坏既有开发、测试和一次性任务使用方式。

**技术方案**：

- `run`、`task resume` 保持原参数和输出兼容；
- 新增 `serve` 命令启动 HTTP 服务；
- FastAPI、Uvicorn 作为 `web` 可选依赖；
- 应用工厂支持测试注入 Store、ApplicationService、EventPublisher 和
  Authenticator；
- Host、Port、artifact 根目录、日志级别通过 Settings 配置；
- 不在模块导入时启动服务器。

### P36-10：端到端、幂等和恢复测试

**意义**：P36 同时涉及协议、持久化、异步执行和权限边界，必须验证真实闭环和
断线恢复，而不是只测试单个 handler。

**测试范围**：

- 连续消息共享同一个 Session；
- 候选选择、确认、任务启动和完成；
- 明确 arXiv URL 快速启动；
- Session 重载后继续查询和控制 Task；
- 重复 request_id 不重复执行；
- request_id 重用不同内容返回 409；
- 跨 Session 访问被拒绝；
- SSE 历史补发和实时事件；
- `Last-Event-ID` 断线续传；
- pause/resume/cancel 事件和状态；
- 连接断开不取消后台 Task；
- HTTP 错误结构和敏感信息过滤；
- `run` CLI 回归；
- P31-P35 全量回归。

## 四、推荐实施顺序

```text
P36-1 Chat CLI 收尾
  -> P36-2 Session API
  -> P36-3 Message API
  -> P36-4 request_id 幂等
  -> P36-5 Session 隔离/鉴权扩展点
  -> P36-7 HTTP 错误映射
  -> P36-8 异步任务生命周期
  -> P36-6 SSE 事件流
  -> P36-9 serve 命令和配置
  -> P36-10 端到端验收
```

## 五、验收标准

- [x] 用户可以在同一 Session 连续发送多条消息。
- [x] Session 重启或重新加载后可以继续关联原 Task。
- [x] Message API 可返回澄清、等待确认、运行、暂停、完成和失败状态。
- [x] 客户端可以订阅并续传 Workflow 进度事件。
- [x] 重复 request_id 不会重复执行 Workflow。
- [x] 跨 Session 读取和控制被拒绝。
- [x] HTTP 错误不泄露 traceback、密钥和绝对路径。
- [x] SSE 连接断开不会取消后台任务。
- [x] 现有 `run` CLI 保持兼容。
- [x] P31-P35 全量回归通过。

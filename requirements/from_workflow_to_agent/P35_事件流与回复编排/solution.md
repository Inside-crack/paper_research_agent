# P35 事件流与回复编排

## 一、目标和核心边界

P35 将 Orchestrator、Workflow 和 ConversationApplicationService 的内部执行过程
转换成可持久化、可订阅、可查询的事件，并生成用户可理解的回复。

```text
Orchestrator / Workflow / ApplicationService
  -> AgentEvent
  -> EventPublisher
  -> EventStore / Subscriber
  -> ResponseComposer
  -> CLI / 后续 HTTP API
```

职责边界：

```text
P34 ConversationApplicationService：任务启动、确认、暂停、恢复、取消和状态迁移
P35 Event System：过程事件、事件查询、实时发布和用户回复编排
P33 Workflow：论文业务步骤和产物生成
P36 Chat/API：对外传输和持续连接
```

P35 不重新实现 P34 状态机，不直接执行 Capability/Tool，也不把回复文本逻辑放入
Orchestrator 或 Workflow。

## 二、子需求清单

### P35-1：统一 AgentEvent 数据模型

**意义**：为 CLI、未来 HTTP API、审计和测试提供统一事件契约，避免各层使用不同
的日志格式。

**技术方案**：

当前实现位于 `src/paper_agent/common/response_composer.py`，并通过
`ConversationApplicationService.compose_event_response()` 提供应用层入口。
该组件只转换事件，不修改 Session、Task 或 Workflow 状态。

新增 `AgentEvent` 模型：

```python
AgentEvent(
    event_id,
    event_type,
    session_id,
    task_id,
    correlation_id,
    timestamp,
    payload,
)
```

要求：

- `event_id` 全局唯一；
- `event_type` 使用白名单枚举；
- `session_id`、`correlation_id` 必填；Task 创建前的事件允许 `task_id` 为空；
  Task 创建后的 Workflow 事件必须携带 `task_id`；
- `timestamp` 使用带时区的 UTC 时间；
- `payload` 只保存结构化、可序列化数据；
- 未知字段拒绝写入，保证事件契约稳定。

### P35-2：事件类型和生命周期

**意义**：统一表达从用户请求到任务完成的完整过程，使长任务进度可观察。

**首批事件类型**：

```text
intent_detected
candidate_found
workflow_started
step_started
step_completed
artifact_created
evaluation_completed
task_paused
task_resumed
task_cancelled
task_completed
task_failed
response_ready
```

每类事件定义固定 payload schema。例如：

```text
step_started:
  phase
  step_id
  step_index
  total_steps

step_completed:
  phase
  step_id
  success
  artifact_refs
  error_code
```

### P35-3：EventPublisher 发布接口

**意义**：将事件产生方与持久化、实时订阅方解耦。

**技术方案**：

```python
class EventPublisher(Protocol):
    def publish(self, event: AgentEvent) -> None:
        ...
```

发布器支持多个 sink：

```text
EventPublisher
  -> PersistentEventStore
  -> InMemorySubscriber
  -> CLI progress adapter
```

核心状态事件写入失败必须向上抛出；纯实时订阅失败可以记录告警，不阻断主任务。

### P35-4：事件持久化

**意义**：支持进程重启后的历史查询、审计、任务恢复和问题排查。

**技术方案**：

沿用项目 JSONL 持久化约定：

```text
artifacts/<task_id>/logs/events.jsonl
```

新增：

```python
class EventStore(Protocol):
    def append(self, event: AgentEvent) -> None:
        ...

    def list(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
    ) -> list[AgentEvent]:
        ...
```

要求：

- 一行一个完整 JSON 事件；
- 追加写入并 flush；
- 支持按 Session、Task 和 correlation 查询；
- 空行可以跳过，损坏事件必须报告文件和行号；
- 不允许事件日志路径为 symlink；
- 事件文件只保存 artifact 相对引用。

### P35-5：ApplicationService 事件接入

**意义**：让用户请求和交互状态变化进入同一事件链。

**接入点**：

- Router 返回决策后发布 `intent_detected`；
- 产生候选集后发布 `candidate_found`；
- 创建 Task 前后发布 `workflow_started`；
- pause/resume/cancel 后发布对应生命周期事件；
- 生成最终回复后发布 `response_ready`。

`correlation_id` 在一次 `handle_message`、`confirm`、`pause` 或 `resume` 调用中
保持不变，并写入相关 assistant message metadata。

### P35-6：Orchestrator/Workflow 事件接入

**意义**：将论文处理过程中的 phase、substep 和产物变化暴露给用户。

**技术方案**：

- Orchestrator 负责 phase 开始、phase 完成、evaluation 和 task 终态事件；
- `PaperProcessingWorkflow` 负责 download、parse、glossary、translate、summary
  的 step 开始/完成事件；
- 产物保存成功后发布 `artifact_created`；
- 事件中的错误使用结构化 `error_code` 和安全摘要，不直接写完整 traceback。

已有 `TaskJsonLogger` 可以作为底层日志实现，但 P35 事件必须使用统一
`AgentEvent` schema，不能让调用方解析旧日志文本。

### P35-7：实时订阅和进度查询

**意义**：长任务不能只在结束后返回结果，用户需要看到当前阶段和下一步。

**技术方案**：

当前实现位于 `src/paper_agent/common/events.py` 的
`CliProgressSubscriber`。Chat 会话启动时订阅当前 `session_id` 的事件，退出时
自动解绑；`/events` 通过 EventStore 查询该会话的历史事件。实时输出和历史查询
都使用 `ResponseComposer` 生成的安全回复。

```python
class EventSubscriber(Protocol):
    def on_event(self, event: AgentEvent) -> None:
        ...
```

第一阶段使用进程内订阅器，供 CLI 使用；历史事件从 EventStore 查询。后续 P36
通过 SSE/WebSocket 将订阅器接到 HTTP 连接。

进度信息统一包含：

```text
phase
step_id
completed_steps
total_steps
status
```

### P35-8：ResponseComposer

**意义**：统一成功、失败、澄清、等待确认、暂停和完成等用户回复，避免每个调用方
手写文案并泄露内部细节。

**技术方案**：

```python
class ResponseComposer:
    def compose(
        self,
        event: AgentEvent,
        *,
        context: ConversationContext | None = None,
    ) -> ComposedResponse:
        ...
```

统一回复结构：

```python
ComposedResponse(
    session_id,
    task_id,
    status,
    message,
    next_actions,
    artifact_refs,
    correlation_id,
)
```

回复类型：

```text
progress
clarification
waiting_confirmation
paused
cancelled
completed
failed
```

失败回复必须包含原因摘要、当前状态和可执行的下一步，例如 `resume`、`retry`、
`view_artifact`，但不能暴露内部异常堆栈。

### P35-9：安全过滤和 Artifact 引用

**意义**：事件和回复会被直接展示给用户，必须隔离内部路径、密钥和运行时细节。

**技术方案**：

当前实现位于 `src/paper_agent/common/event_security.py`。`EventPublisher` 在持久化和
通知订阅者前执行过滤，`EventStore` 作为独立写入入口也会再次过滤，避免绕过发布器
直接写入敏感内容。`ResponseComposer` 复用同一过滤规则，并丢弃脱敏后的不安全
Artifact 路径。

- 绝对路径转换为 task-relative artifact 引用；
- 过滤 API Key、Token、Authorization Header；
- 不输出完整 Prompt、宿主目录和内部环境变量；
- traceback 只写入受保护的任务错误产物，回复使用安全摘要；
- `artifact_refs` 必须经过 Manifest 校验后再暴露。

### P35-10：事件查询、回复和回归测试

**意义**：P35 的核心风险是事件丢失、关联错误、错误信息泄露和进度顺序不稳定，
必须同时覆盖正向和负向场景。

**测试范围**：

- AgentEvent 序列化和反序列化；
- 缺失关联字段被拒绝；
- 非法 event_type 被拒绝；
- JSONL 追加、读取和损坏行处理；
- 按 session/task/correlation 查询；
- Workflow 每个边界事件都可关联；
- 事件顺序和重复事件策略；
- 实时订阅收到事件；
- ResponseComposer 的成功、等待、暂停、取消和失败回复；
- 回复不包含绝对路径、密钥和 traceback；
- EventStore 写入失败的主流程处理；
- P31-P34 全量回归。

## 三、推荐事件序列

```text
intent_detected
  -> candidate_found
  -> workflow_started
  -> step_started
  -> step_completed
  -> artifact_created
  -> evaluation_completed
  -> response_ready
```

暂停、恢复、取消和失败属于分支终态：

```text
task_paused
  -> task_resumed
  -> workflow_started

task_failed
task_cancelled
task_completed
```

## 四、事件序列化格式决策

CLI 和未来 HTTP API 统一使用同一份 `AgentEvent.model_dump(mode="json")` 结果。
CLI 只负责格式化展示，HTTP 层只负责传输，不重新定义字段。

这解决 B35-1：事件 JSON schema 作为内部和外部接口的共同基础，后续通过
`event_type` 和 `payload` 扩展，不改变顶层关联字段。

## 五、推荐实施顺序

```text
P35-1 AgentEvent 模型
  -> P35-2 事件类型和 payload schema
  -> P35-4 EventStore
  -> P35-3 Publisher/Subscriber
  -> P35-5 ApplicationService 接入
  -> P35-6 Orchestrator/Workflow 接入
  -> P35-8 ResponseComposer
  -> P35-7 CLI 实时进度
  -> P35-9/P35-10 安全和验收测试
```

## 六、验收标准

- [x] 每个 Workflow phase 和 paper processing substep 边界产生事件。
- [x] 每个事件带 `session_id`、`correlation_id` 和 UTC timestamp；Task 创建后事件带 `task_id`。
- [x] 事件可持久化，并支持按 Session、Task 和 correlation 查询。
- [x] CLI 和未来 HTTP API 使用同一事件序列化格式。
- [x] 长任务可通过订阅器输出实时进度。
- [x] `ResponseComposer` 覆盖成功、澄清、等待、暂停、取消和失败回复。
- [x] 失败回复包含原因、当前状态和可执行下一步。
- [x] 回复可引用 artifact，但不暴露内部绝对路径。
- [x] 事件损坏、持久化失败和非法关联字段有明确负向测试。
- [x] P31-P34 全量回归通过。

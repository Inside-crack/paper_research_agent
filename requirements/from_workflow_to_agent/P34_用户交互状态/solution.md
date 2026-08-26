# P34 对话应用服务与用户交互状态

## 目标

承接 P32 的路由决策，调用 Capability/Workflow，并支持候选确认、补充信息、
暂停、继续和取消。

P34 的核心边界是：

```text
ConversationApplicationService：交互流程编排
Orchestrator：任务生命周期、状态迁移和 checkpoint
Workflow：论文业务流程
Persistence：任务和会话的恢复源
```

## 一、需求范围

### P34-1：交互状态模型

**意义**：统一表达会话当前处于等待输入、等待确认、执行中、暂停或结束等状态，
避免 CLI、应用服务和任务状态各自维护不同状态。

**技术方案**：

- 扩展 `ConversationSession.status`。
- 支持 `active`、`waiting_user_input`、`waiting_confirmation`、`running`、
  `paused`、`cancelled`、`completed`、`failed`、`closed`。
- 增加状态转移校验，禁止非法状态跳转。
- 保留现有小写字符串，兼容历史 JSON 数据。

### P34-2：ConversationApplicationService

**意义**：建立应用层，统一编排 Session、消息、Router、Capability、Orchestrator
和 Workflow，避免 CLI 直接拼接业务流程。

**技术方案**：

新增：

```text
src/paper_agent/common/conversation_application_service.py
```

核心接口：

```python
handle_message(session_id, content)
confirm(session_id, confirmation_token)
pause(session_id)
resume(session_id)
cancel(session_id)
get_status(session_id)
```

现有 `ConversationService` 保留路由和能力执行职责，或作为兼容 facade，避免一次性
破坏现有调用方。

### P34-3：待确认动作持久化

**意义**：涉及完整论文处理、下载或其他高成本操作时，必须记录等待用户确认的具体
动作，不能只返回一条提示消息。

**技术方案**：

在 `ConversationContext` 增加 `pending_action`，至少包含：

```text
action_id
capability_name
arguments
selected_paper
confirmation_token
created_at
```

确认后清除待确认动作。重复确认同一 token 必须幂等，不能重复创建任务或执行
Workflow。

### P34-4：Session 与 Task 严格绑定

**意义**：防止用户通过错误 Session 操作其他任务，确保上下文、任务状态和产物引用
不会串线。

**技术方案**：

在 `TaskState` 增加兼容字段：

```python
session_id: Optional[str] = None
```

所有任务操作必须校验：

```text
session.active_task_id == task.id
task.session_id == session.session_id
```

需要拒绝不存在的 Session、不存在的 Task、绑定不一致以及跨会话控制请求。

### P34-5：Orchestrator 生命周期拆分

**意义**：当前 `start_task()` 会初始化并立即完整执行，无法支持先确认后启动以及
暂停恢复。

**技术方案**：

新增：

```python
async def create_task(...) -> TaskState
```

该接口只负责创建 `ResearchSpec`、`TaskState`、任务目录、Manifest 和初始
checkpoint。

现有 `start_task()` 保持兼容，并改为：

```text
create_task() -> run()
```

Orchestrator 继续负责任务生命周期，不承载对话路由或确认逻辑。

### P34-6：Task 生命周期状态

**意义**：`TaskPhase` 表示论文研究阶段，不能完整表达暂停、取消和等待执行等任务
生命周期状态。

**技术方案**：

在 `TaskState` 增加：

```python
lifecycle_status: TaskLifecycleStatus = "pending"
control_request: Optional[Literal["pause", "cancel"]] = None
```

明确区分：

```text
current_phase：当前业务阶段
lifecycle_status：任务生命周期
```

旧 checkpoint 缺失字段时使用默认值，保证向后兼容。

### P34-7：受控运行与暂停

**意义**：支持用户暂停长时间运行的论文处理任务，并确保暂停后能够从 checkpoint
恢复。

**技术方案**：

为 Orchestrator 增加协作式控制：

```python
async def run(task_state, control=None) -> None
```

在 phase 开始前、Workflow 子步骤之间和 checkpoint 保存后检查暂停请求。暂停时：

1. 保存最新 `TaskState`；
2. 设置 Task 和 Session 为 `paused`；
3. 阻止后续步骤启动。

不强制中断当前正在执行的 LLM、网络或工具调用。

### P34-8：恢复执行

**意义**：支持暂停、进程重启和故障恢复，并复用现有 checkpoint 和 Workflow 子步骤
状态。

**技术方案**：

1. 根据 Session 获取绑定 Task；
2. 加载最新 checkpoint；
3. 校验 `session_id`；
4. 清除 `control_request`；
5. 设置 Task 和 Session 为 `running`；
6. 调用 Orchestrator 继续执行；
7. 由 `PaperProcessingWorkflow` 跳过已完成子步骤。

### P34-9：取消任务

**意义**：用户取消后，任务不能继续执行后续 Workflow，也不能被普通 resume 意外
重新启动。

**技术方案**：

1. 校验 Session/Task 绑定；
2. 设置 `control_request = "cancel"`；
3. Orchestrator 在安全点发现请求；
4. 保存最终 checkpoint；
5. 设置 Task 和 Session 为 `cancelled`；
6. 关闭运行句柄；
7. 后续 resume 直接拒绝。

取消采用协作式语义，不强杀当前调用。

### P34-10：执行句柄与并发保护

**意义**：防止同一个 Task 被重复确认、重复 resume 或同时运行，造成重复下载、重复
翻译和状态覆盖。

**技术方案**：

`ConversationApplicationService` 维护进程内执行句柄：

```text
task_id -> asyncio.Task
```

启动前检查 Task 是否已运行、confirmation token 是否已执行，以及 Task 是否已进入
terminal 状态。持久化状态仍是恢复源，内存句柄只负责当前进程内的并发控制。

### P34-11：Session 状态同步

**意义**：用户查询 Session 时可以直接知道任务是否运行、暂停、完成或失败，不必
手动读取 TaskState。

**技术方案**：

任务状态变化时同步更新：

```text
Task.lifecycle_status
ConversationSession.status
ConversationSession.updated_at
ConversationSession.active_task_id
```

状态映射：

```text
completed -> completed
failed    -> failed
cancelled -> cancelled
paused    -> paused
running   -> running
```

核心状态持久化失败必须向上抛出，不能只记录日志。

### P34-12：CLI 接入

**意义**：让现有 CLI 使用应用层入口，验证应用层设计能够复用，而不是新增孤立
服务。

**技术方案**：

将 `cmd_chat()` 从直接调用 `ConversationService.handle_message()` 改为调用
`ConversationApplicationService.handle_message()`，并补充：

```text
confirm
pause
resume
cancel
status
```

现有 `run` 和 `task resume` 命令保持兼容。

### P34-13：错误与恢复语义

**意义**：保证路由失败、确认失效、任务异常、持久化失败和状态冲突都能得到明确
结果。

**技术方案**：

统一返回结构：

```python
{
    "session_id": "...",
    "task_id": "...",
    "status": "...",
    "reply": "...",
    "error": "...",
}
```

重点错误包括：

```text
session_not_found
task_not_found
session_task_mismatch
invalid_state_transition
confirmation_expired
duplicate_execution
task_not_resumable
persistence_failed
```

### P34-14：测试与验收

**意义**：P34 涉及多个持久化对象和状态迁移，必须验证负向路径与恢复语义，不能
只测试正常聊天流程。

**技术方案**：

- 状态机合法和非法迁移；
- 待确认动作持久化；
- 重复确认幂等；
- Session/Task 绑定校验；
- 确认前不会启动 Workflow；
- pause 保存 checkpoint；
- resume 跳过已完成步骤；
- cancel 阻止后续步骤；
- Workflow 异常进入 `failed`；
- 任务完成进入 `completed`；
- P31、P32、P33 回归测试。

## 二、核心调用链

```text
ConversationMessage
  -> IntentRouter
  -> CapabilityDecision
  -> ConversationApplicationService
  -> Capability Adapter / Orchestrator
  -> PaperProcessingWorkflow
  -> 更新 Session、Task、Manifest、Checkpoint
```

P32 不直接执行，P33 只提供 Workflow，因此 P34 负责把路由结果连接到实际执行。

## 三、状态转移

```text
active
  -> waiting_user_input
  -> waiting_confirmation
  -> running

waiting_confirmation
  -> running
  -> active

running
  -> paused
  -> cancelled
  -> completed
  -> failed

paused
  -> running
  -> cancelled

completed / failed / cancelled / closed
  -> terminal
```

## 四、推荐实施顺序

```text
P34-1 状态模型
  -> P34-3 待确认动作
  -> P34-4 Session/Task 绑定
  -> P34-5 Orchestrator 生命周期拆分
  -> P34-6/P34-7 受控运行
  -> P34-8/P34-9 恢复与取消
  -> P34-2 ApplicationService
  -> P34-10/P34-11 并发与状态同步
  -> P34-12 CLI
  -> P34-13/P34-14 错误与测试
```

## 五、总体验收标准

- [ ] 检索候选后等待用户选择，不自动使用第一篇。
- [ ] 用户选择后只绑定指定论文。
- [ ] 缺少年份、论文或翻译范围时进入等待输入。
- [ ] 明确提供论文 ID/URL 时允许跳过确认。
- [ ] 暂停后不再启动后续工具或 Workflow 子步骤。
- [ ] 恢复从最新 checkpoint 和子步骤状态继续。
- [ ] 取消后不可继续执行当前任务。
- [ ] Router 返回的 CapabilityDecision 能被 ApplicationService 执行。
- [ ] CapabilityResult 能更新 Session、Task 和等待状态。
- [ ] 无可执行能力时只返回澄清或前置条件缺失，不启动任务。
- [ ] Session 与 Task 始终严格绑定。
- [ ] 重复确认和重复恢复不会造成重复执行。
- [ ] P31、P32、P33 全部回归通过。

## 六、已确认决策

| 决策 | 结论 |
|------|------|
| R34-1 | 明确论文 ID/URL 可跳过确认；检索候选默认必须确认 |
| R34-2 | pause/cancel 采用协作式控制，在安全点生效，不强制中断当前调用 |

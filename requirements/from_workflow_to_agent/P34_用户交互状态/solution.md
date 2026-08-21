# P34 对话应用服务与用户交互状态

**目标**：承接 P32 的路由决策，调用 Capability/Workflow，并支持候选确认、补充信息、暂停、继续和取消。

## 范围

- 增加 `WAITING_USER_INPUT`、`WAITING_CONFIRMATION`、`PAUSED`、`CANCELLED`。
- 新增 `ConversationApplicationService`，连接 Session、Router、CapabilityRegistry 和 Orchestrator/Workflow。
- 实现 P09 候选论文确认。
- 明确提供论文 ID/URL 时允许跳过确认。
- 支持 task pause/resume/cancel。
- 状态和等待原因写入 TaskState、Manifest、Checkpoint。

## 核心调用链

```text
ConversationMessage
  -> IntentRouter
  -> CapabilityDecision
  -> ApplicationService
  -> Capability Adapter / Workflow
  -> 更新 Session 和 Task
```

P34 是“路由结果如何真正产生执行”的边界。P32 不直接执行，P33 只提供
Workflow，因此 P34 负责把二者连接起来。

## 验收标准

- [ ] 检索候选后可等待用户选择，不自动使用第一篇。
- [ ] 用户选择后只绑定指定论文。
- [ ] 缺少年份、论文或翻译范围时进入等待输入。
- [ ] 暂停后不再调用工具，恢复从边界继续。
- [ ] 取消后不可继续执行当前 run。
- [ ] Router 返回的 CapabilityDecision 能被 ApplicationService 执行；
- [ ] CapabilityResult 能更新 Session、Task 和等待状态；
- [ ] 无可执行能力时只返回澄清或前置条件缺失，不启动任务。

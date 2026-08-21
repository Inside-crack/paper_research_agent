# From Workflow To Agent 架构决策

**决策数量**：5  
**最后更新**：2026-08-21

| 决策 | 内容 | 结论 |
|------|------|------|
| R01 | 是否重写现有 Orchestrator | 不重写，保留为执行内核并逐步收敛为生命周期控制器 |
| R02 | Agent 是否直接调用底层 Tool | 不直接调用；先选择 Capability，由 Capability Adapter 调用 Tool，由 Workflow 调用多步骤流程 |
| R03 | Task 与 Conversation 是否合并 | 不合并，Task 负责执行，Session 负责会话 |
| R04 | 论文是否默认选择第一篇 | 只有用户明确指定论文时跳过确认，否则进入 P09 选择 |
| R05 | 迁移顺序 | P31 会话模型 -> P32 能力契约与 Adapter/Registry/Router -> P33 Workflow -> P34 应用服务与交互状态 -> P35 事件/回复 -> P36 Chat 入口 |
| R06 | 已有 Tool 如何进入对话 Agent | 先通过 Capability Adapter 包装为完整输入/输出单元，再注册和路由；不直接把 ToolRegistry 暴露给 Agent |
| R07 | Router 决策如何触发执行 | P32 只产生 CapabilityDecision，P34 ConversationApplicationService 负责调用 Adapter/Workflow 并更新 Task/Session |

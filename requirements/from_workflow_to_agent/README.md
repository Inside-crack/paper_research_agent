# From Workflow To Agent

本目录记录项目从“单次任务型论文工作流”演进为“可持续多轮对话 Agent”所需的架构改进。

## 当前判断

项目当前已经具备：

```text
Research Agent + Evaluation Agent + Orchestrator
  -> 任务状态机
  -> 论文检索
  -> P10-P14 论文获取、解析、术语、翻译和总结
```

但当前入口仍是一次性 CLI 任务，缺少会话、意图路由、用户确认和自然语言回复。

## 需求范围

- [solution.md](solution.md)：问题审计、解决方案和目标架构。
- [progress.md](progress.md)：改进进度。
- [blockers.md](blockers.md)：当前架构卡点。
- [resolutions.md](resolutions.md)：已确认的架构决策。

## 推荐实施顺序

```text
P31 Conversation Session
  -> P32 Capability Contract / Adapter / Registry / Intent Router
  -> P33 Workflow Module Extraction
  -> P34 Application Service / User Interaction State
  -> P35 Event Stream / Response Composer
  -> P36 Chat CLI / HTTP API
```

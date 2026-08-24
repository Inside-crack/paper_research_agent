# P33 决策

| 决策 | 结论 |
|------|------|
| R33-1 | 先抽取 P30 T2，不同时抽取代码复现等未实现 Workflow |
| R33-2 | 先建立可注入 Workflow seam，默认接入旧 P30 T2 实现，再逐步迁移方法体，避免一次性破坏 Orchestrator 生命周期和 checkpoint 兼容性 |

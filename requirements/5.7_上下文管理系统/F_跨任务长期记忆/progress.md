# F：跨任务长期记忆系统 - 进展

## 当前状态

F01、F02、F03、F08 已实现；F04 基础持久化、索引重建和安全降级接口已接入应用与任务完成 Hook。
F05 确定性去重/更新/合并/冲突保留、F06 关键词召回 MVP 和 F07 Router/ResearchAgent 阶段注入已实现；主动搜索工具和混合检索仍待实现。

## 已完成

- [x] 参考 TencentDB Agent Memory 材料提炼设计原则；
- [x] 明确 L0、L1、L2、L3 与工作记忆边界；
- [x] 明确长期记忆与 `TaskState`、Artifact 的职责分离；
- [x] 拆分 F01-F10 需求；
- [x] 制定 M1-M4 实施里程碑；
- [x] 定义全局非功能要求。
- [x] 实现 `MemoryItem`、`MemoryCandidate` 及相关枚举；
- [x] 实现独立 `MemoryStore`；
- [x] 实现原子 JSON 持久化、幂等写入、Owner 隔离和软删除；
- [x] 增加 F01/F02 专项测试（5/5）；
- [x] 全量测试通过（422 passed）。
- [x] 实现确定性的 `MemoryExtractor` 候选提取入口；
- [x] 提取器过滤未确认推断、一次性内容和未校验事实；
- [x] `MemoryStore` 支持索引损坏后的自动重建；
- [x] `MemoryStore` 增加 `try_save_memory` / `try_save_candidate` 降级接口；
- [x] 模型层强制长期记忆和候选必须包含来源引用；
- [x] F03/F04 增量专项测试通过（9/9）。
- [x] `ConversationApplicationService` 接入用户消息记忆写入 Hook；
- [x] `Orchestrator` 接入任务完成/失败记忆 Hook；
- [x] Hook 写入失败时不改变主流程结果；
- [x] 新增 Hook 回归测试（23/23）。
- [x] 实现持久化 `MemoryJob` 队列；
- [x] 实现后台 Worker、指数退避和 dead-letter；
- [x] 实现进程启动时恢复中断的 `running` 任务；
- [x] 实现每次任务状态变更的 pipeline checkpoint；
- [x] Hook 改为“候选入队”，不等待记忆整合完成；
- [x] 新增队列专项测试（7/7）。
- [x] 完成 F06/F07 召回技术方案设计；
- [x] 确定 `MemoryRecallService`、`IntentContextProjector` 和 `MemoryStore` 的职责边界；
- [x] 确定首期采用确定性关键词召回，后续演进到 FTS5/Embedding/RRF；
- [x] 确定 Owner 隔离、历史参考标记、预算裁剪和故障降级策略；
- [x] 实现 `MemoryRecallQuery`、`MemoryRecallItem`、`RecallResult`；
- [x] 实现 `MemoryRecallService` 确定性关键词召回；
- [x] 将召回结果接入 `IntentContextProjector`；
- [x] 将召回接入 `ConversationService` 和 `ConversationApplicationService` Router 前置流程；
- [x] 新增召回专项测试（4/4）；
- [x] 全量测试通过（437 passed）。
- [x] 实现 `MemoryConsolidator` 的 `store / skip / update / merge`；
- [x] 实现冲突记忆双版本保留和来源记录；
- [x] 实现 superseded 版本链和时间线/Artifact 来源合并；
- [x] 将 F05 Consolidator 接入 MemoryPipeline；
- [x] 新增 F05 专项测试（4/4）。
- [x] 任务启动时保存受限长期记忆快照和 `memory_id` 引用；
- [x] ResearchAgent 阶段重置后注入稳定/动态记忆分区；
- [x] 每个 ResearchAgent 阶段基于阶段和最近摘要动态重新召回；
- [x] REVISE 重置路径保持长期记忆注入；
- [x] 增加阶段注入专项测试（2/2）。

## 待完成

- [x] 设计 `MemoryItem`、`MemoryCandidate` Pydantic 模型；
- [x] 选择首期 SQLite 或原子 JSON 存储方案；
- [x] 设计记忆幂等键和状态转换；
- [x] 增加损坏索引从原始记录重建；
- [x] 将记忆故障降级接入 Conversation/Workflow 主链路；
- [x] 设计 `MemoryExtractor` 接口；
- [x] 设计并实现 `MemoryConsolidator` 接口；
- [x] 设计 `ContextProjection` 的记忆预算字段；
- [x] 实现 `MemoryRecallService`；
- [x] 补充召回单元测试和跨任务集成测试；
- [x] 接入 ResearchAgent 阶段上下文；
- [ ] 实现 SQLite FTS5/Embedding/RRF 混合召回；
- [x] 将稳定记忆与动态记忆分区注入；
- [x] 每个阶段动态重新召回任务相关记忆；
- [x] 实现 M1（L1 基础、持久化、提取和后台写入队列）。

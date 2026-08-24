# P32 进度

**状态**：P32 能力注册与意图路由已完成
**完成度**：T32-0 至 T32-4.10、T32-4.11a/b/c 已实现并通过专项测试；T32-4.11d 待实现

- [x] T32-0：Capability/CapabilityResult/ExecutionContext 最小契约
- [x] T32-0.1：`paper_search` Adapter（`arxiv_search` + `arxiv_get_paper`）
- [x] T32-0.1：参数校验、Tool 失败、输出异常测试
- [x] T32-0.2：`paper_download` Adapter
- [x] T32-0.2：任务上下文、论文上下文和底层失败测试
- [x] T32-0.3：`paper_parse` Adapter
- [x] T32-0.3：任务上下文、artifact 路径、底层失败和输出异常测试
- [x] T32-0.4：`paper_glossary` Adapter
- [x] T32-0.4：任务上下文、术语参数、底层失败和输出异常测试
- [x] T32-0.5：`paper_translate` Adapter
- [x] T32-0.5：任务上下文、译文参数、底层失败和输出异常测试
- [x] T32-0.6：`paper_summary` Adapter
- [x] T32-0.6：任务上下文、总结参数、底层失败和输出异常测试
- [x] T32-0：六个 Adapter 输入/输出和错误传播测试
- [x] T32-1：最小 CapabilityRegistry（注册、解析、启用状态）
- [x] T32-1：六个确定能力统一注册入口
- [x] T32-2：Preconditions 与上下文参数归一化
- [x] T32-3：六个确定能力的确定性路由骨架
- [x] T32-3：路由参数缺失、能力禁用和不支持意图测试
- [x] P31 Session 集成到 ConversationService
- [x] Intent Schema 扩展 capability-specific arguments
- [x] Router 参数缺失和确定性规则基础覆盖
- [x] T32-4：LLM Router JSON Schema 失败处理
- [x] 最小 Chat 闭环测试

## T32-4 复杂意图识别与路由

详细清单：[T32-4_complex_intent_routing.md](T32-4_complex_intent_routing.md)

- [x] T32-4.0：Intent Schema 完整化
- [x] T32-4.0：ContextReference、执行类型、来源和状态校验测试
- [x] T32-4.1：Capability Catalog
- [x] T32-4.1：六个能力元数据、Registry 集成和 Catalog 正反例测试
- [x] T32-4.2：Router Provider 抽象
- [x] T32-4.2：请求/响应契约、Fake Provider 和 LLM 错误传播测试
- [x] T32-4.3：上下文投影
- [x] T32-4.3：消息/候选/Artifact 边界、截断脱敏和跨 Session 反例测试
- [x] T32-4.4：LLM 结构化决策
- [x] T32-4.4：Catalog/Projection/Provider 组装、严格 JSON 和失败降级测试
- [x] T32-4.5：Schema 与能力校验
- [x] T32-4.5：能力白名单、意图/执行类型、输入 Schema 和非法参数测试
- [x] T32-4.6：参数归一化与前置条件
- [x] T32-4.6：候选论文、Artifact、Task 和章节引用解析及缺参阻塞测试
- [x] T32-4.7：混合路由策略
- [x] T32-4.7：确定性优先、缺参不回退、模糊意图委托和 Provider 失败边界测试
- [x] T32-4.7：ConversationService 接入 HybridIntentRouter 和上下文投影
- [x] T32-4.8：澄清与低置信度策略
- [x] T32-4.8：低置信度、缺参、能力不可用、上下文冲突和未知意图测试
- [x] T32-4.9：process_selected_paper Workflow 能力注册与确定性路由
- [x] T32-4.9：Workflow 元数据、前置条件和未配置执行器的阻断测试
- [x] T32-4.10：安全与执行边界
- [x] T32-4.10：能力白名单、Schema、确认状态和路径边界测试
- [ ] T32-4.11：评测与可观测性（T32-4.11a/b/c 已完成，d 待实现）
- [x] T32-4.11：路由事件、内存观测器、正负向评测和决策原因测试
- [x] T32-4.11b：路由决策事件持久化与重新加载
- [x] T32-4.11c：评测报告持久化与查询

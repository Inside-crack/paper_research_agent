# 需求实现方案

**需求ID**：E02  
**需求名称**：关键节点上下文自动落盘  
**优先级**：P0  
**创建日期**：2026-08-14  
**最后更新**：2026-08-18

---

## 需求描述

通过Hook机制在关键节点自动落盘：PASS阶段写入PhaseCompletionRecord（轻量统计），REVISE/BLOCKED/Exception时dump完整ErrorContext（含plan/steps/messages/traceback）。

## 方案设计

### 触发点

在Orchestrator主循环 `_execute_phase_flow()` 中：

| 时机 | 动作 | 落盘内容 |
|------|------|----------|
| PASS verdict（mark_phase_completed前） | save_completion_record | PhaseCompletionRecord（stats） |
| REVISE verdict（record_revision后） | dump_error_context(error_type="revise") | ErrorContext含correction notes+eval_result |
| BLOCKED verdict | dump_error_context(error_type="blocked") | ErrorContext含eval+issues |
| Exception（except块） | dump_error_context(error_type="exception") | ErrorContext含traceback+当前plan+step状态 |
| Phase step exception（_execute_plan内） | 已有A04 error落盘，追加error_context引用 | 不变 |

### 上下文快照采集

dump_error_context时采集：
1. **execution_plan**: 当前ExecutionPlan序列化（steps含arguments/result/error/artifact_id）
2. **step_snapshots**: 每个step的StepSnapshot（从plan.steps构建）
3. **messages_snapshot**: research_agent.messages 全量拷贝（LLM可见的完整历史）
4. **eval_result**: 如果有EvaluationResult，序列化
5. **traceback**: `traceback.format_exc()`（仅exception类型）
6. **research_output**: synthesize后的ResearchOutput快照（如果有）

### 失败降级策略

所有E02写入操作包裹在try/except中：
- 写入失败 → logger.error("Failed to dump error context: ...") + 继续流程
- 不抛出RuntimeError（失败路径上不二次崩溃）
- 这与A04/D02的"落盘失败=终止"不同，因为：错误路径上系统已经在处理失败，dump只是辅助调试

### 具体集成点

Orchestrator中新增方法：
```python
async def _dump_phase_error(self, task_state, phase, error_type, 
                            error_msg, plan=None, eval_result=None, 
                            research_output=None, exc=None)
async def _save_phase_completion(self, task_state, phase, plan, 
                                  eval_result, duration_ms)
```

### manifest注册

每次写入后调用 `update_step_in_manifest` 或新增 `add_error_context_to_manifest` 注册文件引用到 `m.phases[phase].errors` 或 `m.files`。

## 实现步骤

1. 在state_persistence新增 `save_completion_record()` 和 `dump_error_context()` 方法
2. Orchestrator _execute_phase_flow 四个verdict分支集成调用
3. Orchestrator exception catch块集成dump
4. 单元测试：模拟PASS/REVISE/BLOCKED/Exception验证文件生成

## 依赖项

- [x] E01 ErrorContext模型
- [x] D01 命名规范
- [x] D02 Manifest CRUD

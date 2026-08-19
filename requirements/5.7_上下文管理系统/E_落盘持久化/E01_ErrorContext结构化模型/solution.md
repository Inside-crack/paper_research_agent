# 需求实现方案

**需求ID**：E01  
**需求名称**：ErrorContext结构化模型  
**优先级**：P0  
**创建日期**：2026-08-14  
**最后更新**：2026-08-18

---

## 需求描述

新增ErrorContext模型：结构化保存失败现场证据，包含task_id/phase/revision/错误类型/错误消息/完整traceback/失败step/失败tool/关联ExecutionPlan/step results快照/LLM messages快照/恢复建议。PASS阶段做轻量记录（PhaseCompletionRecord），REVISE/BLOCKED/Exception做全量现场dump。

## 方案设计

### 整体思路

E01定义两种结构化记录：
1. **PhaseCompletionRecord**（轻量）：PASS时记录，包含phase/score/verdict/duration/steps_count/errors_count/artifact_refs
2. **ErrorContext**（重量）：REVISE/BLOCKED/Exception时dump完整现场

两者均使用D01命名规范，落盘到任务目录，并在manifest中注册引用。

### 架构位置

- 新增 `src/paper_agent/common/persistence/error_context.py`：Pydantic模型+序列化/写入方法
- 触发点在Orchestrator（见E02）
- 写入失败降级为warn（E组特性：失败路径上不二次崩溃）

### 文件命名（D01规范）

- PhaseCompletionRecord: `{phase_short}_completion.json`（如 `paper_retrieval_completion.json`）
- ErrorContext（REVISE）: `{phase_short}_rev{n}_error.json`
- ErrorContext（BLOCKED/Exception）: `{phase_short}_fatal_error.json`

### 关键数据结构

```python
class StepSnapshot(BaseModel):
    step_id: str
    tool_name: str
    success: bool
    duration_ms: int = 0
    artifact_id: Optional[str] = None
    error: Optional[str] = None
    arguments_snapshot: dict[str, Any] = Field(default_factory=dict)

class ErrorContext(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str
    phase: str
    revision: int = 0
    error_type: str  # revise / blocked / exception
    error_message: str
    traceback: Optional[str] = None
    timestamp: str = Field(default_factory=_now_iso)
    
    failed_step: Optional[str] = None
    failed_tool: Optional[str] = None
    
    execution_plan: Optional[dict] = None  # 完整plan快照
    step_snapshots: list[StepSnapshot] = Field(default_factory=list)
    
    messages_snapshot: list[dict] = Field(default_factory=list)  # LLM messages全量快照
    eval_result: Optional[dict] = None  # EvaluationResult快照
    research_output: Optional[dict] = None
    
    recovery_hint: Optional[str] = None
    
class PhaseCompletionRecord(BaseModel):
    task_id: str
    phase: str
    revision: int = 0
    verdict: str
    score: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: str = Field(default_factory=_now_iso)
    duration_ms: int = 0
    steps_total: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    total_errors: int = 0
    artifacts: list[str] = Field(default_factory=list)
```

### 与现有代码交互点

- 新增文件：`common/persistence/error_context.py`
- Orchestrator在PASS/REVISE/BLOCKED/Exception处调用写入方法
- manifest.phases[phase].errors 中追加error_id引用
- scan_artifacts_for_files识别error类型文件

## 实现步骤

1. 创建 `error_context.py` 定义上述模型+atomic_write
2. 提供 `dump_error_context()` 和 `save_completion_record()` 便捷方法
3. Orchestrator集成（E02）
4. 单元测试

## 依赖项

- [x] D01 命名规范（命名pattern已定义）
- [x] D02 Manifest（manifest引用注册）
- [x] A04 工具结果自动落盘（artifact_id引用）

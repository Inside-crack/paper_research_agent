# P30 T1：子步骤状态与持久化

## 目标

为保留的 `PAPER_PARSING` 阶段增加 P10-P14 五个可持久化子步骤状态，
实现 `TaskState`、Manifest 和 checkpoint 的向后兼容读写。T1 不修改
Orchestrator 的执行逻辑。

## 约束

- 不新增顶层 `TaskPhase`。
- 所有 JSON 写入使用现有原子写入流程。
- 持久化失败必须传播错误。
- 历史 TaskState、Manifest 和 checkpoint 没有子步骤字段时仍可读取。

### Task 1

- [x] 新增论文处理子步骤状态模型和默认状态。
- [x] 扩展 `TaskState` 和 `PAPER_PARSING` Manifest 子步骤记录。
- [x] 增加子步骤读写/更新持久化接口。
- [x] 增加正向、失败路径、checkpoint round-trip 和旧数据兼容测试。

**Files:**

- `src/paper_agent/common/models/task_state.py`
- `src/paper_agent/common/models/__init__.py`
- `src/paper_agent/common/persistence/manifest.py`
- `src/paper_agent/common/persistence/state_persistence.py`
- `examples/test_p30_t1_state_persistence.py`

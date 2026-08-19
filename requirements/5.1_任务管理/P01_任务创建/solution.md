# P01 任务创建 - 实现方案

## 方案概述
基于Orchestrator状态机的任务创建与生命周期管理，采用ResearchSpec作为任务规格说明，TaskState跟踪完整任务状态。

## 架构设计

### 任务模型
- **ResearchSpec**：不可变的任务规格（用户目标/约束/预算），创建后持久化
- **TaskState**：可变的运行时状态（当前阶段/阶段状态/产物/轨迹），支持checkpoint

### 创建流程
1. 用户提交query（CLI/API/对话）
2. Orchestrator.create_task() 生成UUID task_id
3. 创建工作目录：data/workspaces/<task_id>/
4. 创建产物目录：data/artifacts/<task_id>/
5. 初始化TaskState，设置current_phase=task_initialization
6. 自动进入第一阶段（任务初始化）

### 任务类型
- topic_research：主题调研（检索多篇论文）
- paper_analysis：单篇论文分析（用户指定arxiv_id）
- reproduction：实验复现（指定论文+代码）

## 相关文件
- `src/paper_agent/common/models/research_spec.py`
- `src/paper_agent/common/models/task_state.py`
- `src/paper_agent/orchestrator/orchestrator.py` - run_task()入口
- `src/paper_agent/cli.py` - CLI入口

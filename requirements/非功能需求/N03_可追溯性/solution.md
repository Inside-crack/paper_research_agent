# N03 可追溯性 - 实现方案

## 方案概述
通过TraceEntry执行轨迹、EvaluationResult评估记录、Artifact产物持久化三级追溯机制，确保每个结论都可溯源到原始证据。

## 追溯维度

### 1. 执行轨迹（Trace）
- 每步工具调用：tool_name/input/output/duration/success/error
- Agent动作：plan_generated/synthesize/evaluation
- 阶段转换：phase_start/phase_end/verdict
- 所有TraceEntry附加timestamp和phase信息

### 2. 产物版本
- 每个Artifact单独保存为JSON文件
- 阶段输出保存到task_state.metadata["phase_output_{name}"]
- revision时保留旧版本产物

### 3. 评估记录
- 每次评估生成独立EvaluationResult（带ID）
- issues关联到具体字段/步骤
- deterministic_checks记录程序检查结果
- evidence_links指向原始证据来源

### 4. 证据链
- Evaluation Agent同时接收：user_query/原始工具输出/research_output
- 问题描述必须包含evidence引用
- 禁止无证据的主观判断

## 相关文件
- `src/paper_agent/common/models/base.py` - TraceEntry
- `src/paper_agent/common/models/evaluation_result.py`
- `src/paper_agent/orchestrator/orchestrator.py` - add_trace()
- `src/paper_agent/evaluation_agent/agent.py` - _gather_evidence()

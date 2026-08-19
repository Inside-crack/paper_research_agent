# 需求实现进展

**需求ID**：A04  
**需求名称**：工具结果按需召回机制（自动落盘+artifact引用）  
**优先级**：P1  
**当前状态**：✅ 已完成  
**完成日期**：2026-08-15

---

## 需求描述

工具执行结果自动落盘为artifact文件，step上记录artifact_id引用；results_prompt中标注artifact文件名，后续阶段可通过load_artifact按需加载，避免跨阶段数据丢失。

## 核心验收点

- [x] 成功工具步骤自动存compact结果为artifact（step_{step_id}_{tool_name}_result.json）
- [x] 失败步骤自动存结构化错误信息（step_{step_id}_{tool_name}_error.json，含step_id/tool_name/phase/error/arguments/timestamp）
- [x] save_artifact工具本身不递归自动存盘（避免冗余）
- [x] step.artifact_id字段记录文件名（增量字段，向后兼容）
- [x] results_prompt包含Artifact列，标注"Persisted artifact: xxx.json (load with load_artifact)"
- [x] 落盘失败raise RuntimeError终止流程（严格策略：无法持久化则无继续必要）
- [x] 错误落盘失败也raise RuntimeError（双重失败防护）
- [x] trace记录包含artifact_id

## 进度概览

- [x] grill-me需求澄清（快速确认7点，跳过openspec直接实现）
- [x] 模型修改（PlanStep新增artifact_id字段）
- [x] 核心逻辑实现（_auto_persist_step_result + _auto_persist_step_error）
- [x] results_prompt更新（Artifact列+load_artifact引用）
- [x] 单元测试通过（8/8）
- [x] 验收通过

## 实现说明

### 改动文件
1. **execution_plan.py**：PlanStep新增`artifact_id: Optional[str] = None`
2. **orchestrator.py**：
   - `_execute_plan()`中工具执行后自动调用_auto_persist_step_result/_auto_persist_step_error
   - 新增`_auto_persist_step_result()`：成功step存compact结果，跳过save_artifact，落盘失败raise RuntimeError
   - 新增`_auto_persist_step_error()`：失败step存结构化错误JSON，落盘失败raise RuntimeError
   - add_trace增加artifact_id字段
3. **agent_base.py**：`_build_results_prompt()`新增Artifact列，每个step标注Persisted artifact引用

### 关键决策
- **严格落盘策略**：落盘失败=流程终止，不降级。原因：信息不能持久化则后续阶段无法取用数据，继续执行无意义
- **存compact结果**：不存原始工具返回值，存_compact_result压缩后的版本
- **save_artifact不递归**：save_artifact本身就是存文件工具，返回值是确认回执，不再存一份回执
- **不改变Synthesize流程**：当前阶段results_prompt仍放完整compact结果，artifact只做持久化+跨阶段引用；占位符替换是B02的事

### 测试结果
- examples/test_a04_auto_persist.py：8/8通过
  1. PlanStep.artifact_id字段存在
  2. 成功step自动存盘
  3. 失败step自动存错误信息
  4. save_artifact不递归存盘
  5. trace记录正确
  6. results_prompt含Artifact列+load_artifact
  7. 落盘失败raise RuntimeError
  8. 错误artifact含全部7个必填字段

## 进展记录

### 2026-08-15
- 快速grill-me澄清7点确认
- superpowers实现：3个文件改动
- 单元测试8/8通过
- 验收8/8通过

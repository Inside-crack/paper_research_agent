# A01 阶段间上下文隔离 - 已解决问题及解决方案

（实现过程中解决的卡点实时记录在此）

---

## 实现前已决策问题

### 1. 阶段隔离触发时机
- **问题**：是评估PASS后立刻重置，还是进入新阶段时重置？
- **决策**：在新阶段`_execute_phase_flow()`第一行重置（选项b）
- **原因**：REVISE重试也走_execute_phase_flow，is_revision=True时不重置，逻辑统一

### 2. REVISE时history是否需要清理
- **问题**：同阶段REVISE重试，上一轮的synthesize结果要不要清理？
- **决策**：不做任何清理，完全保留，只追加correction_notes
- **原因**：REVISE需要看到完整上下文，包括自己上一轮做错了什么

### 3. 摘要卡是否用LLM生成
- **问题**：阶段产物摘要卡是确定性拼接还是让LLM总结？
- **决策**：Orchestrator确定性拼接，不调LLM
- **原因**：字段固定（phase/verdict/score/conclusion/artifact_ids/key_info），直接从research_output和eval_result取字段即可，又快又省token

### 4. 失败信息是否传给下一阶段
- **问题**：REVISE最终PASS后，第一版失败信息要不要作为摘要卡一部分给下一阶段看？
- **决策**：失败信息单独存到task_state.metadata给开发者分析，不进入运行时摘要卡
- **原因**：失败信息对下一阶段Agent执行任务是噪音，但对我们优化系统很宝贵，所以分离存储

---

## 实现过程中遇到的问题及解决

### 5. EvaluationIssue Pydantic模型属性访问错误
- **现象**：`AttributeError: 'EvaluationIssue' object has no attribute 'get'`
- **根因**：_record_phase_failure中用`i.get("severity")`字典方式访问EvaluationIssue对象属性，但EvaluationIssue是Pydantic BaseModel，应该用属性访问
- **解决方案**：改为`issue.severity.value`（枚举值提取）
- **涉及文件**：orchestrator.py _record_phase_failure()
- **验证**：✅ 失败信息正确记录到metadata.phase_failures

### 6. _build_phase_summary_card中issues类型兼容问题
- **现象**：notes字段无法正确提取high/critical issues数量
- **根因**：eval_result.issues在真实调用中是list[EvaluationIssue]（Pydantic模型），但单元测试可能传入list[dict]
- **解决方案**：新增_get_severity()辅助函数，先检查是否有severity属性（Pydantic对象），再检查是否是dict，兼容两种类型
- **涉及文件**：orchestrator.py _build_phase_summary_card()
- **验证**：✅ 单元测试和E2E测试都能正确提取severity

# 实现进度

**需求ID**：A03  
**需求名称**：REVISE重试策略优化  
**当前阶段**：✅ 完成（review-verify验收通过）

---

## 阶段状态

- [x] grill-me 需求澄清（7个维度全部完成，推翻滑动窗口思路）
- [x] openspec 方案设计 + 自检清单（12/12通过）
- [x] 用户确认方案，进入superpowers
- [x] superpowers 代码实现
- [x] superpowers 单元测试（9/9通过）
- [x] superpowers E2E验证（16/16通过）
- [x] review-verify 验收对账（8/8通过）

---

## 已完成项

### Grill-Me 澄清完成
- 推翻A01中"REVISE保留history"的错误决策
- 确认REVISE时重置Research Agent context（防锚定），但保留上一轮成功工具结果
- 确认不做断点续跑（3c，P2留给实验阶段）
- 确认paper二次压缩：去重后≤30篇，compact版含abstract_preview
- 确认PlanStep已有success/result/error字段，无需改模型
- 确认start_new_phase加force参数
- 确认异常降级处理（catch+提示重新规划，不阻塞REVISE）
- 12项自检清单全部通过

### 代码实现完成
1. ✅ BaseAgent.start_new_phase()加force参数，跳过同phase防重入检查
2. ✅ BaseAgent新增inject_message()方法（带未初始化检查）
3. ✅ Orchestrator._execute_phase_flow() REVISE分支改为：
   - 新阶段：清空last_round_results，正常start_new_phase
   - REVISE：start_new_phase(force=True)重置context → 注入"已有数据"消息 → 生成详细correction_notes
4. ✅ Orchestrator._record_round_results()：结构化记录每轮step结果、paper去重、eval issues
5. ✅ Orchestrator._build_correction_notes()重写：执行概况+失败步骤+HIGH/CRITICAL issues+修复建议+复用提示
6. ✅ Orchestrator._build_previous_results_message()新增：成功/失败步骤列表+paper列表（≤30篇compact版）
7. ✅ paper去重逻辑复用arxiv_id base_id去重
8. ✅ paper列表展示30篇上限，all_papers存储50篇上限
9. ✅ 异常降级：build_correction/build_prev_msg内部catch，返回降级提示
10. ✅ _execute_phase_flow末尾调用_record_round_results（try/except包裹，不影响主流程）

### 测试结果

**单元测试**（examples/test_a03_revise.py，9/9通过）：
1. ✅ _record_round_results正确存储step/paper/issues数据
2. ✅ _build_correction_notes生成包含执行概况/失败步骤/Eval issues/修正建议
3. ✅ _build_previous_results_message格式正确，paper列表30篇上限
4. ✅ 100篇论文场景：存储50篇，展示30篇，提示70篇未展示
5. ✅ 非paper_retrieval阶段不显示论文列表
6. ✅ last_round=None时降级返回通用提示
7. ✅ last_round数据不完整时不崩溃
8. ✅ inject_message未初始化时抛RuntimeError（反例）
9. ✅ force=True正确清空history，旧消息移除

**E2E验证**（examples/verify_a03_revise.py，16/16通过）：
- ✅ 锚点保留（system/spec/summary_cards）
- ✅ 旧LLM对话清空（无旧plan/results_prompt，防锚定）
- ✅ "已有可用数据"消息注入
- ✅ 成功/失败步骤正确展示
- ✅ save_artifact错误信息可见
- ✅ 论文列表30篇展示
- ✅ "不需要重新搜索"提示存在
- ✅ correction_notes包含HIGH issues和具体修复建议
- ✅ REVISE开始时history仅4条消息（紧凑）
- ✅ 注入内容总计约9692字符（合理大小）

### 数据验证

REVISE场景context对比：
- **改造前（A01之后）**：保留revision=0全部对话（phase_prompt+plan+results_prompt+synthesize ≈ 5-8条消息，含大段results_prompt约8000字）
- **改造后（A03）**：context重置为4条基准消息（锚点3条+已有数据1条≈9300字），加上phase_prompt+CORRECTION≈400字，总计约9700字
- **关键改进**：没有被旧plan锚定风险；LLM看到的是干净的锚点+精准的失败根因+可用数据，而非冗余的旧对话历史

---

## 待完成项

无。A03已全部完成，8/8验收通过。

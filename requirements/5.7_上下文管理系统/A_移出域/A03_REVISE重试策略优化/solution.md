# 需求实现方案

**需求ID**：A03  
**需求名称**：REVISE重试策略优化（原名：阶段内轮次历史滑动窗口——已废弃滑动窗口思路）  
**优先级**：P1  
**创建日期**：2026-08-14

---

## 需求描述

优化REVISE重试策略：
1. REVISE时不再保留上一轮全部LLM对话历史（避免锚定效应和token膨胀），而是像新阶段一样重置Research Agent context
2. 结构化记录上一轮执行结果（每个step成功/失败/结果摘要/Eval issues），精准传递给第二轮
3. 重置后通过两条消息告诉LLM：①上一轮已有什么数据可以复用；②具体什么问题需要修正
4. 失败根因完整落盘给开发者分析
5. **不做断点续跑**（3c，P2后续：实验执行阶段才需要）

---

## Grill-Me 澄清纪要

### 第一维度：需求定位与类型

1. **类型**：改造。改REVISE重试时Research Agent的context处理策略。推翻A01中"REVISE不重置history"的决策。
2. **优先级**：P1（max_revisions=1，REVISE最多一次，但显著提升修正成功率、避免锚定、降低token）
3. **依赖**：依赖A01（已完成）。不依赖D01/E02。
4. **核心改动**：
   - Orchestrator新增`_record_round_results()`收集上一轮执行数据
   - 改`_execute_phase_flow()`的is_revision分支：从"不重置"→"start_new_phase(force=True)重置 + 注入修正包"
   - 重写`_build_correction_notes()`：基于last_round_results生成详细修正指令
   - 新增`_build_previous_results_message()`：格式化上一轮成功step的已有数据
   - PlanStep模型新增`success: bool`和`result: dict`字段
   - Agent Base的`start_new_phase()`支持force参数
   - Research Agent新增`inject_message()`方法用于追加独立消息
5. **A01决策修正**：原A01"REVISE不重置history"是错误决策——保留旧history导致LLM被上一轮错误plan锚定，且上一轮results_prompt（3000-8000字）冗余。改为REVISE也重置context，通过精准注入传递必要信息。
6. **断点续跑3c**：标记为P2，本次不做。LLM如果重复执行已成功的幂等工具（如arxiv_search），成本可接受，不强制跳过。

### 第二维度：用户与场景

1. **触发方与时机**：Orchestrator在`_execute_phase_flow()`开头，is_revision=True时：
   - 调用start_new_phase(force=True)重置Research Agent context
   - 注入"已有数据"独立USER消息
   - phase_prompt里追加CORRECTION REQUIRED段落（用现有机制）
2. **数据存储**：上一轮执行结果存`task_state.metadata["last_round_results"]`（dict），覆盖式更新（只保留最近一轮）。新阶段开始时清空。
3. **工具结果传递**：传完整紧凑结果（_compact_result压缩过的paper列表），不是只传摘要。
4. **correction_notes内容**：
   - 上一轮Plan执行概况（成功/失败step数）
   - 失败step的错误信息
   - Eval的high/critical issues（description+suggestion）
   - 明确修正指令
5. **Eval Agent**：完全不改，天然独立。

### 第三维度：功能规则与数据流

1. **改动范围**：集中在Orchestrator。Agent基类只加force参数和inject_message()，极小改动。TaskState不改（用metadata）。
2. **消息注入机制**：用现有correction_notes追加在phase_prompt里，不新注入机制。"已有数据"用独立USER消息通过inject_message()追加。
3. **last_round_results生命周期**：
   - 每轮结束（PASS/REVISE/BLOCKED）：调用_record_round_results()覆盖保存
   - PASS→进入下一阶段：新阶段开头（is_revision=False）清空
   - REVISE→第二轮：读取生成correction，第二轮结束后覆盖
   - BLOCKED/FAILED：保留（给开发者分析）
4. **已有数据格式**：
   - 列出每个step的成功/失败状态、结果摘要
   - paper数据：去重（复用_deduplicate_search_results）、≤30篇、compact版含abstract_preview[:200]
   - 明确告知"这些结果可用，你可以选择不重复搜索"
5. **不强制跳过已成功步骤**：correction里建议LLM复用已有数据，但不强制；LLM自主决定是否重搜。

### 第四维度：边界与异常

1. **max_revisions>1（未来扩展）**：每轮覆盖last_round_results，只保留最近一轮（第三轮只需要知道第二轮的问题）。
2. **新阶段清空**：is_revision=False时，_execute_phase_flow开头清空metadata["last_round_results"]。
3. **BLOCKED场景**：仍然_record_round_results()记录根因，但不生成correction_notes（不会重试）。
4. **paper数据二次压缩**：arxiv_id去重后最多30篇，每篇compact版（arxiv_id/title/authors[:3]/published/categories/abstract_preview[:200]），每篇约200-300字，总计≤9000字。超过30篇截断，统计里说明"另有N篇未展示"。
5. **数据不完整降级**：如果execute_plan异常中断（无eval_result或部分step无result），_build_correction_notes()降级处理，有什么用什么，不崩溃，提示"上一轮异常中断，请重新完整规划"。
6. **防重入兼容**：start_new_phase()加force=True参数，REVISE时传force=True跳过同phase重复检查。

### 第五维度：验收标准

1. **REVISE时context干净**：第二轮history无第一轮旧对话消息，只有锚点3条 + 已有数据消息 + CORRECTION phase_prompt
2. **correction_notes内容完整**：包含执行概况、失败step错误、Eval high/critical issues、修正指令
3. **已有数据消息正确**：成功step摘要、paper去重≤30篇含compact abstract、明确告知可复用
4. **新阶段逻辑不受影响**：revision=0时清空last_round_results，start_new_phase正常工作，无correction注入
5. **降级处理正常**：异常中断不崩溃，生成"请重新完整规划"提示
6. **force参数工作**：REVISE时start_new_phase(force=True)不抛RuntimeError
7. **负向测试4项**：
   - (a) 有Eval issues时correction正确包含
   - (b) 无last_round_results时不注入correction
   - (c) 部分step失败时失败信息正确展示
   - (d) 数据不完整时不崩溃，降级提示
8. **E2E验证**：第一轮故意REVISE（save_artifact参数错误），第二轮干净context+正确correction，最终PASS

### 第六维度：非功能需求

1. **侵入性**：只改orchestrator.py、agent_base.py（极小）、plan模型（加2字段），其他模块不动
2. **日志**：INFO记录关键节点（REVISE重置、注入N步M篇K issues），DEBUG打correction完整内容
3. **错误处理**：_record_round_results/_build_correction_notes内部catch异常，ERROR日志，降级为"数据不完整请重新规划"，不阻塞REVISE
4. **兼容性**：现有test_two_phases.py不受影响（无REVISE场景），新增REVISE专项测试
5. **配置开关**：不加开关，核心逻辑必须开

### 第七维度：技术选择

1. **PlanStep加字段**：success: bool = False，result: dict | None = None，增量字段default兼容
2. **start_new_phase force参数**：加force: bool = False，True时跳过同phase重复检查
3. **消息注入**：Research Agent新增`inject_message(content: str, role: MessageRole = USER)`方法封装，Orchestrator不直接操作message_history
4. **去重复用**：复用现有_deduplicate_search_results()
5. **30篇截断策略**：按搜索出现顺序截断前30篇，简单可靠

---

## 方案设计

### 整体架构

在现有A01阶段隔离基础上，修改REVISE分支逻辑：

```
_execute_phase_flow(phase, is_revision):
    if not is_revision:
        clear metadata["last_round_results"]
        await research.start_new_phase(phase, task_state, task_state.phase_summaries)
    else:
        # REVISE: 重置context（和新阶段一样干净），但注入修正包
        await research.start_new_phase(phase, task_state, task_state.phase_summaries, force=True)
        prev_msg = _build_previous_results_message(task_state.metadata["last_round_results"])
        await research.inject_message(prev_msg)
        # correction_notes在generate_plan时追加到phase_prompt（现有机制）

    # ...后续generate_plan→validate→execute→synthesize→eval...

    # 本轮结束后（不管PASS/REVISE/BLOCKED）
    _record_round_results(phase, plan, eval_result, task_state)
```

### 架构位置

- 改动模块：`src/paper_agent/orchestrator/orchestrator.py`（主要）、`src/paper_agent/common/agent_base.py`（加force）、`src/paper_agent/research_agent/agent.py`（加inject_message）、`src/paper_agent/common/models/plan.py`（PlanStep加字段）
- 新增方法：
  - `Orchestrator._record_round_results(phase, plan, eval_result, task_state)`
  - `Orchestrator._build_correction_notes(eval_result, last_round_results)`（重写）
  - `Orchestrator._build_previous_results_message(last_round_results)`（新增）
  - `ResearchAgent.inject_message(content, role)`（新增）
- Hook注册：无
- 配置开关：无

### 关键数据结构

**PlanStep新增字段**（增量，default兼容）：
```python
success: bool = Field(default=False, description="步骤是否执行成功")
result: dict[str, Any] | None = Field(default=None, description="步骤执行结果（紧凑版）")
error: str | None = Field(default=None, description="步骤执行错误信息")
```

**last_round_results结构**（存在task_state.metadata["last_round_results"]）：
```python
{
    "phase": "paper_retrieval",
    "revision": 0,
    "total_steps": 7,
    "succeeded_steps": 6,
    "failed_steps": 1,
    "steps": [
        {
            "step_id": "step_1",
            "tool_name": "arxiv_search",
            "success": True,
            "result_summary": "15 results (arxiv:2401.0xxx, ...)",
            "compact_result": [...],  # 最多30篇compact paper
            "error": None
        },
        ...
    ],
    "eval_issues": [  # high/critical only
        {"severity": "high", "description": "...", "suggestion": "..."}
    ],
    "eval_score": 0.65,
    "verdict": "revise"
}
```

### 关键消息格式

**"已有数据"消息**（独立USER消息）：
```
=== 上一轮执行：已有可用数据 ===

上一轮(revision=0)执行概况：7个步骤中6个成功，1个失败。

✅ 成功步骤（结果可复用，你可以选择不重复执行）：
  - step_1 (arxiv_search "multi-agent LLM collaboration"): 15篇论文
  - step_2 (arxiv_search "tool use learning"): 15篇论文
  ...

❌ 失败步骤（需要修正）：
  - step_7 (save_artifact "candidate_papers"): 错误 - Missing required parameter: data
    → 调用save_artifact时参数名应为'data'而非'content'

📄 去重后已有论文列表（共45篇，展示前30篇）：
  1. arxiv:2401.01234 - "Multi-Agent Collaboration in LLMs" - Smith et al. (2024) [cs.AI]
     Abstract: We propose...
  2. ...

⚠️ 你可以直接使用上述论文结果，不需要重新搜索。必须修复save_artifact调用问题并保存候选论文。
```

**CORRECTION REQUIRED**（追加在phase_prompt里）：
```
## CORRECTION REQUIRED

上一轮尝试(revision=0)未通过评估（score=0.65）。

必须修复以下问题：
1. [HIGH] save_artifact未被正确调用，候选论文未保存
   → 建议：确保在synthesize阶段调用save_artifact，参数data传入论文列表
2. [HIGH] 未验证候选论文的code_available字段
   → 建议：筛选有代码仓库的论文，标记has_code=True

已有可用数据见上方消息，你不需要重复执行已成功的arxiv_search。请重新制定修正后的Plan。
```

---

## 实现步骤

1. PlanStep模型加success/result/error字段
2. _execute_plan()中执行step后更新step.success/step.result/step.error
3. Agent Base的start_new_phase()加force参数
4. ResearchAgent加inject_message()方法
5. Orchestrator实现_record_round_results()
6. 重写_build_correction_notes()
7. 实现_build_previous_results_message()（含去重、30篇截断、compact格式化）
8. 改_execute_phase_flow()的REVISE分支逻辑
9. 新阶段开头清空last_round_results
10. 单元测试 + REVISE场景E2E测试
11. 验收

---

## 自检清单

| # | 检查项 | 结果 |
|---|--------|------|
| 1 | 是否推翻A01"REVISE不重置"的错误决策 | ✅ 是，改为重置+精准注入 |
| 2 | 是否避免锚定效应（旧LLM对话被清空） | ✅ 是 |
| 3 | 上一轮工具结果是否保留给第二轮用 | ✅ 是，通过独立消息精准传递 |
| 4 | 数据二次压缩是否合理（≤30篇含abstract） | ✅ 是，约9000字 |
| 5 | 断点续跑是否标记为P2不做 | ✅ 是 |
| 6 | 异常降级是否处理（catch+降级提示） | ✅ 是 |
| 7 | force参数是否解决防重入冲突 | ✅ 是 |
| 8 | PlanStep加字段是否增量兼容 | ✅ 是，default_factory |
| 9 | 是否不加配置开关 | ✅ 是 |
| 10 | Eval Agent是否不受影响 | ✅ 是，天然独立 |
| 11 | last_round_results生命周期是否清晰 | ✅ 是，覆盖+清空规则明确 |
| 12 | 8项验收标准是否可验证 | ✅ 是 |

---

## 依赖项

- [x] A01 阶段间隔离
- [ ] D01 命名规范（不需要等）
- [ ] E02 Hook触发机制（不需要等）

---

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|--------|----------|----------|
| REVISE重置context后LLM修正能力不如保留历史 | 中 | correction_notes精准传递Eval issues和已有数据，比保留冗余旧历史信息更有效；E2E测试验证修正成功率 |
| _execute_plan改step.result侵入现有执行逻辑 | 低 | 增量字段，只在_execute_plan末尾赋值，不改变执行逻辑 |
| 30篇截断可能丢失关键论文 | 低 | 截断只是不传给LLM，论文原始结果已存在last_round_results里；LLM如果觉得不够可以补充搜索 |

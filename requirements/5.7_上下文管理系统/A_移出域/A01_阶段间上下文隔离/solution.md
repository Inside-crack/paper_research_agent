# 需求实现方案

**需求ID**：A01
**需求名称**：阶段间上下文隔离
**优先级**：P0
**创建日期**：2026-08-14
**澄清日期**：2026-08-14
**包含子需求**：A02 阶段产物摘要卡生成（A01依赖，一起实现）

---

## 需求澄清纪要（grill-me 7维度确认）

### 1. 需求定位与类型

| 项 | 结论 |
|----|------|
| 类型 | 对现有Agent上下文机制的改造（非全新功能） |
| 模块归属 | 上下文管理系统 → A.移出域 |
| 优先级 | P0（A/B/C三层的基础，不做多阶段必爆token窗口） |
| 依赖策略 | 选项A：A01+A02核心逻辑先做，D01/E02落盘后续补；先解决运行时爆窗口问题 |
| 核心改动点 | 每个阶段开始时都重新初始化Research Agent上下文，而非整个任务只初始化一次 |
| 旧checkpoint兼容性 | 不兼容旧数据，开发早期直接从新任务开始测试 |

### 2. 用户与场景

| 项 | 结论 |
|----|------|
| 触发方 | Orchestrator（流程控制器）在阶段切换时触发 |
| 触发时机 | 新阶段`_execute_phase_flow()`第一行（选项b），不是评估PASS那一刻 |
| REVISE重试（revision=1） | **不重置**history，只追加correction_notes，不做任何清理，保留全部上一轮对话 |
| Evaluation Agent | 不需要改造，Eval每次评估天然独立（不跨阶段累积history） |
| 注入内容锚点 | System Prompt + ResearchSpec（永远保留）+ 前序已完成阶段摘要卡 + 当前Phase Prompt |

### 3. 功能规则与数据流

| 项 | 结论 |
|----|------|
| 新方法签名 | `async def start_new_phase(self, phase: TaskPhase, previous_summaries: list[dict]) -> None`（定义在BaseAgent） |
| 摘要卡生成 | Orchestrator确定性生成，从research_output + eval_result中直接取字段拼接，**不额外调LLM** |
| 第一阶段处理 | previous_summaries为空list，history=System+ResearchSpec+Phase Prompt |
| ResearchSpec | 永远保留的锚点，每个阶段都要注入 |
| 与initialize()关系 | 保留initialize()作为start_new_phase内部调用的子方法（加载system prompt），外部不再直接调用；移除`if not self.system_prompt`懒初始化逻辑，改为Orchestrator显式调用 |

### 4. 边界与异常

| 场景 | 处理方式 |
|------|----------|
| BLOCKED/FAILED阶段 | 任务直接终止，但失败信息单独持久化保存（留给人分析），不生成摘要卡给后续阶段 |
| 阶段PASS但没save_artifact | Eval确定性检查必须拦住，没保存就给REVISE，不让PASS |
| REVISE后第一版失败结果 | 失败信息**单独存到task_state**给开发者分析优化；**运行时摘要卡只用最终PASS的结果**，不污染下一阶段context |
| 状态不一致（is_revision=True但revision_count=0） | 直接抛异常（c），不静默处理，暴露bug |
| 同阶段重复调用start_new_phase | 抛异常+记录错误原因；通过`_current_phase`标记防重入 |
| 阶段执行过程中（plan→execute→synthesize） | history正常累积，绝对不能重置 |
| resume崩溃恢复 | A01不处理，留给E02落盘机制后续解决 |

### 5. 验收标准

| 验证项 | 要求 |
|--------|------|
| 下一阶段无原始工具结果 | 进入paper_parsing时，Research Agent message_history里**没有**paper_retrieval阶段的arxiv_search原始结果（90篇摘要） |
| 上下文内容正确 | message_history = System Prompt + ResearchSpec + 已完成阶段摘要卡 + 当前Phase Prompt |
| REVISE不重置 | revision=1重试时，保留revision=0的全部对话+correction_notes |
| Token减少效果 | paper_parsing阶段首次LLM请求prompt token比不做隔离减少60%+ |
| 单卡硬限制 | 每张摘要卡≤200字，超长截断 |
| 重复调用防护 | 同阶段重复调用start_new_phase直接抛异常 |
| 反例测试必须覆盖 | (1)PASS后下一阶段看不到上阶段原始输出 (2)REVISE时history未清空 (3)重复调用报错 (4)空summaries第一阶段正常 |

### 6. 非功能与约束

| 项 | 结论 |
|----|------|
| 性能开销 | start_new_phase微秒级（清空列表+拼字符串）；摘要卡生成微秒级（确定性拼接，无LLM调用）；context变小后LLM调用反而更快更省 |
| 摘要卡硬限制 | 单卡≤200字 |
| 改动范围 | 4个文件：`common/agent_base.py`、`research_agent/agent.py`、`orchestrator/orchestrator.py`、`common/models/task_state.py`；其他模块不碰 |
| 日志 | 关键节点打INFO日志：注入几张卡、生成哪张卡、当前阶段 |
| 配置开关 | **核心逻辑，不需要开关，必须开启**（不是实验性功能） |

### 7. 技术方案选择

| 项 | 结论 |
|----|------|
| 方法实现位置 | 基类BaseAgent做通用逻辑（清空history、加system prompt）；ResearchAgent重写加research_spec注入和摘要卡格式化 |
| initialize()处理 | 保留，作为start_new_phase内部调用的子方法，不删除 |
| phase_summaries存储 | 新增TaskState字段`phase_summaries: list[dict] = Field(default_factory=list)`，随checkpoint持久化 |
| 防重入机制 | Agent加`_current_phase: TaskPhase | None`标记；start_new_phase检查：相同phase重复调用抛错，不同phase正常重置并更新标记 |
| 测试方式 | 新建测试脚本`examples/test_phase_isolation.py`，专门测隔离逻辑，不污染现有E2E测试 |

---

## 方案设计

### 整体思路

三级上下文管理的第一层"移出域"核心机制：利用7阶段工作流的天然边界，**阶段完成后将Research Agent的message_history中的跨阶段冗余内容移出**，替换为结构化的阶段产物摘要卡。同一阶段内（Plan→Execute→Synthesize）消息正常累积；REVISE重试不重置。

### 上下文构成（新阶段开始时）

```
Research Agent message_history（重置后）:
├── [SYSTEM] System Prompt（角色定义，锚点）
├── [USER] === 研究任务规格（ResearchSpec，锚点，永远保留）===
│   {research_spec JSON 或格式化文本}
│
├── [USER] === 已完成阶段进度 ===
│   ✅ task_initialization: PASS (0.97)
│      核心结论: 任务类型=topic_research，研究领域=LLM Multi-Agent
│      关键词: ["multi-agent systems", "LLM agents", "tool use"]
│      产物: research_spec
│
│   ✅ paper_retrieval: PASS (0.82)
│      核心结论: 124篇→去重10篇，top3: [2401.07324, 2412.05449, ...]
│      产物: paper_candidates
│      备注: 目标论文需用户确认
│
└── [USER] === 当前阶段: Paper Parsing ===
    {paper_parsing phase prompt}
    可用工具: arxiv_get_paper, download_file, save_artifact, ...
```

token占比：System(~300) + ResearchSpec(~500) + 摘要卡每张~100-150字(7阶段全过也就~1000字) + Phase Prompt(~500) = **稳定在2000-3000字基准**，不会随阶段数增长而膨胀。

### 架构位置

```
Orchestrator._execute_phase_flow(phase, task_state):
    if task_state.revision_count == 0:
        # 新阶段开始：重置上下文，注入前序摘要
        await research_agent.start_new_phase(phase, task_state.phase_summaries)
        logger.info(f"Starting new phase: {phase}, injecting {len(task_state.phase_summaries)} summary cards")
    else:
        # REVISE重试：不重置，history保留，后续追加correction_notes
        logger.info(f"REVISE retry for phase: {phase}, revision={task_state.revision_count}")

    # ... 原有的 generate_plan → validate → execute → synthesize 逻辑 ...

    # 阶段PASS后：生成摘要卡（确定性拼接，无LLM）
    if eval_result.verdict == EvaluationVerdict.PASS:
        summary_card = _build_phase_summary_card(phase, research_output, eval_result)
        task_state.phase_summaries.append(summary_card)
        logger.info(f"Generated summary card for {phase}: score={eval_result.score}, artifact={summary_card['artifact_ids']}")
```

### 与现有代码的交互点

| 改动文件 | 改动内容 | 侵入性 |
|----------|----------|--------|
| `common/models/task_state.py` | 新增字段 `phase_summaries: list[dict] = Field(default_factory=list)` | 极低（增量字段，default_factory兼容旧数据） |
| `common/agent_base.py` | 新增 `start_new_phase()` 方法（通用逻辑：清空history、调用initialize()、防重入检查）；移除懒初始化判断 | 低 |
| `research_agent/agent.py` | 重写 `start_new_phase()`：调用基类方法后，注入ResearchSpec、格式化摘要卡文本 | 低 |
| `orchestrator/orchestrator.py` | (1)`_execute_phase_flow()`开头加is_revision判断和start_new_phase调用 (2)PASS后生成摘要卡加入task_state (3)失败信息单独记录到metadata | 低 |

**不改动**：tools、eval_agent、persistence、llm层、config。

### 关键数据结构

#### PhaseSummaryCard（dict结构，不需要新建Pydantic模型，轻量）

```python
{
    "phase": str,                    # TaskPhase枚举值
    "verdict": str,                  # "PASS"
    "score": float,                  # 0.0-1.0
    "conclusion": str,               # 核心结论，≤100字
    "artifact_ids": list[str],       # 本阶段保存的artifact ID列表
    "key_info": dict,                # 传给下阶段的关键信息（各阶段自定义，比如top3论文ID）
    "notes": str,                    # 备注，≤50字，可为空
}
```

#### BaseAgent新增状态

```python
# 在BaseAgent.__init__中
self._current_phase: TaskPhase | None = None
```

### 摘要卡模板

```
=== 已完成阶段: {phase} ===
状态: ✅ {verdict} (score: {score:.2f})
核心结论: {conclusion}
产物: {artifact_ids 逗号分隔}
备注: {notes or "无"}
```

### 实现步骤

1. **TaskState模型增量**：加phase_summaries字段
2. **BaseAgent改造**：加start_new_phase()通用方法+_current_phase防重入
3. **ResearchAgent改造**：重写start_new_phase，注入research_spec+格式化摘要卡
4. **Orchestrator改造**：
   - _execute_phase_flow开头加is_revision判断
   - 实现_build_phase_summary_card()确定性生成摘要卡
   - PASS后追加summaries，失败信息记录到metadata
5. **日志添加**：关键节点INFO日志
6. **测试脚本编写**：examples/test_phase_isolation.py，覆盖正向+4个反例场景
7. **运行验证**：测试task_initialization → paper_retrieval → 进入paper_parsing前检查context

## 依赖项

- [x] A01 核心机制
- [x] A02 阶段产物摘要卡生成（一起实现）
- [ ] D01 命名规范（后续，当前摘要卡先存内存+checkpoint）
- [ ] E02 Hook触发落盘（后续，A01阶段被移出的history先不持久化）

## 风险评估

| 风险点 | 影响等级 | 应对措施 |
|--------|----------|----------|
| start_new_phase时机不对导致阶段内history被清空 | 高 | _current_phase标记防重入；_execute_phase_flow最开头只调用一次；测试覆盖REVISE场景 |
| 摘要卡信息不够，下一阶段不知道该干什么 | 中 | 每个阶段的key_info字段定义清楚该传什么；Eval验证摘要卡核心信息不缺失；B层压缩策略兜底 |
| 侵入Orchestrator主循环影响现有稳定流程 | 中 | 改动最小化：只在开头加is_revision分支，PASS后加摘要卡生成；现有generate_plan→execute→synthesize逻辑完全不动 |
| 同阶段内start_new_phase被误调两次 | 低 | _current_phase标记检测，重复调用直接抛RuntimeError |

---

## OpenSpec 自检清单（openspec 阶段）

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 目标/非目标边界清晰 | ✅ | 目标：7阶段间Research Agent上下文隔离；非目标：Eval Agent不改、resume不改、落盘不改 |
| 模块边界清晰 | ✅ | 只改4个文件：task_state.py、agent_base.py、research_agent/agent.py、orchestrator.py |
| 核心API签名确定 | ✅ | `start_new_phase(phase, previous_summaries: list[dict])` |
| 核心数据结构确定 | ✅ | PhaseSummaryCard(dict)字段：phase/verdict/score/conclusion/artifact_ids/key_info/notes |
| 主流程伪代码已写 | ✅ | Orchestrator调用时机、is_revision分支、摘要卡生成时机都已明确 |
| 边界场景全覆盖 | ✅ | 7个边界场景全部有处理决策（BLOCKED/无artifact/REVISE失败结果/状态不一致/重复调用/阶段中途/resume） |
| 异常处理策略明确 | ✅ | 状态不一致抛异常、重复调用抛异常、不静默处理 |
| 验收标准可验证 | ✅ | 7个正向验收点 + 4个反例测试，全部可观测可验证 |
| 测试思路明确 | ✅ | 新建test_phase_isolation.py，正向三阶段+4反例 |
| 无模糊的"支持xx/做xx" | ✅ | 所有决策都是具体的、可执行的 |
| 无未决事项 | ✅ | 7维度grill-me已全部问完，无遗留问题 |
| 依赖关系明确 | ✅ | A01+A02一起做，D01/E02后续实现，不阻塞A01 |

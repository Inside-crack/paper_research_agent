# 上下文管理系统（Context Management System）- 需求总览

**模块编号**：5.7  
**模块名称**：上下文管理系统  
**创建日期**：2026-08-14  
**最后更新**：2026-08-18
**需求总数**：21（运行时13 + 存储/检索8）  
**已完成**：17（A01-A04, B01-B02, C01-C03, D01-D04, E01-E04）
**依赖模块**：P01任务创建、P03状态管理、N03可追溯性、N05可恢复性、N07可扩展性

---

## 一、背景与问题

### 1.1 现状痛点

当前项目采用朴素的上下文管理：

| 痛点 | 具体表现 | 后果 |
|------|----------|------|
| **多阶段累积** | 7阶段对话历史全量保留，越走越重 | 第4阶段起context爆涨，token消耗指数增加 |
| **工具结果冗余** | arXiv搜索90篇paper摘要全量塞入 | 单search结果就占好几K tokens |
| **阶段间无隔离** | paper_parsing阶段还能看到前3次arxiv raw搜索 | 干扰LLM决策，增加幻觉风险 |
| **超限报错** | 超窗口直接API报错400，无兜底 | 任务中途失败，不知道哪里截断了 |
| **锚点无保护** | 截断可能丢system prompt/research_spec | Agent"失忆"，不知道自己该干嘛 |
| **失败不可查** | 运行时context丢了就是丢了 | 调试失败原因只能凭console日志推测 |
| **检索无索引** | 落盘文件散落，不知哪个对应哪个阶段 | "存了"和"能用"之间有巨大gap |

### 1.2 设计目标

```
┌──────────────────────────────────────────────────────────────────┐
│ 运行时（不爆窗口 + 成本可控 + 决策准确）                            │
│   ├── A. 移出域 + 索引召回（阶段边界隔离）                         │
│   ├── B. 压缩替换（大段内容 → 摘要占位）                           │
│   └── C. 超限丢弃 + 锚点保护（兜底策略）                           │
│                                                                   │
│ 落盘检索（失败可调试 + 恢复可继续 + 上下文可审计）                   │
│   ├── D. 索引检索体系（清单+命名规范+CLI工具）                      │
│   └── E. 失败落盘持久化（ErrorContext + History + Plan）           │
└──────────────────────────────────────────────────────────────────┘
```

**关键目标量化**：

| 指标 | 现状 | 目标 |
|------|------|------|
| 单阶段运行时context（默认模式） | 15-25K tokens | 6-8K tokens |
| 7阶段全流程最大context | 可能爆128K | 稳定在8-15K tokens |
| REVISE后context增量 | ~2倍叠加 | +1-2K tokens（仅新增修正意见） |
| 失败后定位根因时间 | 十几分钟+猜 | <5分钟+证据确凿 |
| 单个任务落盘大小 | ~100KB（仅状态） | L1: 1-3MB, L2: 3-5MB |
| 列出所有失败任务 | 遍历目录猜 | 1条命令<10ms |

---

## 二、总体架构：三级运行时策略 + 两级存储检索

### 2.1 三级运行时策略（按触发优先级排序）

```
每次LLM调用前预计算token数：
┌─────────────────────────────────────────────────────────────┐
│ 优先级 1：A. 移出域（最温和，只清理跨阶段冗余）                 │
│   - 阶段完成后，历史对话→产物摘要卡，raw历史落盘                │
│   - 下一阶段只加载：System + Spec + 前序摘要卡 + 当前阶段Prompt │
│   - 召回：需要详细内容时通过 load_artifact 按需加载             │
└─────────────────────────────────────────────────────────────┘
          ↓ 还是超阈值（>模型窗口70%）时触发
┌─────────────────────────────────────────────────────────────┐
│ 优先级 2：B. 压缩替换（不丢信息，只降密度）                     │
│   - 工具执行结果→摘要占位符（如 [Step x: arxiv_search → 15]） │
│   - PDF全文→章节摘要卡 + 全文存artifact                        │
│   - 日志/stdout→最后N行 + 完整日志落盘                         │
└─────────────────────────────────────────────────────────────┘
          ↓ 还是超阈值（>模型窗口90%）时触发
┌─────────────────────────────────────────────────────────────┐
│ 优先级 3：C. 超限丢弃（丢信息但保锚点）                         │
│   - 先多维权重打分（时效性/信息密度/依赖关系/错误状态）          │
│   - 锚点绝对保护（System/Spec/修正意见/最近2轮）                │
│   - 从最低分开始丢弃，注入压缩提示                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 两级存储检索体系

```
data/artifacts/<task_id>/
├── 🔍 manifest.json           # 单任务索引：所有阶段+文件目录（几KB，先读它）
├── 🔍 task_state.json         # 最新状态快照
│
├── context/                   # 移出域的目的地（A层"域"所在）
│   ├── plans/                 # 每个阶段的完整ExecutionPlan
│   ├── agent_history/         # 移出的agent对话历史
│   ├── errors/                # ErrorContext + traceback
│   └── llm_calls/             # Debug模式：原始请求响应
│
├── evaluations/               # 每次EvaluationResult
├── checkpoints/               # 时间戳快照
├── artifacts/                 # save_artifact产物
└── logs/
    └── run.jsonl              # 结构化JSON Lines日志，grep友好
```

---

## 三、需求清单

### A. 移出域 + 索引召回（5个需求）

| ID | 需求名称 | 核心内容 | 优先级 | 状态 |
|----|----------|----------|--------|------|
| A01 | 阶段间上下文隔离 | 7阶段天然边界：阶段完成后清空Agent history，只加载System+Spec+前序产物摘要卡+当前Phase Prompt | P0 | ✅ 已完成 |
| A02 | 阶段产物摘要卡生成 | 每个阶段PASS后自动生成≤200字结构化摘要：包含关键决策、artifact引用id、核心数据 | P0 | ✅ 随A01完成 |
| A03 | REVISE重试策略优化 | REVISE时重置context避免锚定，结构化记录上一轮执行结果，精准注入correction_notes+已有数据消息；断点续跑留P2 | P1 | ✅ 已完成 |
| A04 | 工具结果自动落盘+按需召回 | 工具执行后自动存compact结果为artifact，step记录artifact_id；results_prompt标注artifact文件名，后续阶段可通过load_artifact加载 | P1 | ✅ 已完成 |
| A05 | 断点续跑（已成功步骤跳过） | REVISE时自动检测新Plan中与上一轮参数一致的成功步骤，跳过执行直接使用缓存结果（实验阶段刚需） | P2 | ⏸️ P2延后 |

### B. 压缩替换（5个需求）

| ID | 需求名称 | 核心内容 | 优先级 | 状态 |
|----|----------|----------|--------|------|
| B01 | arXiv搜索结果压缩 | _compact_result字段精简（7字段/abstract[:150]/authors[:1]）；results_prompt跨步骤去重+≤30篇上限+分区展示 | P0 | ✅ 已完成 |
| B02 | 工具执行结果通用压缩 | 各工具独立压缩分支+未知工具通用兜底（type/keys/size/preview）；非arxiv步骤>4000字符截断+artifact引用；load_artifact加载大dict/list时摘要展示 | P0 | ✅ 已完成 |
| B03 | PDF内容压缩策略 | PDF解析后：结构目录+各章节摘要卡保存在context；全文落盘，需要时load_artifact召回 | P1 | ⏸️ P2延后 |
| B04 | 实验日志/stdout压缩 | 命令行输出：最后50行在context，完整stdout/stderr落盘 | P2 | ⏸️ P2延后 |
| B05 | 代码仓库内容压缩 | 仓库分析：文件树摘要+关键文件函数签名，大文件/全量列表落盘 | P2 | ⏸️ P2延后 |

### C. 超限丢弃 + 锚点保护（3个需求）

| ID | 需求名称 | 核心内容 | 优先级 | 状态 |
|----|----------|----------|--------|------|
| C01 | 上下文token预计算与阈值触发 | 每次LLM调用前用字符数/4估算token数，70%→WARNING日志，85%→COMPRESS按priority丢弃，95%→CRITICAL激进压缩 | P0 | ✅ 已完成 |
| C02 | 锚点定义与绝对保护 | 锚点清单（System/Spec/Summaries/PhasePrompt/ResultsPrompt/REVISE注入），任何压缩不触碰锚点；SYSTEM消息硬保护 | P0 | ✅ 已完成 |
| C03 | 多维权重打分丢弃 | MVP版采用静态priority权重（20-100）按priority升序丢弃；CRITICAL时保留锚点+最后2条；压缩后注入notice | P1 | ✅ MVP已完成 |

### D. 索引检索体系（4个需求）

| ID | 需求名称 | 核心内容 | 优先级 | 状态 |
|----|----------|----------|--------|------|
| D01 | 结构化文件命名规范 | phase短名映射+artifact type枚举+{phase}_{step}_{type}[_r{n}].json命名pattern+反向解析；保持research_spec/task_state/checkpoint命名不变 | P0 | ✅ 已完成 |
| D02 | 单任务Manifest索引 | manifest.json记录task_id/topic/status/phases（每步状态摘要）/files清单；原子写；每步更新；plan/summary/output/eval自动落盘；写失败终止；旧任务自动补建 | P0 | ✅ 已完成 |
| D03 | 全局TasksIndex索引 | tasks_index.json汇总所有任务摘要；原子写tmp→os.replace；写失败降级（日志warn不终止）；不存在/损坏自动扫目录重建 | P0 | ✅ 已完成 |
| D04 | CLI上下文调试命令集 | 5条MVP命令JSON输出：tasks list/task show/task errors/task artifacts/task resume；错误exit 1；保持原run命令兼容 | P1 | ✅ MVP已完成 |

### E. 失败落盘持久化（4个需求）

| ID | 需求名称 | 核心内容 | 优先级 | 状态 |
|----|----------|----------|--------|------|
| E01 | ErrorContext结构化模型 | StepSnapshot/ErrorContext/PhaseCompletionRecord三模型；错误类型revise/blocked/exception/fatal；完整traceback+step_snapshots+messages_snapshot；文件名{phase}_error_r{n}.json/{phase}_fatal_error.json；{phase}_completion.json | P0 | ✅ 已完成 |
| E02 | 关键节点上下文自动落盘 | Orchestrator verdict Hook触发：PASS→PhaseCompletionRecord（轻量）；REVISE/BLOCKED/Exception→dump_error_context（全量plan+step_snapshots+messages+eval+traceback）；失败降级warn不crash；更新manifest.errors+files+tasks_index | P0 | ✅ 已完成 |
| E03 | 结构化JSONL日志文件 | 每任务独立logs/run.jsonl（append-only，flush/事件）；10种事件：phase_started/phase_completed/step_executed/revision_triggered/checkpoint_saved/error_dumped/warning/error/cleanup/task_completed；grep/jq友好；失败容忍warn | P1 | ✅ 已完成 |
| E04 | 保留策略与自动清理 | trim_checkpoints保留最近5个（grill-me决策）；触发时机：start_task恢复时+每次save_checkpoint后；cleanup事件写JSONL审计；≤keep时no-op；失败降级warn | P2 | ✅ MVP已完成 |

---

## 四、Research vs Evaluation Agent上下文管理差异

| 维度 | Research Agent（生产） | Evaluation Agent（评估） |
|------|------------------------|-------------------------|
| 模型 | V4-Flash（追求快/省） | V4-Pro（追求准） |
| 窗口压力 | 高（多轮工具调用） | 中（每阶段1-2次调用） |
| A-移出域策略 | 激进：阶段间硬隔离 | 保守：跨阶段保留完整证据链 |
| B-压缩策略 | 积极：Synthesize时压缩版 | 原始证据：Eval确定性检查需要完整数据 |
| C-丢弃策略 | 权重打分丢弃 | 仅在超阈值时压缩非锚点 |
| 落盘策略 | 运行时history落盘为artifact | Eval调用输入输出落盘 |

---

## 五、非功能约束

| 约束 | 要求 |
|------|------|
| **低侵入** | 核心Agent基类方法签名不修改；通过Hook+增量方法实现；所有TaskState新增字段Optional+default_factory |
| **向后兼容** | 旧checkpoint文件可直接加载；新索引文件不存在时不影响现有流程 |
| **可开关** | 每个子功能可独立开关（config.context.enable_out_of_domain / enable_compression / enable_weight_drop） |
| **性能** | 预计算token+权重打分单任务CPU开销<10ms（纯本地计算，不额外请求LLM） |
| **可验证** | 提供paper-agent context check <task_id>命令：输出当前各锚点token、预估token、各阶段context节省比例 |

---

## 六、建议实现顺序

**MVP第一阶段（必做，不做后面阶段跑不动）**：
1. ✅ **P0 A01 阶段间上下文隔离**（解决多阶段累积）
2. ✅ **P0 A02 阶段产物摘要卡**（A01的基础数据）
3. ✅ **P1 A03 REVISE重试策略优化**（覆盖原A05精准召回核心需求）
4. ✅ **P1 A04 工具结果自动落盘+按需召回**（跨阶段数据不丢失，load_artifact基础设施就绪）
5. ✅ **P0 B01 arXiv搜索结果压缩**（字段精简+跨步骤去重+30篇上限，单阶段context减少80%）
6. ✅ **P0 B02 工具结果通用压缩**（各工具独立分支+未知工具兜底，大结果截断+artifact引用）
7. ✅ **P0 C01 token预计算阈值触发**（字符数/4估算+70%/85%/95%三级触发）
8. ✅ **P0 C02 锚点绝对保护**（System/Spec/Summaries/PhasePrompt/Results永不丢，SYSTEM消息硬保护）
9. ✅ **P1 C03 权重打分丢弃MVP**（静态priority排序+CRITICAL激进丢弃+压缩notice注入）
10. ✅ **P0 D01 命名规范 + D02 Manifest + D03 TasksIndex**（存储检索基础）
11. ✅ **P0 E01 ErrorContext + E02 关键节点落盘**（失败可调试）

**MVP第二阶段（好用）**：
12. ✅ **P1 D04 CLI调试命令**（5条JSON命令MVP完成）
13. ✅ **P1 E03 JSONL日志**（per-task结构化事件日志）
14. ✅ **P2 E04 自动清理策略**（checkpoint保留5个）
15. ⏸️ P2 A05 断点续跑（实验阶段刚需）
16. ⏸️ P1 B03 PDF压缩（等paper_parsing）
17. ⏸️ P2 B04 实验日志压缩（等experiment_execution）
18. ⏸️ P2 B05 代码仓库压缩（等code_location）

**后续迭代**：
19. P2 C03 完整多维权重打分（时效性/信息密度/依赖/错误状态）
20. P2 E04 扩展：LLM calls TTL + 任务完成后L2清理（按需）

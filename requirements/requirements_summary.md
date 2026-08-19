# 论文研究与实验复现 Agent 项目需求清单

**项目名称**：论文研究与实验复现 Agent  
**文档版本**：V0.3  
**整理人**：喻祯帅  
**状态**：核心框架搭建完成，基础功能验证通过  
**创建日期**：2026-08-14  
**最后更新**：2026-08-14

---

## 需求定位

- **项目目标**：搭建论文检索、翻译与实验复现系统。
- **核心架构**：Research Agent 与 Evaluation Agent 配对开发。
- **质量原则**：每项主能力必须配套独立评估能力。
- **首版边界**：优先支持 arXiv 与公开代码论文。

---

## 项目概述

### 一、项目背景

研究生在开展论文调研和实验复现时，需要跨越论文检索、全文阅读、学术翻译、代码定位、环境配置、实验执行和结果对比等环节。现有工具通常只覆盖其中一段，且大模型生成结果存在随机性、证据不足和虚假完成风险。

本项目计划从 0 到 1 搭建一套双 Agent 系统：**Research Agent** 负责完成研究与复现任务，**Evaluation Agent** 对其产物和执行轨迹进行独立评估，形成可追溯、可修正、可持续优化的闭环。

### 二、项目目标

- 支持从研究主题到候选论文筛选的完整检索流程。
- 支持论文结构解析、术语管理、分章节翻译和内容总结。
- 支持官方代码、数据集、模型权重和实验配置的定位与验证。
- 支持复现可行性评估、实验规划、受控执行和结果比较。
- 为每项主干能力建立对应的评估能力和质量门禁。
- 保存完整任务状态、工具调用轨迹、实验日志和版本信息。

### 三、系统角色

| 角色 | 定位 | 职责 |
|------|------|------|
| **Research Agent** | 生产与执行 | 理解用户任务，完成论文检索、筛选、解析、翻译、代码分析、复现规划、实验执行和报告生成。 |
| **Evaluation Agent** | 评估与归因 | 读取原始证据、主 Agent 产物和执行轨迹，运行确定性检查与模型评估，输出通过、修正或阻塞结论。 |
| **Orchestrator** | 流程控制 | 以状态机控制任务阶段、质量门禁、修正次数、预算、人工确认和中断恢复；不负责复杂内容生成。 |

### 四、总体流程

1. 用户提交研究主题、具体论文或实验复现目标。
2. Research Agent 解析目标并生成结构化任务说明。
3. Research Agent 按检索、翻译、复现等阶段执行任务。
4. 每个阶段完成后，Evaluation Agent 检查产物和执行轨迹。
5. Evaluation Agent 输出 **PASS**、**REVISE** 或 **BLOCKED**。
6. REVISE 时由 Research Agent 定向修正；默认最多修正一次。
7. 通过阶段门禁后进入下一阶段，最终归档全部产物。

---

## 功能需求目录

### 5.1 任务管理

| 序号 | 需求ID | 需求名称 | 模块 | 状态 | 负责人 | 进度 |
|------|--------|----------|------|------|--------|------|
| 1 | P01 | 任务创建 | 任务管理 | 进行中 | | 90% |
| 2 | P02 | 目标与约束解析 | 任务管理 | 进行中 | | 85% |
| 3 | P03 | 任务状态管理 | 任务管理 | 进行中 | | 90% |
| 4 | P04 | 中断恢复 | 任务管理 | 进行中 | | 75% |

### 5.2 论文检索与筛选

| 序号 | 需求ID | 需求名称 | 模块 | 状态 | 负责人 | 进度 |
|------|--------|----------|------|------|--------|------|
| 5 | P05 | 研究主题拆解 | 论文检索与筛选 | 进行中 | | 70% |
| 6 | P06 | 论文检索 | 论文检索与筛选 | 进行中 | | 80% |
| 7 | P07 | 论文分类 | 论文检索与筛选 | 进行中 | | 70% |
| 8 | P08 | 论文排序推荐 | 论文检索与筛选 | 进行中 | | 70% |
| 9 | P09 | 目标论文确认 | 论文检索与筛选 | 待开始 | | 0% |

### 5.3 论文获取、解析与翻译

| 序号 | 需求ID | 需求名称 | 模块 | 状态 | 负责人 | 进度 |
|------|--------|----------|------|------|--------|------|
| 10 | P10 | 全文与版本获取 | 论文获取解析翻译 | 进行中 | | 15% |
| 11 | P11 | 论文结构解析 | 论文获取解析翻译 | 待开始 | | 0% |
| 12 | P12 | 术语表生成 | 论文获取解析翻译 | 待开始 | | 0% |
| 13 | P13 | 分章节翻译 | 论文获取解析翻译 | 待开始 | | 0% |
| 14 | P14 | 论文总结与解释 | 论文获取解析翻译 | 待开始 | | 0% |

### 5.4 代码、数据与复现资源

| 序号 | 需求ID | 需求名称 | 模块 | 状态 | 负责人 | 进度 |
|------|--------|----------|------|------|--------|------|
| 15 | P15 | 官方代码定位 | 代码数据复现资源 | 待开始 | | 5% |
| 16 | P16 | 代码版本确认 | 代码数据复现资源 | 待开始 | | 0% |
| 17 | P17 | 仓库结构分析 | 代码数据复现资源 | 待开始 | | 0% |
| 18 | P18 | 论文代码映射 | 代码数据复现资源 | 待开始 | | 0% |

### 5.5 复现规划与实验执行

| 序号 | 需求ID | 需求名称 | 模块 | 状态 | 负责人 | 进度 |
|------|--------|----------|------|------|--------|------|
| 19 | P19 | 复现目标定义 | 复现规划实验执行 | 待开始 | | 0% |
| 20 | P20 | 可行性评估 | 复现规划实验执行 | 待开始 | | 0% |
| 21 | P21 | 实验计划生成 | 复现规划实验执行 | 待开始 | | 0% |
| 22 | P22 | 隔离环境构建 | 复现规划实验执行 | 进行中 | | 10% |
| 23 | P23 | 实验执行 | 复现规划实验执行 | 待开始 | | 0% |
| 24 | P24 | 失败诊断与恢复 | 复现规划实验执行 | 待开始 | | 0% |

### 5.6 结果分析与报告

| 序号 | 需求ID | 需求名称 | 模块 | 状态 | 负责人 | 进度 |
|------|--------|----------|------|------|--------|------|
| 25 | P25 | 实验指标提取 | 结果分析与报告 | 待开始 | | 0% |
| 26 | P26 | 论文结果对比 | 结果分析与报告 | 待开始 | | 0% |
| 27 | P27 | 差异原因分析 | 结果分析与报告 | 待开始 | | 0% |
| 28 | P28 | 复现结果判定 | 结果分析与报告 | 待开始 | | 0% |
| 29 | P29 | 复现报告生成 | 结果分析与报告 | 待开始 | | 0% |

### 非功能需求

| 序号 | 需求ID | 需求名称 | 模块 | 状态 | 负责人 | 进度 |
|------|--------|----------|------|------|--------|------|
| 30 | N01 | 安全隔离 | 非功能需求 | 进行中 | | 10% |
| 31 | N02 | 成本控制 | 非功能需求 | 进行中 | | 60% |
| 32 | N03 | 可追溯性 | 非功能需求 | 进行中 | | 85% |
| 33 | N04 | 真实性 | 非功能需求 | 进行中 | | 65% |
| 34 | N05 | 可恢复性 | 非功能需求 | 进行中 | | 75% |
| 35 | N06 | 可审计性 | 非功能需求 | 进行中 | | 75% |
| 36 | N07 | 可扩展性 | 非功能需求 | 进行中 | | 90% |
| 37 | N08 | 数据隐私 | 非功能需求 | 待开始 | | 0% |

### 5.7 上下文管理系统（新增：运行时+落盘闭环）

**设计总览文档**：[context_management_summary.md](file:///Users/bytedance/workspace/paper_research_agent/requirements/5.7_上下文管理系统/context_management_summary.md)

**设计理念**：三级运行时策略（A移出域→B压缩替换→C超限丢弃）+ 两级存储检索体系（D索引+E落盘）

| 序号 | 需求ID | 需求名称 | 分组 | 优先级 | 状态 | 进度 |
|------|--------|----------|------|--------|------|------|
| 38 | A01 | 阶段间上下文隔离 | A.移出域 | P0 | 待开始 | 0% |
| 39 | A02 | 阶段产物摘要卡生成 | A.移出域 | P0 | 待开始 | 0% |
| 40 | A03 | 阶段内轮次历史滑动窗口 | A.移出域 | P1 | 待开始 | 0% |
| 41 | A04 | 工具结果按需召回机制 | A.移出域 | P1 | 待开始 | 0% |
| 42 | A05 | REVISE精准召回 | A.移出域 | P0 | 待开始 | 0% |
| 43 | B01 | arXiv搜索结果压缩 | B.压缩替换 | P0 | 进行中 | 30% |
| 44 | B02 | 工具执行结果通用压缩 | B.压缩替换 | P0 | 待开始 | 0% |
| 45 | B03 | PDF内容压缩策略 | B.压缩替换 | P1 | 待开始 | 0% |
| 46 | B04 | 实验日志/stdout压缩 | B.压缩替换 | P2 | 待开始 | 0% |
| 47 | B05 | 代码仓库内容压缩 | B.压缩替换 | P2 | 待开始 | 0% |
| 48 | C01 | 上下文token预计算与阈值触发 | C.超限丢弃 | P0 | 待开始 | 0% |
| 49 | C02 | 锚点定义与绝对保护 | C.超限丢弃 | P0 | 待开始 | 0% |
| 50 | C03 | 多维权重打分丢弃 | C.超限丢弃 | P1 | 待开始 | 0% |
| 51 | D01 | 结构化文件命名规范 | D.索引检索 | P0 | 待开始 | 0% |
| 52 | D02 | 单任务Manifest索引 | D.索引检索 | P0 | 待开始 | 0% |
| 53 | D03 | 全局TasksIndex索引 | D.索引检索 | P0 | 待开始 | 0% |
| 54 | D04 | CLI上下文调试命令集 | D.索引检索 | P1 | 待开始 | 0% |
| 55 | E01 | ErrorContext结构化模型 | E.落盘持久化 | P0 | 待开始 | 0% |
| 56 | E02 | 关键节点上下文自动落盘 | E.落盘持久化 | P0 | 待开始 | 0% |
| 57 | E03 | 结构化JSONL日志文件 | E.落盘持久化 | P1 | 待开始 | 0% |
| 58 | E04 | 保留策略与自动清理 | E.落盘持久化 | P2 | 待开始 | 0% |

---

## 六、评估机制要求

- **独立输入**：Evaluation Agent 同时读取用户原始任务、原始证据、Research Agent 产物和完整 Trace。
- **避免锚定**：评估 Agent 应先基于原始证据形成判断，再对比主 Agent 结论。
- **确定性优先**：数字、公式、引用、退出码、文件、指标和版本等优先使用程序检查。
- **结构化输出**：统一输出 PASS、REVISE 或 BLOCKED，并附问题类型、严重程度、位置、证据和修正要求。
- **有限修正**：默认只允许一次定向修正，禁止无边界自我循环。
- **局部复查**：修正后优先复查问题项及其影响范围，不重新生成全部产物。
- **独立配置**：两个 Agent 使用独立 Prompt；预算允许时可使用不同模型进行交叉验证。

---

## 七、数据与产物要求

系统至少保存以下结构化产物：

- **ResearchSpec**：用户目标、范围、预算与约束。
- **PaperCandidateSet**：候选论文、来源、元数据和筛选理由。
- **PaperArtifact**：原文、解析结果、术语表、译文和总结。
- **ReproductionSpec**：代码版本、数据、环境、实验目标和资源估算。
- **ExperimentRun**：命令、配置、随机种子、日志、资源消耗和指标。
- **EvaluationResult**：评估结论、评分、问题、证据和修正要求。
- **FinalReport**：复现结果、差异分析、限制和可追溯链接。

---

## 八、已完成核心架构盘点（2026-08-14）

### 1. 项目基础架构 ✅
- [x] 项目目录结构（src/paper_agent 标准Python包结构）
- [x] pyproject.toml 依赖管理
- [x] config/default.yaml 配置（DeepSeek V4-Flash/V4-Pro）
- [x] .env 环境变量管理
- [x] CLI入口框架（cli.py, __main__.py）
- [x] 结构化日志配置

### 2. LLM抽象层 ✅
- [x] BaseLLM 抽象基类
- [x] OpenAI兼容HTTP客户端（httpx）
- [x] LLM Factory（支持deepseek/deepseek-v4-flash/deepseek-v4-pro/openai）
- [x] 双LLM配置：Research用V4-Flash（快、便宜、Agent友好），Evaluation用V4-Pro（旗舰推理）
- [x] 消息历史管理（System/User/Assistant/Tool角色）

### 3. 核心数据模型 ✅（全部7类产物模型已定义）
- [x] ResearchSpec（用户目标/范围/预算/约束）
- [x] TaskState + StageStatus（任务/阶段状态追踪）
- [x] ExecutionPlan + PlanStep（执行计划）
- [x] EvaluationResult + Issue（评估结果/问题）
- [x] PaperCandidate + PaperCandidateSet（候选论文集）
- [x] PaperArtifact（论文产物）
- [x] ReproductionSpec（复现规格）
- [x] ExperimentRun（实验运行记录）
- [x] FinalReport（最终报告）
- [x] TraceEntry（执行轨迹）
- [x] Budget（预算配置）

### 4. Agent框架 ✅
- [x] BaseAgent 抽象基类（Plan→Execute→Synthesize模式）
- [x] generate_plan() LLM生成JSON执行计划
- [x] _parse_llm_to_plan() JSON解析+重试
- [x] synthesize_result() 结果综合
- [x] _extract_json() Markdown代码块提取
- [x] _try_fix_json() 截断JSON自动修复（补全括号/大括号）
- [x] 工具描述注入prompt
- [x] 结果压缩（_compact_result 截断arXiv结果减少token）

### 5. Research Agent ✅
- [x] 系统prompt（角色定义、工作流、输出格式）
- [x] **全部7个阶段prompt模板**：
  - task_initialization（任务初始化）
  - paper_retrieval（论文检索）
  - paper_parsing（论文解析）
  - code_location（代码定位）
  - reproduction_planning（复现规划）
  - experiment_execution（实验执行）
  - result_reporting（结果报告）
- [x] 阶段prompt变量替换（research_spec/current_state/available_tools等）

### 6. Evaluation Agent ✅
- [x] V4-Pro模型，temperature=0.0（确定性推理）
- [x] 独立系统prompt
- [x] evaluate_phase() 阶段评估主逻辑
- [x] **确定性检查优先**，然后LLM评估
- [x] 7阶段检查清单（分阶段验证规则）
- [x] 证据收集（_gather_evidence）
- [x] 输入截断优化（_trim_evidence/_trim_output减少token）
- [x] 结构化输出：verdict(PASS/REVISE/BLOCKED) + score + issues[]

### 7. Orchestrator 状态机 ✅
- [x] 7阶段状态机（phase transitions）
- [x] _execute_phase_flow()：Plan→Validate→HumanConfirm→Execute→Deduplicate→Synthesize→Save→Evaluate
- [x] 质量闸门处理（PASS→下阶段，REVISE→有限重试，BLOCKED→失败）
- [x] 修订次数控制（max_revisions_per_stage=1）
- [x] 预算追踪（token/wall_time/revision计数）
- [x] Plan验证（未知工具检查、空步骤检查）
- [x] 顺序工具执行+错误处理
- [x] task_id自动传递给工具
- [x] 阶段产物保存到metadata
- [x] **arXiv搜索结果预去重**（Orchestrator端跨查询去重，减少LLM负担）
- [x] Hook机制（phase hooks/verdict hooks/plan validation hooks）
- [x] 人工确认接口预留

### 8. 工具系统 ✅
- [x] BaseTool 抽象基类
- [x] Tool Registry 注册中心（可扩展插件架构）
- [x] register_all_tools() 自动注册
- [x] 工具参数灵活处理（**kwargs兼容）
- [x] 已实现工具：
  - [x] **arxiv_search**：arXiv搜索（关键词/分类/结果数，返回结构化结果）
  - [x] **arxiv_get_paper**：单篇论文详情获取
  - [x] **save_artifact**：产物保存（到data/artifacts/<task_id>/）
  - [x] **load_artifact**：产物加载
  - [x] **download_file**：文件下载框架
- [x] 工具目录预留：code/filesystem/paper_processing/sandbox/common

### 9. 持久化框架 ✅
- [x] BasePersistence 接口
- [x] save_checkpoint()/load_checkpoint()
- [x] save_evaluation_result()/load_evaluation_result()
- [x] Artifact文件系统存储框架

### 10. 测试验证 ✅
- [x] examples/test_task_init.py 单阶段初始化测试
- [x] examples/test_phase_init.py 阶段初始化测试
- [x] examples/test_two_phases.py 两阶段E2E测试（init→retrieval）
- [x] DeepSeek API连通验证
- [x] 双Agent质量闭环验证：
  - 任务初始化稳定PASS（0.95-1.0分）
  - 论文检索阶段完整执行，Evaluation Agent正确识别质量问题给出REVISE

---

## 九、首版 MVP 范围

首版重点：先验证双 Agent 配对架构和质量闭环，不追求任意论文的全自动完整复现。

**包含范围：**
- 领域：机器学习、人工智能与 Agent 相关论文。
- 来源：优先 arXiv，补充官方网页与公开代码仓库。
- 检索：主题解析、候选论文检索、去重、分类和可复现性排序。
- 翻译：单篇论文全文解析、术语表、分章节翻译和一致性评估。
- 代码：官方仓库验证、代码版本确认和实验入口分析。
- 复现：完成可行性评估和 R2 级实验规划；受控跑通 Demo 或小数据趋势实验。
- 评估：每个阶段均输出结构化 EvaluationResult，并支持一次定向修正。

**明确不做：**
- 任意学科、任意论文来源的全覆盖。
- 多机多卡、大规模预训练和高成本完整复现。
- 无人确认地执行未知脚本或购买云资源。
- 自动修改或提交论文作者的远程代码仓库。
- Evaluation Agent 直接覆盖 Research Agent 产物。
- 两个 Agent 无限循环修正。

---

## 十、后续待确认

- [x] ~~确定使用DeepSeek V4-Flash/V4-Pro作为基座模型~~ ✅ 已确认
- [ ] 确定首版支持的具体研究方向与示例论文。
- [ ] 确定本地或云端可用的 CPU、GPU、内存和磁盘预算。
- [ ] 确定首版交互形式：命令行、Web 页面或对话界面。
- [ ] 为第一组配对能力制定验收标准和测试数据集。

---

## 十一、已解决的技术卡点

| 问题 | 根因 | 解决方案 |
|------|------|----------|
| Python 3.9不支持`X \| None`语法 | Python版本兼容 | 所有受影响文件添加`from __future__ import annotations` |
| str.format()与JSON示例大括号冲突 | prompt模板中含JSON示例花括号 | 改用简单的`str.replace("{key}", value)`变量替换 |
| 无原生function calling，TOOL角色消息不支持 | DeepSeek非原生函数调用 | record_step_result()改为no-op，结果通过_build_results_prompt()聚合传入 |
| 工具参数名`name`与artifact的"name"参数冲突 | registry.execute参数名碰撞 | 改为`tool_name`参数，kwargs.pop("name", None)兼容 |
| save_artifact参数名不匹配（LLM传content而非data） | LLM输出参数名不一致 | SaveArtifactTool通过kwargs.get()兼容data/content/artifact_name/name |
| task_id未传递给工具 | 上下文传递缺失 | _execute_plan()中显式添加args["task_id"] = task_state.id |
| Evaluation Agent输入过大导致400/截断 | 6×20篇论文结果太大 | 添加_trim_evidence/_trim_output，_compact_result截断arXiv结果 |
| LLM返回list而非dict导致AttributeError | 模型输出格式不固定 | _parse_llm_to_json()检测list，取第一个元素或包装为dict |
| JSON截断导致解析失败（Unterminated string） | max_tokens不足或输出过长 | _try_fix_json()自动补全缺失的括号/大括号，增加max_tokens到8192 |
| arXiv搜索结果重复（跨查询） | 多关键词搜索结果重叠 | Orchestrator端_deduplicate_search_results()按arxiv_id去重 |

---

## 需求统计

- 总需求数：58（功能需求29 + 非功能需求8 + 上下文管理21）
  - 其中上下文管理系统21个：
    - A 移出域：5个
    - B 压缩替换：5个
    - C 超限丢弃：3个
    - D 索引检索：4个
    - E 落盘持久化：4个
- 已完成：0
- 进行中：15（P01-P08, P10, P22, N01-N07, B01）
- 待开始：43
- 阻塞：0
- **核心框架完成度：~75%**
- **上下文管理系统文档完成度：100%（21个子需求已拆解）**

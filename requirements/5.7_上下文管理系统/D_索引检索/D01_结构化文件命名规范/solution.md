# D01 结构化文件命名规范 - 实现方案

**需求ID**：D01
**需求名称**：结构化文件命名规范
**创建日期**：2026-08-14
**最后更新**：2026-08-18
**优先级**：P0
**依赖需求**：A04（自动落盘基础设施）

---

## 一、需求背景与目标

### 1.1 背景
当前artifact文件命名分散且不统一：
- checkpoint用`checkpoint_{timestamp}.json`（已规范）
- eval用`eval_{phase}_{id}.json`（已部分规范）
- A04自动落盘用`step_{step_id}_{tool}_result.json`（缺phase信息）
- synthesize产物（candidates.json/domain.json等）由LLM随意命名，无规范
- 后果：glob/ls无法按phase/type过滤；不知道文件属于哪个阶段；REVISE文件无法区分轮次

### 1.2 目标
1. 所有artifact文件名本身携带元数据（phase/step_id/type/revision）
2. glob/ls即可完成80%的过滤检索
3. 与现有checkpoint/research_spec/task_state命名兼容（不重命名已有文件）
4. A04自动落盘改用新命名

### 1.3 范围
- **In Scope**：
  - [ ] 定义phase短名映射
  - [ ] 定义artifact type枚举
  - [ ] 定义命名pattern
  - [ ] A04 auto_persist改用新命名
  - [ ] plan/summary/output自动落盘使用新命名
  - [ ] revision轮次后缀（_r1/_r2）
- **Out of Scope**：
  - 不重命名已有的research_spec.json/task_state.json/checkpoint_*.json
  - 不修改SaveArtifactTool的通用能力（LLM调save_artifact时的命名不强制，但Orchestrator自动保存的产物用规范名）

---

## 二、功能规格

### 2.1 核心功能规则

**phase短名映射**（文件名用短名避免过长）：

| 完整phase名 | 文件名短名 |
|------------|----------|
| task_initialization | task_init |
| paper_retrieval | paper_retrieval |
| paper_parsing | paper_parsing |
| code_location | code_loc |
| reproduction_planning | repro_plan |
| experiment_execution | exp_exec |
| result_reporting | result_report |

**artifact type枚举**：

| type | 含义 | 命名pattern | 示例 |
|------|------|-------------|------|
| spec | 任务规格 | 保持research_spec.json（不重命名） | research_spec.json |
| plan | 阶段ExecutionPlan | {phase_short}_plan.json | paper_retrieval_plan.json |
| result | 步骤成功结果 | {phase_short}_{step_id}_{tool}_result.json | paper_retrieval_s1_arxiv_search_result.json |
| error | 步骤失败信息 | {phase_short}_{step_id}_{tool}_error[_r{n}].json | paper_retrieval_s3_arxiv_search_error.json, paper_retrieval_s3_arxiv_search_error_r1.json |
| eval | 阶段评估结果 | {phase_short}_eval_{verdict}.json | paper_retrieval_eval_passed.json |
| summary | 阶段摘要卡 | {phase_short}_summary.json | paper_retrieval_summary.json |
| output | synthesize最终产物 | {phase_short}_output.json | paper_retrieval_output.json |
| checkpoint | 状态快照 | 保持checkpoints/checkpoint_{ts}.json | checkpoint_20260817_180000.json |
| state | 最新状态 | 保持task_state.json | task_state.json |

**revision规则**：
- 首轮正常执行：无revision后缀（等效r0）
- REVISE第1轮：新产生的文件加_r1后缀
- REVISE第N轮：加_r{n}后缀
- 同一artifact在同一轮次内不重复（覆盖写入）

**保持不变的文件**：
- research_spec.json
- task_state.json
- checkpoints/checkpoint_*.json
- evaluations/eval_{phase}_{id}.json（现有路径，manifest记录路径）

### 2.2 命名辅助函数
新增模块`src/paper_agent/common/persistence/naming.py`：
- `phase_short(phase: TaskPhase) -> str`：phase名到短名映射
- `artifact_filename(phase, step_id, tool, artifact_type, revision=None) -> str`：生成规范文件名
- `parse_artifact_filename(name) -> dict | None`：反向解析文件名提取元数据（用于CLI/manifest构建）

### 2.3 边界条件与异常处理

| 场景 | 预期行为 |
|------|----------|
| phase不在映射表 | 使用完整phase名（降级） |
| revision=0 | 不添加_r0后缀 |
| step_id为空（非步骤类文件如plan/eval/summary/output） | 省略step_id和tool段 |
| tool名含特殊字符 | 原样使用（SaveArtifactTool已有路径安全处理） |

### 2.4 与双Agent质量门禁的适配
- 不需要Evaluation Agent评估（命名规范是确定性的）
- 验收通过单元测试验证命名pattern的正则匹配

### 2.5 验收标准
- [ ] D01-1：`artifact_filename()`对所有type生成符合pattern的文件名
- [ ] D01-2：`parse_artifact_filename()`能正确反向解析
- [ ] D01-3：A04自动落盘成功文件用新命名（{phase}_{step}_{tool}_result.json）
- [ ] D01-4：A04自动落盘失败文件用新命名（{phase}_{step}_{tool}_error[_r{n}].json）
- [ ] D01-5：首轮文件无_r0后缀，REVISE轮次带_r1/_r2
- [ ] D01-6：research_spec.json/task_state.json/checkpoint_*.json命名保持不变
- [ ] D01-7：单元测试覆盖所有type的命名和反向解析
- [ ] D01-8：负向测试：未知phase降级为全名；revision=0不加后缀

---

## 三、技术方案（公共架构，D02-D04共用）

### 3.1 整体思路
在StatePersistence中扩展manifest和tasks_index能力；Orchestrator在现有的hook点（_execute_phase_flow中各阶段）调用StatePersistence方法更新manifest；CLI从manifest和index读取数据。

### 3.2 架构设计

```
Orchestrator
  ├─ start_task()
  │   ├─ StatePersistence.create_task_manifest()  ← D02 创建manifest
  │   └─ StatePersistence.update_tasks_index()    ← D03 更新全局索引
  ├─ _execute_phase_flow()
  │   ├─ manifest_update_phase_started()          ← D02 phase开始
  │   ├─ save phase_plan.json                     ← D01+D02
  │   ├─ _execute_plan() 每步执行完
  │   │   ├─ _auto_persist_step_result/error      ← D01 新命名
  │   │   └─ manifest_update_step()               ← D02 更新step状态+files
  │   ├─ save phase_eval_{verdict}.json           ← D01+D02
  │   ├─ _build_phase_summary_card() + save       ← D01+D02 summary
  │   ├─ save phase_output.json                   ← D01+D02 synthesize结果
  │   └─ manifest_update_phase_completed()        ← D02 phase完成
  └─ run()结束
      ├─ manifest_update_task_completed()         ← D02
      └─ update_tasks_index()                     ← D03

CLI (paper-agent)
  ├─ tasks list    → StatePersistence.list_tasks()     ← D03读index
  ├─ task show     → StatePersistence.load_manifest()  ← D02读manifest
  ├─ task errors   → 读manifest.phases[*].errors
  ├─ task artifacts→ 读manifest.files
  └─ task resume   → 已有load_checkpoint，更新manifest
```

### 3.3 接口设计

**新增模块**：
- `src/paper_agent/common/persistence/naming.py`：命名辅助函数
- `src/paper_agent/common/persistence/manifest.py`：Manifest/Index模型+读写
- `src/paper_agent/cli/`目录：拆分CLI子命令

**StatePersistence新增方法**：
- `create_task_manifest(spec: ResearchSpec) -> dict`
- `update_task_manifest(task_id, updater: callable)`：原子读-改-写manifest
- `save_phase_plan(task_id, phase, plan: ExecutionPlan) -> Path`
- `save_phase_summary(task_id, phase, summary_card: dict) -> Path`
- `save_phase_output(task_id, phase, output: dict) -> Path`
- `save_phase_eval(task_id, phase, verdict, eval_result: EvaluationResult) -> Path`
- `update_step_in_manifest(task_id, phase, step: PlanStep, revision: int)`
- `record_error_in_manifest(task_id, phase, step, error_msg, revision, artifact_name)`
- `complete_task_manifest(task_id, final_status)`
- `rebuild_manifest_if_missing(task_id) -> dict`：补建旧任务的manifest
- `update_tasks_index(task_id=None)`：更新/重建全局index
- `list_tasks() -> list[dict]`：读tasks_index
- `load_manifest(task_id) -> dict`
- `atomic_write_json(path, data)`：原子写（tmp→os.replace）

**CLI子命令**（使用argparse子解析器或click）：
- `paper-agent tasks list`
- `paper-agent task show <task_id>`
- `paper-agent task errors <task_id>`
- `paper-agent task artifacts <task_id>`
- `paper-agent task resume <task_id>`

### 3.4 影响面分析
- 需要修改的文件：
  - `src/paper_agent/common/persistence/state_persistence.py`（扩展方法）
  - `src/paper_agent/orchestrator/orchestrator.py`（hook点调用manifest更新，A04改命名）
  - `src/paper_agent/cli.py`（拆分CLI为子命令）
  - `src/paper_agent/common/agent_base.py`（_build_results_prompt里artifact_id用新名）
- 需要新增的文件：
  - `src/paper_agent/common/persistence/naming.py`
  - `src/paper_agent/common/persistence/manifest.py`（Manifest模型+Index模型）
  - `examples/test_d01_d04_indexing.py`
- 需要回归的现有功能：
  - A03 REVISE流程（revision命名）
  - A04自动落盘（新命名）
  - checkpoint/resume功能（补建manifest）

### 3.5 风险评估与应对

| 风险点 | 影响等级 | 应对措施 |
|--------|----------|----------|
| manifest写失败导致任务终止 | 高 | 符合A04策略（落盘失败=流程终止），单元测试验证 |
| A04改名导致artifact_id引用断裂 | 中 | artifact_id在Orchestrator内部统一传递，不硬编码旧名 |
| tasks_index并发写冲突 | 低 | 原子写（os.replace）；损坏时自动重建 |
| 旧任务无manifest | 低 | resume时detect缺失→基于task_state补建 |
| CLI改动影响现有run命令 | 低 | 保留`paper-agent <query>`作为run的默认行为 |

---

## 四、实施任务拆分

| 任务ID | 任务描述 | 依赖 | 复杂度 | 验收子标准 |
|--------|----------|------|--------|------------|
| T1 | D01 naming.py：phase短名+artifact_filename+parse+单元测试 | 无 | S | 所有type生成正确文件名；反向解析正确 |
| T2 | D02 manifest.py：Manifest模型+原子写+CRUD方法 | T1 | M | create/update/read/rebuild均工作 |
| T3 | D02 Orchestrator集成：hook点调用manifest更新；plan/summary/output自动落盘；A04改用新命名 | T1,T2 | L | 两阶段流程后manifest完整、所有文件命名正确 |
| T4 | D03 tasks_index：原子更新+自动重建+list_tasks | T2 | S | 多任务创建后index正确；删除index可重建 |
| T5 | D04 CLI子命令：tasks list/task show/errors/artifacts/resume | T2,T4 | M | 5条命令输出合法JSON，错误情况exit 1 |
| T6 | 回归测试+E2E验证 | T3,T4,T5 | M | 所有旧测试通过；两阶段E2E demo可用 |

## 实现步骤总览
1. T1: naming.py + 单元测试
2. T2: manifest.py Manifest模型+原子写+CRUD
3. T3: Orchestrator集成（manifest hook+D01改名+plan/summary/output落盘）
4. T4: tasks_index + list_tasks + rebuild
5. T5: CLI子命令
6. T6: 回归+E2E验证

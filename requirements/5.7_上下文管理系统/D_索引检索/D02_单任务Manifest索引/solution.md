# D02 单任务Manifest索引 - 实现方案

**需求ID**：D02
**需求名称**：单任务Manifest索引
**创建日期**：2026-08-14
**最后更新**：2026-08-18
**优先级**：P0
**依赖需求**：D01（命名规范）、A04（自动落盘）

> 架构设计、接口设计、影响面、任务拆分等公共部分见 D01 solution.md

---

## 一、需求背景与目标

### 1.1 背景
当前要了解一个任务的状态，需要：读task_state.json（大文件）+ 遍历目录ls + 逐个cat文件拼凑。没有一个统一的入口文件能"秒懂"任务进展。

### 1.2 目标
1. 每个任务根目录一个manifest.json（5-15KB），打开即可了解任务状态
2. 记录各阶段verdict/score/errors/artifacts
3. 每步状态摘要（tool/status/artifact/error/duration_ms）
4. 所有artifact文件清单（name/type/phase/size_bytes）
5. 写失败终止流程（和A04一致）

### 1.3 范围
- **In Scope**：
  - [ ] Manifest数据模型定义
  - [ ] 原子读-改-写（避免写半）
  - [ ] Orchestrator各hook点更新manifest
  - [ ] plan/summary/output/eval自动落盘
  - [ ] 旧任务无manifest时自动补建
- **Out of Scope**：
  - LLM不读manifest（Orchestrator注入方式不变）
  - manifest不存大result内容（只存引用路径）

---

## 二、功能规格

### 2.1 Manifest数据模型

```json
{
  "task_id": "uuid",
  "topic": "研究主题前100字",
  "status": "running|passed|failed|blocked",
  "current_phase": "paper_retrieval",
  "current_revision": 0,
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "phases": {
    "task_initialization": {
      "status": "passed|running|failed|not_started",
      "score": 1.0,
      "verdict": "passed|revised|blocked|failed|null",
      "started_at": "ISO8601",
      "ended_at": "ISO8601|null",
      "revisions": 0,
      "artifacts": {
        "spec": "research_spec.json",
        "plan": null,
        "eval": null,
        "summary": "task_init_summary.json",
        "output": null
      },
      "steps": {
        "s1": {"tool": "xxx", "status": "success|failed", "artifact": "xxx.json", "error": null, "duration_ms": 1234}
      },
      "errors": [
        {"step_id": "s3", "tool": "arxiv_search", "error": "Connection timeout", "revision": 0, "artifact": "paper_retrieval_s3_error.json"}
      ]
    }
  },
  "files": [
    {"name": "research_spec.json", "type": "spec", "phase": "task_initialization", "size_bytes": 1234}
  ],
  "total_errors": 0,
  "total_revisions": 0
}
```

### 2.2 核心功能规则

1. **manifest创建**：`start_task()`时调用`create_task_manifest()`，初始manifest包含task_id/topic/status=running/current_phase=task_initialization/created_at，phases为所有7个阶段初始化为not_started
2. **phase开始**：`_execute_phase_flow()`开头更新phases.{phase}.status=running/started_at/current_phase
3. **plan落盘**：generate_plan后自动保存{phase}_plan.json，更新phases.{phase}.artifacts.plan
4. **step完成**：每步执行完（成功/失败）更新phases.{phase}.steps.{step_id}，追加files记录；失败时追加phases.{phase}.errors
5. **eval落盘**：Evaluation返回后保存{phase}_eval_{verdict}.json，更新artifacts.eval/score/verdict
6. **summary落盘**：PASS后_build_phase_summary_card()结果保存{phase}_summary.json，更新artifacts.summary
7. **output落盘**：synthesize_result返回后保存{phase}_output.json，更新artifacts.output
8. **phase完成**：verdict处理后更新phases.{phase}.status/ended_at/revisions
9. **任务完成**：run()结束时更新manifest.status=passed/failed/blocked
10. **REVISE覆盖**：REVISE时steps覆盖（最新状态），旧error保留在errors数组和files中
11. **原子写**：先写manifest.json.tmp，fsync后os.replace()为manifest.json

### 2.3 更新频率
- 任务创建：写1次
- phase开始：写1次
- 每步执行完（成功+失败）：写1次
- eval后：写1次
- summary/output：写1次
- phase完成：写1次
- 任务完成：写1次

每写一次约几KB磁盘IO，7阶段×平均5步≈42次写，开销可忽略。

### 2.4 边界条件与异常处理

| 场景 | 预期行为 |
|------|----------|
| manifest写失败 | raise RuntimeError终止流程（和A04一致） |
| manifest不存在（旧任务） | resume/CLI访问时基于task_state.json+目录扫描补建 |
| manifest JSON损坏 | CLI返回错误JSON exit 1；Orchestrator启动时检测到损坏则重建 |
| 磁盘满/权限错误 | raise RuntimeError（不降级） |
| REVISE时同step_id已存在 | 覆盖steps.{step_id}（最新状态），旧文件保留在files |
| 并发写manifest | 不存在（单任务单Orchestrator asyncio串行） |
| artifact文件被手动删除 | CLI显示[missing]，不崩溃不修复 |

### 2.5 验收标准
- [ ] D02-1：start_task后manifest.json存在且合法JSON，包含所有7个phase初始状态
- [ ] D02-2：phase开始时manifest.phases.{phase}.status=running
- [ ] D02-3：每步执行后steps.{step_id}更新（success/failed），files追加记录
- [ ] D02-4：plan/summary/output/eval自动落盘，artifacts字段更新
- [ ] D02-5：REVISE时steps覆盖，errors历史保留
- [ ] D02-6：manifest写失败raise RuntimeError
- [ ] D02-7：旧任务（无manifest）resume时自动补建
- [ ] D02-8：manifest大小控制在30KB以内（典型场景≤15KB）
- [ ] D02-9：负向测试：磁盘满时raise RuntimeError；损坏manifest返回错误

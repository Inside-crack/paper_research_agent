# 需求实现方案

**需求ID**：E03  
**需求名称**：结构化JSONL日志文件  
**优先级**：P1  
**创建日期**：2026-08-14  
**最后更新**：2026-08-18

---

## 需求描述

每个任务目录下独立的 `run.jsonl` 结构化日志文件，单行JSON格式，grep/jq友好。记录关键节点事件（phase_start/phase_end/step_start/step_end/revision/checkpoint/error_dump）+ warning/error级别日志。不替代全局paper_agent.log，而是按task_id分流的辅助调试日志。

## 方案设计

### 整体思路

新增 `TaskJsonLogger` 类：每个任务创建一个logger实例，append写 `{task_dir}/run.jsonl`。事件级别：
- `phase_started` / `phase_completed`：阶段生命周期
- `step_executed`：步骤执行结果
- `revision_triggered`：REVISE触发
- `checkpoint_saved`：checkpoint保存
- `error_dumped`：ErrorContext落盘
- `warning` / `error`：关键警告/错误（非debug/info）

不记录普通info/debug日志（避免jsonl膨胀）。全局structlog `paper_agent.log` 保持不变。

### 文件位置

`data/artifacts/{task_id}/logs/run.jsonl`

### 日志条目格式

```json
{"ts":"2026-08-18T12:00:00","event":"phase_started","phase":"paper_retrieval","revision":0}
{"ts":"2026-08-18T12:00:05","event":"step_executed","step_id":"s1","tool":"arxiv_search","success":true,"duration_ms":1500,"artifact":"paper_retrieval_s1_arxiv_search_result.json"}
{"ts":"2026-08-18T12:01:00","event":"revision_triggered","phase":"exp_exec","revision":1,"reason":"score 0.6 below threshold"}
{"ts":"2026-08-18T12:02:00","event":"error_dumped","error_type":"exception","error_file":"exp_exec_fatal_error.json","message":"KeyError: 'results'"}
{"ts":"2026-08-18T12:03:00","event":"checkpoint_saved","checkpoint":"checkpoint_paper_parsing_s2.json"}
{"ts":"2026-08-18T12:03:01","event":"phase_completed","phase":"result_reporting","verdict":"PASS","score":0.95,"duration_ms":120000}
```

### 架构位置

- 新增 `src/paper_agent/common/persistence/task_jsonl_logger.py`
- Orchestrator.start_task()时初始化TaskJsonLogger
- 在各关键节点调用log方法
- append模式打开，每条事件flush
- 写入失败降级（warn不抛异常）

### 与logging.py的关系

- 全局structlog (paper_agent.log)：保留，收集所有进程日志
- TaskJsonLogger (run.jsonl)：新增，仅关键事件+warn/error，per-task文件
- 两者独立，不互相干扰

### 大小控制

- 单个任务jsonl预计最大几MB（7阶段×若干step+错误），不需要rotate
- E04清理时如果任务超过保留期，整个任务目录删除，jsonl自然清理

## 实现步骤

1. 创建TaskJsonLogger类
2. 在Orchestrator集成（start_task时初始化，各节点调用）
3. 单元测试验证jsonl格式+append+flush

## 依赖项

- [x] D01 命名规范

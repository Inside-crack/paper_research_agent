# 需求实现进展

**需求ID**：E04  
**需求名称**：保留策略与自动清理  
**优先级**：P2  
**当前状态**：已完成 ✅  
**创建日期**：2026-08-14
**完成日期**：2026-08-18

---

## 需求描述

防止磁盘无限膨胀：checkpoints最多N个；触发时机：任务启动时+每次checkpoint保存后。

> 注：根据grill-me决策调整：仅实现checkpoint保留策略（keep=5），LLM calls TTL和任务完成后L2清理暂不实现（YAGNI，当前无L2调试目录）。清理事件通过JSONL日志记录审计。

## 核心验收点

- [x] checkpoints：按mtime排序保留最近5个（grill-me决策），超出自动删除
- [x] 触发时机：start_task()恢复任务时 + 每次save_checkpoint后
- [x] 清理事件写JSONL日志（cleanup事件，记录count+deleted列表）
- [x] trim失败降级为warn不抛异常
- [x] ≤keep时no-op

## 进度概览

- [x] 方案设计确认（grill-me决策：keep=5，启动+checkpoint后触发）
- [x] StatePersistence.trim_checkpoints()实现
- [x] Orchestrator两处触发点集成
- [x] 单元测试通过（2项E04测试）
- [x] 全量回归通过

## 进展记录

### 2026-08-18

- StatePersistence新增trim_checkpoints(task_id, keep=5) -> list[str]：
  - 列出task_dir/checkpoints/下所有checkpoint_*.json
  - 按mtime降序排序（最新在前）
  - 保留前keep个，删除其余
  - 返回被删除的文件名列表
  - 异常时logger.error返回空列表（降级）
- Orchestrator集成：
  - start_task()恢复路径：调用trim_checkpoints，通过event_logger.cleanup()记录
  - run() loop每次save_checkpoint后：调用trim_checkpoints(keep=5)，记录cleanup事件
- 单元测试：10个checkpoint保留5个删除5个；3个checkpoint(≤5)时no-op

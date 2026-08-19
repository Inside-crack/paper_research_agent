# 需求实现方案

**需求ID**：E04  
**需求名称**：保留策略与自动清理  
**优先级**：P2  
**创建日期**：2026-08-14  
**最后更新**：2026-08-18

---

## 需求描述

自动清理策略防止磁盘无限增长：checkpoints保留最近N个；旧任务自动清理。Orchestrator启动时和写checkpoint后触发。

## 方案设计

### MVP范围（本次实现）

仅实现**checkpoint数量限制**：保留最近5个checkpoint，旧的自动删除。
- LLM调用记录/大文件TTL暂不实现（P2延后）
- 失败任务保留永不删除（便于调试）
- 完成任务保留不自动删除（MVP阶段磁盘压力不大）

### 清理时机

1. **Orchestrator启动时**：start_task()中resume路径，加载checkpoint后调用cleanup
2. **写checkpoint后**：save_checkpoint成功后调用trim_checkpoints

### 清理逻辑

```python
def trim_checkpoints(task_dir: Path, keep: int = 5) -> list[str]:
    """保留最近keep个checkpoint，删除多余的，返回被删除的文件名列表"""
    checkpoints = sorted(task_dir.glob("checkpoint_*.json"), 
                        key=lambda p: p.stat().st_mtime, reverse=True)
    old = checkpoints[keep:]
    deleted = []
    for p in old:
        p.unlink()
        deleted.append(p.name)
    return deleted
```

### 错误处理

- 清理失败（权限/文件被占用）→ warn日志，不影响主流程
- 不在事务中（checkpoint文件本身已写入成功）

### manifest同步

删除checkpoint后更新manifest中的files列表（可选，因为scan_artifacts会过滤不存在的文件）。MVP阶段不做同步：
- CLI artifacts命令会显示exists=false标记
- manifest重建时会重新scan

### 未来扩展（不实现）

- 完成任务N天后归档/删除
- LLM调用记录TTL
- 大文件（>10MB）压缩归档
- paper-agent cleanup CLI命令

## 实现步骤

1. 在state_persistence.py新增 `trim_checkpoints(task_id, keep=5)` 方法
2. Orchestrator.start_task() resume路径调用
3. save_checkpoint后调用
4. TaskJsonLogger记录cleanup事件
5. 单元测试

## 依赖项

- [x] D02 Manifest

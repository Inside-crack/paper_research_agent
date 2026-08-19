# D03 进度跟踪

**需求ID**：D03
**需求名称**：全局TasksIndex索引
**状态**：✅ 已完成
**完成度**：100%
**最后更新**：2026-08-18

---

## 进度记录

| 日期 | 完成事项 | 状态 | 完成度 | 下一步 |
|------|----------|------|--------|--------|
| 2026-08-14 | 需求文档创建 | 待开始 | 0% | - |
| 2026-08-18 | grill-me需求澄清完成，openspec方案设计完成（与D01/D02/D04合并实现） | 🔨 实现中 | 20% | T2: TasksIndex/TaskIndexEntry模型 |
| 2026-08-18 | ✅ TasksIndex实现完成: TasksIndex/TaskIndexEntry Pydantic模型; update_tasks_index增量更新(try/except降级为warn); _rebuild_tasks_index全量扫描重建; list_tasks()自动处理缺失/损坏index(备份.corrupt+重建); 原子写(tmp+os.replace); 所有manifest写操作自动触发index增量更新 | ✅ 完成 | 100% | CLI list_tasks命令验证 |

### 设计决策
- index非关键路径，写入失败只warn不终止
- index损坏自动备份到.tasks_index.json.corrupt然后全量重建
- list_tasks()是入口点，缺失/损坏时透明重建
- TaskIndexEntry包含task_id/topic/status/current_phase/latest_score/errors/revisions/timestamps，用于CLI列表展示

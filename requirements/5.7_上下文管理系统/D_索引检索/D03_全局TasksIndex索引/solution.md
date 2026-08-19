# D03 全局TasksIndex索引 - 实现方案

**需求ID**：D03
**需求名称**：全局TasksIndex索引
**创建日期**：2026-08-14
**最后更新**：2026-08-18
**优先级**：P0
**依赖需求**：D02（manifest）

> 架构设计、接口设计、影响面、任务拆分等公共部分见 D01 solution.md

---

## 一、需求背景与目标

### 1.1 背景
当前列出所有任务需要`ls data/artifacts/`遍历子目录，只能看到task_id（UUID），不知道每个任务是什么主题、跑到哪个阶段、是否失败。

### 1.2 目标
1. artifacts根目录一个tasks_index.json，不需要遍历目录就能看到所有任务
2. 每个任务一行摘要：task_id/topic/status/current_phase/latest_score/errors/revisions/created_at/updated_at
3. 原子写避免并发损坏
4. 损坏时自动重建（降级不阻塞）

### 1.3 范围
- **In Scope**：
  - [ ] TasksIndex数据模型
  - [ ] 原子更新（tmp→os.replace）
  - [ ] 写失败降级（日志warn，不终止流程）
  - [ ] 自动重建（index不存在/损坏时扫目录读manifest）
  - [ ] 增量更新（单任务状态变化时只更新对应条目）
- **Out of Scope**：
  - 不做文件锁（原子写+重建足够）
  - 不做watch实时监控（按需更新）

---

## 二、功能规格

### 2.1 TasksIndex数据模型

位置：`data/artifacts/tasks_index.json`

```json
{
  "updated_at": "ISO8601",
  "version": 1,
  "tasks": [
    {
      "task_id": "uuid",
      "topic": "研究主题前80字",
      "status": "running|passed|failed|blocked",
      "current_phase": "paper_retrieval",
      "latest_score": 0.85,
      "total_errors": 2,
      "total_revisions": 1,
      "created_at": "ISO8601",
      "updated_at": "ISO8601",
      "manifest_path": "uuid/manifest.json"
    }
  ]
}
```

### 2.2 核心功能规则

1. **创建时机**：第一个任务创建时自动生成tasks_index.json
2. **更新时机**：
   - 任务创建后（新增条目）
   - 每步manifest更新后（增量更新对应条目）
   - 任务完成后（更新status）
3. **原子写**：写tasks_index.json.tmp→fsync→os.replace()
4. **写失败处理**：日志warning级别记录，不raise异常（不终止任务），因为单任务manifest是真相源
5. **读取时校验**：
   - 文件不存在：触发全量重建
   - JSON解析失败：触发全量重建（备份旧文件为tasks_index.json.corrupt）
   - version不匹配：触发全量重建
6. **全量重建逻辑**：
   - 遍历data/artifacts/下所有子目录
   - 对每个子目录尝试读manifest.json
   - 成功则提取摘要加入index；失败则跳过（日志warn）
   - 按updated_at降序排列
   - 原子写回tasks_index.json
7. **增量更新逻辑**：
   - 读现有index（不存在/损坏则重建）
   - 找到对应task_id条目更新（不存在则追加）
   - 更新updated_at
   - 原子写回

### 2.3 边界条件与异常处理

| 场景 | 预期行为 |
|------|----------|
| tasks_index.json不存在 | list_tasks()触发全量重建 |
| tasks_index.json JSON损坏 | 备份为.corrupt，全量重建，日志warn |
| 两个进程同时写index | 后写覆盖先写（os.replace原子），下次list_tasks检测updated_at滞后则增量更新 |
| 写index时磁盘满 | 日志error，不终止任务流程 |
| 某个任务目录无manifest | 重建时跳过该任务，日志warn |
| 空artifacts目录（无任何任务） | index写入空tasks数组 |

### 2.4 验收标准
- [ ] D03-1：首个任务创建后tasks_index.json存在且包含该任务
- [ ] D03-2：任务状态变化时index对应条目更新
- [ ] D03-3：删除tasks_index.json后list_tasks()自动重建
- [ ] D03-4：写入损坏JSON后list_tasks()自动重建（备份旧文件）
- [ ] D03-5：写index失败不抛异常（降级日志）
- [ ] D03-6：原子写验证（写入过程中不会出现半写文件）
- [ ] D03-7：空任务目录时index正确（tasks:[]）
- [ ] D03-8：负向测试：无权限写index时任务继续运行不崩溃

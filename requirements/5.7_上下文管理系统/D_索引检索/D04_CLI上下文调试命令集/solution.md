# D04 CLI上下文调试命令集 - 实现方案

**需求ID**：D04
**需求名称**：CLI上下文调试命令集
**创建日期**：2026-08-14
**最后更新**：2026-08-18
**优先级**：P1
**依赖需求**：D02（manifest）、D03（tasks_index）

> 架构设计、接口设计、影响面、任务拆分等公共部分见 D01 solution.md

---

## 一、需求背景与目标

### 1.1 背景
当前CLI只有`paper-agent <query>`一个run命令，debug时只能手动`ls data/artifacts/{task_id}/`+`cat xxx.json`+`jq`组合使用，效率低。

### 1.2 目标
1. 提供5个核心调试命令（MVP1阶段）
2. 所有输出是合法JSON（jq友好）
3. 错误情况返回错误JSON + exit code 1
4. 保持`paper-agent <query>`原有run行为不变（向后兼容）

### 1.3 范围
- **In Scope**（MVP先做的5条命令）：
  - [ ] `paper-agent tasks list`：列出所有任务摘要
  - [ ] `paper-agent task show <task_id>`：展示完整manifest
  - [ ] `paper-agent task errors <task_id>`：列出所有错误
  - [ ] `paper-agent task artifacts <task_id>`：列出所有artifact文件
  - [ ] `paper-agent task resume <task_id>`：从checkpoint恢复任务
- **Out of Scope（后续迭代/E组再做）**：
  - `task plan`（等E03 JSONL日志后做）
  - `task history`（等E组落盘对话历史后做）
  - `task logs`（E03 JSONL日志）
  - 表格/美化输出（先只做JSON）
  - 交互式TUI

---

## 二、功能规格

### 2.1 CLI结构设计

使用argparse子解析器：

```
paper-agent
├── <query> [--paper URL] [--resume ID]   # 原有run命令（保持兼容）
├── tasks
│   └── list                              # 列出所有任务
└── task
    ├── show <task_id>                    # 展示manifest
    ├── errors <task_id>                  # 错误列表
    ├── artifacts <task_id>               # 文件清单
    └── resume <task_id>                  # 恢复任务
```

向后兼容：`paper-agent "LLM agent survey"`（无明确子命令）继续作为run命令工作。

### 2.2 各命令规格

**`paper-agent tasks list`**
- 输出：`{"tasks": [{task_id, topic, status, current_phase, ...}], "total": N, "updated_at": "..."}`
- 数据源：读tasks_index.json（不存在/损坏则自动重建）
- 按updated_at降序

**`paper-agent task show <task_id>`**
- 输出：完整manifest.json内容（原样输出，不做加工）
- task_id不存在：`{"error": "task_not_found", "task_id": "xxx"}` exit 1
- manifest损坏：`{"error": "manifest_corrupted", "task_id": "xxx", "detail": "..."}` exit 1
- 自动检测并重建缺失的manifest（基于task_state）

**`paper-agent task errors <task_id>`**
- 输出：`{"task_id": "xxx", "errors": [{phase, step_id, tool, error, revision, artifact}], "total": N}`
- 收集所有phases.*.errors平铺为列表
- task_id不存在：同show

**`paper-agent task artifacts <task_id>`**
- 输出：`{"task_id": "xxx", "files": [{name, type, phase, size_bytes, exists: bool}], "total": N}`
- 检查每个文件是否存在于磁盘，exists=false标记[missing]
- task_id不存在：同show

**`paper-agent task resume <task_id>`**
- 等价于`paper-agent --resume <task_id>`（已有功能）
- 输出：`{"task_id": "xxx", "status": "resumed", "checkpoint": "task_state.json"}`然后开始run
- 如果没有checkpoint：`{"error": "no_checkpoint_found", "task_id": "xxx"}` exit 1

### 2.3 全局错误格式

所有错误情况统一输出：
```json
{
  "error": "error_code",
  "message": "human readable message",
  "task_id": "xxx"（如果适用）
}
```
exit code：成功0，错误1。

### 2.4 边界条件与异常处理

| 场景 | 预期行为 |
|------|----------|
| 无参数调用 | 打印help（保持现有行为） |
| task_id不存在 | error JSON + exit 1 |
| manifest JSON损坏 | error JSON + exit 1 |
| tasks_index.json损坏 | 自动重建，不报错 |
| artifact目录不存在 | error JSON + exit 1 |
| resume时无checkpoint | error JSON + exit 1 |
| 文件存在但不可读（权限） | error JSON + exit 1 |

### 2.5 验收标准
- [ ] D04-1：`paper-agent tasks list`输出合法JSON数组
- [ ] D04-2：`paper-agent task show <id>`输出完整manifest JSON
- [ ] D04-3：`paper-agent task errors <id>`输出扁平错误列表JSON
- [ ] D04-4：`paper-agent task artifacts <id>`输出文件清单JSON（含exists标记）
- [ ] D04-5：`paper-agent task resume <id>`能恢复任务
- [ ] D04-6：`paper-agent <query>`原有run命令继续工作
- [ ] D04-7：task_id不存在时输出error JSON exit 1
- [ ] D04-8：所有输出都是合法JSON（可直接jq管道）

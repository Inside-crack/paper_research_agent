# D04 进度跟踪

**需求ID**：D04
**需求名称**：CLI上下文调试命令集
**状态**：✅ 已完成
**完成度**：100%（MVP 5条命令）
**最后更新**：2026-08-18

---

## 进度记录

| 日期 | 完成事项 | 状态 | 完成度 | 下一步 |
|------|----------|------|--------|--------|
| 2026-08-14 | 需求文档创建 | 待开始 | 0% | - |
| 2026-08-18 | grill-me需求澄清完成（用户选择a: LLM不读manifest; 先做5条MVP命令; 纯JSON输出不要表格） | 🔨 实现中 | 30% | T5: cli.py子命令实现 |
| 2026-08-18 | ✅ CLI实现完成: argparse子命令重构; 保持原run命令向后兼容; 5条MVP命令全部JSON输出(jq-friendly); 错误统一返回error JSON+exit code 1 | ✅ 完成 | 100% | 后续可扩展artifact内容查看/context-inspect/manual-rebuild等P1命令 |

### 命令清单（MVP P0）
| 命令 | 功能 | 输出 |
|------|------|------|
| `paper-agent tasks list` | 列出所有任务 | `{"tasks":[...], "total":N}` |
| `paper-agent task show <task_id>` | 展示单个任务完整manifest | manifest JSON |
| `paper-agent task errors <task_id>` | 列出任务所有阶段错误 | `{"task_id":..., "errors":[...], "total":N}` |
| `paper-agent task artifacts <task_id>` | 列出任务所有artifact文件 | `{"task_id":..., "files":[...], "total":N}` (含exists标记) |
| `paper-agent task resume <task_id>` | 从最新checkpoint恢复任务 | 任务状态JSON |

### 错误格式（统一）
```json
{"error": "task_not_found", "message": "...", "task_id": "..."}
```
exit code = 1

### 设计决策
- 纯JSON输出，不做表格格式化（jq友好，便于脚本集成）
- 原run命令保持位置参数+--paper/--resume flag向后兼容
- task not found / manifest corrupt / no checkpoint 统一error JSON

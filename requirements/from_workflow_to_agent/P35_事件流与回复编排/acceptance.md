# P35 验收清单

## 验收结果

| 检查项 | 结果 |
|---|---|
| AgentEvent 序列化/反序列化 | 通过 |
| session/task/correlation 查询 | 通过 |
| Task 创建前事件允许空 task_id | 通过 |
| Task 创建后 Workflow 事件带 task_id | 通过 |
| JSONL 损坏事件检测 | 通过 |
| 非法关联字段和 event_type 拒绝 | 通过 |
| EventStore 持久化失败阻断主流程 | 通过 |
| 实时订阅和 Session 隔离 | 通过 |
| 订阅者失败不影响已持久化事件 | 通过 |
| ResponseComposer 状态回复 | 通过 |
| 回复和事件敏感信息过滤 | 通过 |
| Artifact 绝对路径过滤 | 通过 |
| P31-P34 全量回归 | 通过 |

## 执行命令

P35 专项测试：

```bash
python3 -m pytest -q examples/test_p35_*.py
```

结果：

```text
20 passed
```

全量回归：

```bash
python3 -m pytest -q
```

结果：

```text
367 passed, 3 warnings
```

警告为既有 LibreSSL 环境提示和 Pydantic 弃用提示，不影响测试结果。

## 交付边界

- CLI 使用 `CliProgressSubscriber` 输出实时进度。
- `/events` 查询当前 Session 的历史事件。
- 未来 HTTP API 复用 `AgentEvent.model_dump(mode="json")`，不重新定义事件格式。
- 事件持久化和实时通知均执行安全过滤。
- P35 不负责 SSE/WebSocket 传输，连接层属于后续 API 阶段。

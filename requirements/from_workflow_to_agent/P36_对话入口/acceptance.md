# P36 验收清单

## 验收结果

| 检查项 | 结果 |
|---|---|
| 同一 Session 连续发送多条消息 | 通过 |
| 检索、选择、确认和启动 Task 多轮流程 | 通过 |
| Session/Task 绑定持久化 | 通过 |
| 服务重新加载后恢复 Session 和 Task | 通过 |
| 重复 request_id 不重复执行 | 通过 |
| 失败响应重放保持原 HTTP 状态码 | 通过 |
| 跨 principal 读取 Session 被拒绝 | 通过 |
| Task checkpoint 启动恢复 | 通过 |
| 多 Worker lease 互斥 | 通过 |
| paused/unbound Task 不自动接管 | 通过 |
| SSE 历史事件补发 | 通过 |
| `Last-Event-ID` 断线续传 | 通过 |
| SSE 实时事件推送 | 通过 |
| SSE 客户端断开自动解绑 | 通过 |
| 跨 Session SSE 订阅被拒绝 | 通过 |
| `run` CLI 回归 | 通过 |
| P31-P35 全量回归 | 通过 |

## 测试结果

P36 专项测试：

```bash
python3 -m pytest -q examples/test_p36_*.py
```

结果：

```text
11 passed
```

全量回归：

```bash
python3 -m pytest -q
```

结果：

```text
378 passed, 3 warnings
```

警告为既有 LibreSSL 环境提示和 Pydantic 弃用提示，不影响测试结果。

## 当前边界

- P36 第一阶段为单机多进程恢复，lease 使用本地文件。
- 多主机分布式锁和外部任务队列不在本阶段范围内。
- WebSocket 不实现，事件入口统一使用 SSE。
- 鉴权当前通过 `X-Principal-ID` 扩展点模拟，正式 JWT/API Key 属于后续接入。

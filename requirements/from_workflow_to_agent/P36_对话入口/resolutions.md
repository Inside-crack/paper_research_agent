# P36 决策

| 决策 | 结论 |
|------|------|
| R36-1 | 保留现有 run CLI，新增 chat 入口，不破坏一次性任务调用 |
| R36-2 | HTTP 第一阶段采用 FastAPI + Uvicorn 作为可选 web 依赖 |
| R36-3 | 事件传输第一阶段采用 SSE，复用 P35 AgentEvent JSON 格式；WebSocket 暂不作为必需项 |
| R36-4 | request_id 在 Session 内幂等，相同请求返回原响应，不同请求内容复用同一 ID 返回 409 |
| R36-5 | HTTP 断开不取消后台 Task，Task 通过 ApplicationService 和 checkpoint 独立运行 |

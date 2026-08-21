# P32 决策

| 决策 | 结论 |
|------|------|
| R32-1 | Router 只选择 Capability，不直接执行底层 Tool |
| R32-2 | P32 收敛为 Capability Registry、Preconditions 和 Intent Router；执行由后续 Workflow/Orchestrator 负责 |
| R32-3 | Capability 同时支持 `tool` 和 `workflow` 两种 execution_kind，但 P32 只保存和解析元数据，不执行对象 |
| R32-4 | 同名 Capability 只允许注册一次；重复注册报错，disabled 能力不可被 Router 选择 |
| R32-5 | `intent` 与 `capability_name` 分离；前者描述用户目标，后者描述系统能力 |
| R32-6 | `IntentDecision` 是 Router 的唯一输出契约，低置信度、非法 JSON 或缺少参数时不得产生可执行决策 |
| R32-7 | 前置条件读取 `PreconditionContext(session, task_state, artifact_refs)`，不扫描文件系统猜测 artifact |
| R32-8 | 简单格式明确的操作优先走确定性规则，模糊自然语言再调用 LLM |
| R32-9 | LLM Router 输出采用 JSON Schema 校验；失败只重试当前 Router 调用，仍失败则返回澄清 |
| R32-10 | P32 的实现顺序固定为 Capability 模型与 Registry -> Preconditions -> Intent Schema -> Router -> P31 Session 集成 |
| R32-11 | P32 拆分为 T32-0 至 T32-5；首个实现包含最小执行契约和已有 Tool 的 Capability Adapter，不实现 Registry、Router 或 LLM |
| R32-12 | 当前可封装能力为 paper_search、paper_download、paper_parse、paper_glossary、paper_translate、paper_summary |
| R32-13 | paper_search 由 arxiv_search 和 arxiv_get_paper 组成；paper_select 当前没有独立 Tool，由 P34 用户确认流程负责 |
| R32-14 | save_artifact、load_artifact、download_file 属于内部基础设施 Tool，不直接暴露给对话 Agent |
| R32-15 | Adapter 统一接受 ExecutionContext 和业务参数，统一返回 CapabilityResult；底层 ToolResult 的 success/data/error 不直接暴露给 Router |
| R32-16 | 最小闭环先采用确定性 IntentRouter，不依赖 LLM；后续再增加 LLM Router |
| R32-17 | 最小 Chat 只注册 `paper_search`，不自动选择论文、不启动 P10-P14 |
| R32-18 | 先完成已确定能力的 Adapter 封装和统一输入输出契约，再实现动态 IntentRouter；动态路由不得反向定义能力边界 |
| R32-19 | 复杂意图识别拆分为 Schema、Capability Catalog、Provider、上下文投影、LLM 决策、校验、混合路由、澄清、安全和评测等子需求，按依赖顺序逐项实现 |

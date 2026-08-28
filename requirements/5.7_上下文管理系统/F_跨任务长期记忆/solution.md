# F：跨任务长期记忆系统 - 方案概要

## 1. 总体架构

```text
ConversationStore / EventStore / TaskState / Artifact
                         |
                         v
                 MemoryCandidate
                         |
              结构化筛选 + 去重候选召回
                         |
                 语义整合与冲突判断
                         |
                         v
                    MemoryStore
                         |
          user_id + scope + query + budget
                         |
                         v
                 ContextProjection
                         |
                         v
                     Router / Agent
```

## 2. 责任边界

| 组件 | 负责内容 | 不负责内容 |
|------|----------|------------|
| `ConversationStore` | 原始会话和消息 | 长期记忆归纳 |
| `StatePersistence` | 任务状态、checkpoint、Manifest、Artifact | 跨任务用户记忆 |
| `MemoryStore` | L1 记忆生命周期 | 当前任务状态 |
| `MemoryExtractor` | 提取候选记忆 | 最终事实裁决 |
| `MemoryConsolidator` | 去重、更新、合并 | 绕过权限直接写入 |
| `ContextProjector` | 对已召回结果做安全投影 | 读取文件、检索或修改记忆 |
| `Orchestrator` | 在关键节点发布记忆事件 | 直接维护长期记忆文件 |

## 3. 首期实现原则

1. 原始记录先落盘，记忆候选异步提炼；
2. 先做结构化过滤，再做语义判断；
3. 记忆写入和召回都必须带用户隔离条件；
4. LLM 不直接决定最终持久化状态；
5. 记忆失败只影响个性化增强，不影响主流程；
6. 任务 Artifact 与用户长期记忆默认分离；
7. 所有更新保留来源、版本和被替代记录。

## 4. F06/F07 召回技术方案

### 4.1 召回职责拆分

召回链路拆为三个独立组件：

```text
当前请求/会话上下文
          |
          v
MemoryRecallService
  1. 构造查询
  2. 权限和 scope 过滤
  3. 候选检索
  4. 排序和去重
  5. 字符/token预算裁剪
          |
          v
IntentContextProjector
  只负责把已召回结果投影为安全模型
          |
          v
Router / Agent
```

职责边界：

| 组件 | 负责 | 不负责 |
|------|------|--------|
| `MemoryRecallService` | 查询、权限、排序、预算、降级 | 修改记忆 |
| `MemoryStore` | 持久化和基础过滤 | 决定当前请求需要什么 |
| `IntentContextProjector` | 输出受限 `ProjectedMemory` | 读取文件或执行检索 |
| Router/Agent | 使用召回结果进行推理 | 自行绕过权限读取记忆 |

`ContextProjector` 保持无文件访问特性，召回结果由调用方显式传入。这避免上下文投影组件隐式依赖磁盘，也便于单元测试。

### 4.2 查询输入

首期查询由以下信息组合而成：

```text
当前用户消息
+ current_intent
+ selected_paper.title / arxiv_id / keywords
+ selected_sections
+ 当前任务研究主题（如果存在）
```

以下内容不得作为召回查询：

- 当前任务的完整 Artifact 内容；
- 未经过预算裁剪的全部历史消息；
- 其他用户或其他 Owner 的内容；
- 历史任务的“已完成”状态。

查询对象使用结构化模型，避免由字符串拼接决定权限：

```python
class MemoryRecallQuery(BaseModel):
    owner_user_id: str
    text: str = ""
    scope: Optional[MemoryScope] = None
    memory_types: list[MemoryType] = []
    topic_key: Optional[str] = None
    limit: int = 5
    max_chars: int = 6000
```

### 4.3 首期检索策略：确定性关键词召回

首期不依赖向量模型，直接对 `MemoryStore` 中的 `active` 记忆做确定性检索：

1. 过滤 `owner_user_id`；
2. 过滤 `status=active`；
3. 过滤未过期记忆；
4. 按 scope 和 topic_key 做结构化过滤；
5. 对查询和记忆内容做统一归一化；
6. 使用中文连续字片段、英文词项和论文 ID 进行匹配；
7. 计算词项命中分数；
8. 按综合分排序并去重；
9. 应用 Top-K 和字符预算。

论文 ID、模型名、错误码、数据集名等精确标识优先保留，不能只依赖语义相似度。

综合排序首期采用可解释规则：

```text
score =
    lexical_match * 0.55
  + priority       * 0.20
  + confidence     * 0.15
  + recency        * 0.10
```

其中：

- `lexical_match` 必须达到最低阈值，避免只因高 priority 注入无关记忆；
- `priority` 使用记忆写入时的优先级；
- `confidence` 使用候选被验证时的置信度；
- `recency` 只用于同等相关记忆的排序，不覆盖明确的事实匹配。

### 4.4 后续检索演进

`MemoryRecallService` 对上层暴露稳定接口，内部检索器可按阶段替换：

```text
MVP：JSON 扫描 + 确定性关键词
  ↓
M1：SQLite FTS5/BM25 + 结构化索引
  ↓
M2：Embedding + FTS5 并行召回
  ↓
M3：RRF 融合 + 轻量重排
```

后续混合检索必须保持以下不变：

- 先做 Owner 和 scope 权限过滤；
- 向量召回不能绕过状态和过期过滤；
- 召回结果必须带来源和分数；
- embedding 服务失败时降级到关键词召回；
- 不因召回后端升级改变当前任务状态。

### 4.5 投影模型和注入格式

`IntentContextProjection` 增加只读字段：

```python
relevant_memories: list[ProjectedMemory]
```

`ProjectedMemory` 只允许暴露：

```text
memory_id
content
memory_type
scope
confidence
source_task_id
source_artifact_ids
relevance_score
```

不向 Router 暴露内部路径、Owner 管理字段或删除状态。

注入内容必须明确区分历史记忆和当前任务：

```text
<relevant-long-term-memories>
以下是从历史任务召回的相关记忆，仅作为参考；
不代表当前任务已完成，也不能替代当前任务的工具事实。

1. ...
</relevant-long-term-memories>
```

动态召回结果放在本轮 user context 中，不放入稳定 System Prompt，避免破坏 Prompt Cache。稳定的全局研究偏好后续可以单独形成低频更新的静态片段。

### 4.6 预算与降级

首期默认预算：

| 项目 | 默认值 |
|------|--------|
| 召回条数 | 5 |
| 记忆总字符数 | 6000 |
| 单条记忆字符数 | 1200 |
| 主动搜索次数 | 预留，默认 0 |
| 召回超时 | 本地同步检索不超过 100ms |

预算裁剪顺序：

1. 丢弃相关性低于阈值的候选；
2. 丢弃低 priority 候选；
3. 截断单条内容；
4. 截断总结果；
5. 保留来源和“可继续查询”提示。

降级规则：

- 记忆文件损坏：返回空召回并记录 warning；
- 检索超时：返回空召回；
- embedding/FTS5 不可用：回退关键词检索；
- 权限信息不完整：拒绝召回；
- 无 `user_id`：不召回用户长期记忆；
- 记忆服务失败：不得影响 Router、Workflow 或 Orchestrator。

### 4.7 接入点

第一阶段接入 `ConversationService.handle_message()`：

```text
保存用户消息
  → 构造 MemoryRecallQuery
  → MemoryRecallService.search()
  → ContextProjector.project(..., memories=...)
  → Router.route()
```

第二阶段接入任务启动：

```text
确认任务
  → 召回与研究主题相关的记忆
  → 只保存 memory_ids 和受限快照
  → ResearchAgent 新阶段注入历史参考区
```

任务恢复时优先使用 `memory_ids` 重新召回，不把长期记忆全文复制进 `TaskState`，避免 checkpoint 膨胀和历史内容失控。

### 4.8 关键安全约束

1. `MemoryRecallService` 的所有公开方法必须要求 `owner_user_id`；
2. `MemoryStore` 不提供无 Owner 的“搜索全部记忆”接口；
3. `deleted`、`expired`、`superseded` 记忆默认不可召回；
4. 历史记忆不能覆盖 `TaskState`、当前论文身份或工具返回事实；
5. 记忆来源只作为参考证据，确定性工具事实优先级更高；
6. 召回日志只记录 memory_id、分数、数量和耗时，不记录完整私有内容。

## 5. F06/F07 实施顺序

1. 新增 `MemoryRecallQuery`、`ProjectedMemory` 和 `RecallResult`；
2. 为 `MemoryStore` 增加 Owner 强制的关键词搜索接口；
3. 实现 `MemoryRecallService` 的过滤、排序、去重和预算；
4. 扩展 `IntentContextProjector.project()` 接收召回结果；
5. 接入 `ConversationService` 的 Router 前置链路；
6. 接入 `ConversationApplicationService` 和任务启动链路；
7. 增加跨任务、越权、预算、损坏和降级测试；
8. 再引入 SQLite FTS5 和 embedding，不提前耦合具体检索后端。

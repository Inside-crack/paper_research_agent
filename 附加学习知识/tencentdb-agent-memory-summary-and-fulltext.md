# 记忆不是存下来的，是取舍出来的——拆解腾讯 TencentDB Agent Memory

**来源链接：** https://bytetech.info/articles/7677848128308903942

## 详细中文总结

### 一、核心观点

文章通过阅读 TencentDB Agent Memory 的 v2.0.x 源码（commit `97f9465`），提出一个贯穿全文的判断：**Agent 记忆系统最困难的不是“如何存储更多”，而是“如何持续取舍”**。项目的关键设计都在做减法：写入时过滤低价值信息，聚合时限制场景数量，召回时限定条数、分数、字符预算和超时时间；当记忆能力出现故障时，宁可完全不注入记忆，也不阻塞 Agent 的主对话流程。

### 二、分层记忆与系统组成

项目不是单纯的向量数据库或 RAG 封装，而是一套覆盖多类记忆的工程系统：

- **L0 原始对话**：保存可追溯的原始证据。
- **L1 原子记忆**：从对话中提取独立、完整、可复用的 persona、episodic、instruction 三类记忆。
- **L2 场景记忆**：把相关原子记忆整合为连贯的场景叙事，而不是简单列表。
- **L3 Persona**：周期性生成和更新稳定的用户画像。
- **工作记忆/上下文卸载**：当上下文接近窗口上限时，用摘要和 Mermaid 状态图替换大量工具调用原文。
- **程序性记忆/Skill**：把可复用的工作方式沉淀为能力，并采用先注入目录、再按需加载全文的渐进式披露模式。

代码主要由 MemoryCore、MemoryProxy、MemoryPanel 和 MemoryKnowledge 组成。文章特别指出，接入层代码量明显大于知识引擎，说明在 Agent 生态碎片化的现实中，“如何无侵入地接进去”往往比记忆算法本身更耗费工程量。

### 三、写入侧：从原始对话到稳定画像

1. **L0 多份冗余保存**：同一条消息进入 SQLite 结构化表、`vec0` 向量表和按天分片的 JSONL。三者分别服务于结构化查询、语义检索和故障恢复。`team_id / user_id / agent_id / task_id` 四个隔离维度从底层表结构开始建立，为后续团队资产治理打基础。
2. **L0→L1 的触发机制**：默认每 5 轮对话抽取一次，或会话空闲 600 秒后兜底；warmup 让新会话按 1、2、4、5 轮递增触发，尽早产生第一条记忆。
3. **抽取原则**：Prompt 首先要求“宁缺毋滥”，并强调记忆必须脱离原对话后仍能独立理解；强关联信息需要归纳合并，纯主观且不稳定的情绪不进入长期记忆。
4. **LLM 判决式去重**：先通过向量或 FTS5 召回 Top-5 候选，再让 LLM 在 `store / skip / update / merge` 中判断。相比单一相似度阈值，这能区分旧信息更好、新信息更好以及多条信息互补等不同语义，但代价是额外调用、成本和不可复现性。
5. **L2 聚合交给 LLM 维护文件**：系统把场景目录的读写能力交给 LLM，并设置默认 15 个场景文件的硬上限。达到上限时必须先合并主题重叠、叙事弧线相近或低热度场景，用容量约束迫使系统持续归纳，而不是无限积累碎片。
6. **L3 与可靠性**：L3 默认每新增 50 条记忆触发；Persona 保留 3 个历史版本，场景块保留 10 个备份。异步流水线基于 Redis Stream，配合 Agent 维度分布式锁、指数退避、死信队列和 checkpoint 断点续跑，避免多个 LLM 同时修改同一目录，并提高记忆产出的稳定性。

### 四、召回侧：少拿但拿对

- **混合检索**：本地方案结合 SQLite FTS5/BM25 和 sqlite-vec 余弦相似度，两路并行召回后用 RRF 融合。RRF 只依赖排名，不要求 BM25 与向量分数处于同一量纲。云端则可由腾讯云 VectorDB 执行原生混合检索。
- **并非所有层都检索**：L3 Persona 和 L2 场景导航因为已经高度压缩，存在时会直接注入；持续增长的 L1 原子记忆才进行语义召回。
- **优化 Prompt Cache**：稳定的 Persona、场景导航和工具指南放在 system prompt 尾部，动态变化的 L1 记忆放在 user prompt 前部，避免每轮动态记忆击穿系统提示词缓存。
- **主动检索补充**：预算裁剪使自动注入必然不完整，因此系统给 Agent 提供 `tdai_memory_search`、`tdai_conversation_search` 和 `read_file` 等继续下钻的途径，但单轮最多搜索 3 次，防止模型在无结果时无限循环。
- **失败即降级**：召回默认 5 秒超时，超时后返回空注入；截断时明确提示 Agent 可继续主动查询。设计目标是保证记忆作为增强能力不会拖垮主流程。

### 五、上下文卸载：长期记忆之外的关键能力

文章认为，“省 61% token”的主要来源不是长期记忆，而是工作记忆的上下文卸载。系统设置三级压力阈值：

- 达到 50% 时进行温和卸载，优先替换较不重要的工具结果；
- 达到 85% 时从最老消息开始进行激进压缩，并借助 L1.5 判断任务边界；
- 达到 95% 时执行紧急压缩，目标降至窗口的 60%；
- 回填的 Mermaid 状态图最多占总 token 的 20%。

其本质是将几十条工具调用原文替换成一张表达任务状态和进度的图，同时保留按引用回查完整原文的能力，从而在减少上下文负担的同时保留可追溯性。

### 六、从个人记忆走向团队资产

v2.0 的重点不仅是算法，也包括资产治理：

- **Wiki**：先让 LLM 生成抽取计划，再生成或更新页面；已有实体优先合并，而不是不断制造新页面。
- **CodeGraph**：借助 tree-sitter 建立符号、文件和调用关系，提供 callers、callees、impact 等查询。
- **Skill**：先提供能力名录，再由 Agent 按需加载全文，以降低上下文占用；Prompt 会主动抑制模型“我已经会了所以不加载”的过度自信。
- **权限与可见性**：记忆资产具备 Owner、版本、可见性、团队成员和 ACL。`private` 的语义是只有 Owner 能访问，即使团队管理员也不能读取，体现了隐私信任优先于管理便利。
- **知识工具化**：当知识规模超出上下文窗口时，不再尝试整库注入，而是通过 `/v3/tools/list` 和 `/v3/tools/call` 暴露搜索、读取、图查询等能力，让 Agent 自主决定获取什么。

### 七、接入方式与工程代价

项目从 v0.x/v1.x 的插件模式演进为 v2.x 的协议代理模式。MemoryProxy 同时兼容 Anthropic、OpenAI 及部分客户端特化路由，用户只需修改 base URL。对 SSE 流式响应，代理使用 `TransformStream` 边透传边旁路收集 assistant 内容和工具调用，流结束后异步写入 L0，以避免增加首字延迟。

无状态代理通过多个可能的会话 Header 依次识别会话。这实现了“零侵入”，但也把不同客户端的兼容性负担集中到了代理和适配器中：如果客户端不发送已知 Header，或把系统信息、补全请求、压缩请求混在用户内容中，就必须继续扩展适配逻辑。

### 八、优势、风险与局限

**值得借鉴的设计：**

1. 让 LLM 作为记忆维护者，负责去重、合并、改写和知识库更新，而不仅是记忆消费者。
2. 通过场景数量、回填比例、搜索次数等硬上限倒逼信息密度与归纳质量。
3. 把降级作为一等设计：超时、检索后端缺失或内容被截断时，都有明确退路。
4. 把记忆从“检索语料”升级为具备 Owner、版本、权限和装配关系的团队资产。

**主要风险和不足：**

- 多层 LLM 调用带来显著 token 成本。
- 去重、场景合并和 Persona 重写都具有非确定性，同一输入可能生成不同结果。
- L3 基于上一版画像增量重写，错误判断可能被后续版本继承并持续强化，源码中尚未看到明确的漂移校正机制。
- SQLite 与本地文件适用于个人或小团队，但存在单机规模上限。
- Wiki、CodeGraph 构建是异步的；CodeGraph 对私有仓库凭证的支持有限；资产装配仍需人工操作，全自动记忆路由尚未完成。
- PersonaMem 从 48% 到 76% 等数字属于官方自测，因测试环境、模型和 Prompt 配置未充分公开，应视为特定场景结果，而不是可直接泛化的结论。

### 九、最终结论

文章归纳出五条可迁移原则：记忆的第一性原理是取舍；增强能力必须可以静默降级；硬容量上限能迫使系统做真正的归纳；LLM 应参与维护和组织记忆；一旦记忆跨用户、Agent 和团队流动，治理的重要性就会超过算法。TencentDB Agent Memory 的价值不在某个单点新算法，而在于把分层、混合检索、上下文卸载、权限、版本、资产装配和协议代理组合成一套面向真实产品的完整工程系统。

---

## 完整原文全文

# 记忆不是存下来的，是取舍出来的——拆解腾讯 TencentDB Agent Memory

核心判断：Agent 记忆的工程难点不在存储，在取舍。
写入端做减法：抽取 prompt 的第一条原则写着「宁缺毋滥」，场景文件设 15 个硬上限，撞顶就强制合并。
召回端做预算：Top-5 + 分数门槛 0.3 + 字符截断 + 5 秒超时直接放弃注入，宁可无记忆也不阻塞对话。
关键设计不靠算法靠 LLM：去重是「向量召回 Top-5 → LLM 判决」，L2 聚合是「给 LLM 开一个目录的读写权限」。
真正的分水岭是治理：Owner、版本、可见性、Agent 装配——这些是 RAG 从来不管、而团队协作一定会撞上的东西。
欢迎大家来点赞一下我的 bytetech 主页文章：https://bytetech.info/articles/7677848128308903942
先纠正一个容易混淆的名字。这个项目的全名是 TencentDB Agent Memory（GitHub 仓库 TencentCloud/TencentDB-Agent-Memory），腾讯云数据库团队 2026 年 5 月开源，MIT 协议。它和 AWS MemoryDB、Redis 那类内存数据库没有关系，是一套给 AI Agent 用的分层记忆引擎。本文分析的是 97f9465 这个 commit，对应 v2.0.x，约 18 万行 TypeScript。
网上关于它的文章大多停在 README 那一层：分层记忆、省 61% token、PersonaMem 从 48% 涨到 76%。这些说法本身没错，但它们是结论，不是机制。我把仓库拉下来逐个模块读了一遍，想回答的是另一个问题——一个能用的 Agent 记忆系统，代码里到底在做哪些决定？
读完之后我的判断是：这套系统里最值钱的部分，几乎全是「不做什么」的决定。

一、先建一个坐标系：记忆的五个层次
直接讲 L0/L1/L2/L3 容易变成术语背诵。借人类记忆的分类做一次映射，读者能少走很多弯路。

这个映射是我为了讲清楚而做的类比，不是官方的设计对应关系，但它能解释一件事：大多数「Agent 记忆」方案只做了其中一层。只存对话记录的，停在情景记忆；做 RAG 切片检索的，勉强碰到语义记忆的边；而工作记忆（上下文快满了怎么办）和程序记忆（把跑通的做法固化成能力）通常无人认领。
TencentDB Agent Memory 的野心是五层都要。这也是它代码量膨胀到 18 万行的原因：

| 模块 | 代码量 | 职责 |
| --- | --- | --- |
| MemoryCore | 约 9.6 万行 | 记忆内核：L0–L3 沉淀、混合召回、offload 压缩、Skill 抽取 |
| MemoryProxy | 约 4.2 万行 | 零侵入接入网关：拦截 LLM 协议、注入记忆、异步落库 |
| MemoryPanel | 约 3.1 万行 | Memory Hub 管控台 |
| MemoryKnowledge | 约 1.1 万行 | Wiki / CodeGraph 知识资产引擎 |

值得先记住这个比例：接入层（4.2 万行）比知识引擎（1.1 万行）大了近四倍。这个失衡本身就是一个信号，后面第六章会回到它。

二、写入侧：记忆怎么逐层长出来
对话不是直接变成记忆的。它先原样落库，然后由一条异步流水线分四段提炼。

2.1 L0：为什么要写两份
每轮对话结束后立刻落 L0，表结构很朴素：
MemoryCore/src/core/store/sqlite.ts:748
```sql
CREATE TABLE IF NOT EXISTS l0_conversations (
  record_id     TEXT PRIMARY KEY,
  session_key   TEXT NOT NULL,
  session_id    TEXT DEFAULT 'default',
  team_id       TEXT DEFAULT 'default',
  task_id       TEXT DEFAULT '',
  user_id       TEXT NOT NULL DEFAULT 'default',
  agent_id      TEXT NOT NULL DEFAULT 'default',
  role          TEXT NOT NULL DEFAULT '',
  message_text  TEXT NOT NULL,
  recorded_at   TEXT DEFAULT '',
  timestamp     INTEGER DEFAULT 0
)
```
四个隔离维度（team_id / user_id / agent_id / task_id）从最底层的表就埋好了，这是它后来能做团队级资产治理的地基。同一条消息还会写进 l0_vec 这张 vec0 虚拟表做向量检索，另外再按天分片存一份 JSONL 文件。
三份冗余看着浪费，但各有各的用处：SQLite 表负责结构化查询，向量表负责语义召回，JSONL 负责在数据库出问题时还能把原话捞回来。记忆系统一旦丢数据就是不可逆的信任损失，这里的冗余是刻意的。
2.2 L0→L1：一次 LLM 调用干两件事
抽取不是每轮都做。触发条件写在配置默认值里：
MemoryCore/src/config.ts:562-568
```typescript
pipeline: {
  everyNConversations: num(pipelineGroup, "everyNConversations") ?? 5,
  enableWarmup: bool(pipelineGroup, "enableWarmup") ?? true,
  l1IdleTimeoutSeconds: num(pipelineGroup, "l1IdleTimeoutSeconds") ?? 600,
  l2DelayAfterL1Seconds: num(pipelineGroup, "l2DelayAfterL1Seconds") ?? 10,
  l2MinIntervalSeconds: num(pipelineGroup, "l2MinIntervalSeconds") ?? 900,
  l2MaxIntervalSeconds: num(pipelineGroup, "l2MaxIntervalSeconds") ?? 3600,
  sessionActiveWindowHours: num(pipelineGroup, "sessionActiveWindowHours") ?? 24,
}
```
默认每 5 轮触发一次，或者会话空闲 600 秒后兜底触发。enableWarmup 是个容易被忽略的细节：新会话按 1 → 2 → 4 → 5 轮递增触发，让第一条记忆尽早出现。冷启动阶段用户还没建立信任，等 5 轮才产出第一条记忆，体感上就是「它根本没记住」。
📌 校正一处 README 与源码的不一致：一些解读文章把空闲兜底写成 30 秒，源码里 l1IdleTimeoutSeconds 的默认值是 600 秒。
抽取 prompt 最值得逐字看。它把「情境切分」和「记忆提取」压在同一次 LLM 调用里完成：
MemoryCore/src/core/prompts/l1-extraction.ts:15-56（节选）
```text
你是专业的"情境切分与记忆提取专家"。
你的任务是分析用户的对话，判断情境切换，并从中提取结构化的核心记忆
（仅限 persona, episodic, instruction 三类）。

### 任务一：情境切分（Scene Segmentation）
- 继承：无明显切换，沿用上一个情境。
- 切换条件：用户发出明确指令（如"换话题"）、意图转变、或提出独立新目标。
- 命名规则："我（AI）在和xxx（用户身份）做xxx（目标活动）"

### 任务二：核心记忆提取（Memory Extraction）
【通用提取原则】
1. 宁缺毋滥：过滤琐碎闲聊、临时性指令和一次性操作（如"这次、本单"）；
   剔除不可靠的边缘信息。
2. 独立完整：记忆必须"跳出当前对话依然成立"，无上下文也能看懂。
   提取主体必须以"用户（姓名）"或"AI"为核心。
3. 归纳合并：强关联或因果关系的多条消息，必须合并为一条完整记忆，
   不可碎片化。

1. 个性化记忆 (type: "persona")
   - 定义：用户的稳定属性、偏好、技能、价值观、习惯（如住所、职业、饮食禁忌）。
   - 打分 (priority)：80-100（健康/禁忌/核心特质）；50-70（一般喜好/技能）；
     &lt;50（模糊次要，可丢弃）。

2. 客观事件记忆 (type: "episodic")
   - 定义：客观发生的动作、决定、计划或达成结果。绝不包含纯主观感受。
   - 提取句式："用户（[姓名]）在 [最好是精确绝对时间] 于 [地点] [做了某事]"

3. 全局指令记忆 (type: "instruction")
   - 定义：用户对 AI 提出的长期行为规则、格式偏好、语气控制。
   - 打分 (priority)：-1（极其严格的全局死命令）；90-100（核心行为规则）
```
三个细节撑起了整套设计的品味。
「独立完整」这条约束解决了 RAG 最常见的翻车场景。切片检索经常召回一句「那就按第二个方案来」——命中了关键词，但脱离上下文毫无价值。这里强制要求记忆写成「用户（张三）在 X 时间决定采用 Y 方案」，代价是多花 LLM token，换来的是召回结果不需要再补上下文。
类型只有三种，而且刻意排除了主观感受。「不应该提取的内容」里明确列了「纯主观感受（不带客观事件的情绪表达）」。这是一个很克制的判断：情绪是易变的，把它固化成长期记忆，Agent 会拿着三个月前的一句抱怨当成用户的稳定偏好。
priority: -1 是个彩蛋。正常打分区间是 0–100，而 -1 被留给「极其严格的全局死命令」。用负数表达最高优先级，说明这个字段在排序时走的是特殊分支——留了一个逃生舱给「这条必须永远生效」的规则。
2.3 去重不靠阈值，靠判决
大多数方案的去重是算余弦相似度、卡个阈值。这里换了个思路：先用向量或 FTS5 召回 Top-5 候选，然后让 LLM 逐条判决。
MemoryCore/src/core/prompts/l1-dedup.ts:16-42（节选）
```text
你是记忆冲突检测器。批量比较多条【新记忆】与【统一候选记忆池】中的已有记忆，
逐条决定如何处理。

## 核心规则
- **跨 type 合并**：不同 type 的记忆如果语义上描述同一事实/事件，**可以合并**。
- **多对多合并**：一条新记忆可以同时替换/合并候选池中的**多条**已有记忆。

## 判断逻辑
3. **选择动作**：
   - "store"：视为新信息，新增当前记忆。
   - "skip"：已有记忆更好，新记忆无增量或更模糊，忽略当前记忆。
   - "update"：同一事实/事件，新记忆在内容或时间上更优（更具体、更晚或纠错）。
   - "merge"：同一事实或同一演化过程，多条记忆信息互补且不矛盾，
     合并成一条更完整记忆。

5. **timestamp 处理**：
   - merge / update 时，merged_timestamps 应包含**所有相关记忆的时间戳并集**
   - 这样可以保留事件发生的完整时间线
```
四种动作的语义区分很有分寸感。skip 是「旧的更好」，update 是「新的更好」，merge 是「两条都对，合起来更完整」。纯向量方案只能做到「像不像」，做不出这三种判断。
时间戳取并集这个处理尤其聪明：合并「用户 3 月开始学 Rust」和「用户 6 月用 Rust 写了个项目」时，如果只保留最新时间戳，就丢掉了这是一条持续三个月的演化线。保留并集，记忆里就带着时间跨度。
代价也很明确：每次抽取都要额外一轮 LLM 调用做判决，而 LLM 判决是不可复现的——同样两条记忆，这次判 merge，下次可能判 skip。用确定性换语义质量，这是一笔明码标价的交易。
2.4 L2 聚合：给 LLM 开一个目录的写权限
这是全项目最反直觉的设计。L1 到 L2 的「聚合」没有用任何聚类算法，而是把一个目录的读写工具交给 LLM，让它自己维护一堆 Markdown 文件。
MemoryCore/src/core/prompts/scene-extraction.ts:49-104（节选）
```text
# Memory Consolidation Architect

## 角色定义 (Role Definition)
你是记忆整合架构师。你的目标是为用户构建一个"数字第二大脑"。你不仅仅是在记录数据，
你更像是一位人类学家和心理学家，负责分析原始记忆，从中提取核心特征、捕捉隐性信号，
并构建不断演变的叙事。

### Layer 2 (Processing): Scene Diaries
- **形态**：**不是清单，是连贯的叙事文档**
- **动作**：Create（创建）、Integrate（整合）、Rewrite（重写）
- **禁止**：简单追加列表

**⚠️ 场景文件数量上限：${maxScenes} 个。处理完成后目录中的场景文件数量
必须严格小于此上限。**

### ⚠️ 阶段 0：强制检查场景总数（必须先执行）
3. **遵守分级预警**：
   - 红色预警（≥ 15）：**必须先通过 MERGE 减少文件数量**，将最相似的 2-4 个场景
     合并为 1 个，**并删除被合并的旧文件**，直到文件数 &lt; 15 后，再处理新记忆
   - 橙色预警（= 14）：**只能 UPDATE 现有场景，不能 CREATE 新场景**
   - 黄色预警（接近 15）：**优先 UPDATE 或主动 MERGE 相似场景**

**合并优先级**（当需要合并时，按以下顺序选择）：
1. **主题高度重叠**：如"Python后端开发"和"Go后端开发" → 合并为"后端开发技术栈"
2. **叙事弧线相同**：如"求职材料-JD匹配"和"职业发展-能力对齐" → 合并为"职业发展与求职"
3. **热度最低的场景**：如果没有明显重叠，合并或删除 heat 最低的 2-3 个场景
```
maxScenes 默认 15（MemoryCore/src/config.ts:556）。这个数字是整个设计里最关键的一处约束：它用容量上限反向逼出了记忆密度。文件数快撞顶时，LLM 被迫回头合并最相似的场景，于是记忆自然而然地从「一堆碎片」收敛成「十几条主线」。
把它跟无上限方案对比就能看出差别。无上限的系统里，记忆只增不减，三个月后场景列表有 200 条，召回时噪音淹没信号。这里的 15 个上限强制系统持续做归纳——用工程约束替代了「需要多智能的算法才能自动归纳」这个难题。
删除机制也很有意思：LLM 不能真的删文件，只能把内容写成 [DELETED] 标记，由工程侧清理。prompt 里还特意堵了几个口子：「禁止写入空字符串（会被系统拒绝）」「禁止用 [ARCHIVE]、[CONSOLIDATED] 等其他标记替代删除」。这些约束显然是被真实的 LLM 行为教育出来的。
2.5 L3 Persona 与异步底座
L3 的触发阈值是 50 条新记忆，这个数字确实在源码里：
MemoryCore/src/config.ts:554-560
```typescript
persona: {
  triggerEveryN: num(personaGroup, "triggerEveryN") ?? 50,
  maxScenes: num(personaGroup, "maxScenes") ?? 15,
  backupCount: num(personaGroup, "backupCount") ?? 3,
  sceneBackupCount: num(personaGroup, "sceneBackupCount") ?? 10,
  ...
}
```
backupCount 和 sceneBackupCount 透露了另一层担心：persona 保留 3 个历史版本，场景块保留 10 个。LLM 重写画像时可能写坏，得留回滚的余地。
比算法更值得产品同学看的是这条流水线的可靠性设计。它跑在 Redis Stream 的竞争消费模型上，配了按 agent 维度的分布式锁保证串行、失败指数退避、死信队列、以及 checkpoint.json 断点续跑。重试逻辑直接写在代码里：
MemoryCore/src/services/pipeline-worker.ts:527-531
```typescript
// 指数退避重试
if (retryCount &lt; this.config.maxRetries) {
  const delay = this.config.retryBaseDelayMs * Math.pow(3, retryCount); // 5s, 15s, 45s
  this.logger.warn(
    `${TAG} Task failed (retry ${retryCount + 1}/${this.config.maxRetries}, delay=${delay}ms): ${errMsg}`,
  );
```
为什么必须按 agent 加锁串行？因为 L2 阶段是 LLM 在改文件。两个任务并发跑同一个 scene_blocks/ 目录，就是两个人同时编辑同一份文档而且都不用 git。这个锁不是性能优化，是正确性前提。

给产品同学的提示：记忆功能上线后的投诉，大部分不是「记得不准」，而是「有时候记得、有时候不记得」。前者是算法问题，后者是队列、锁和断点续跑的问题。这一节的工程量看着不性感，但它决定用户是否信任这个功能。

三、召回侧：怎么做到少拿但拿对
召回的入口是 handleBeforeRecall，链路是 performAutoRecall → performAutoRecallCore → searchHybrid。整条链路的形状值得先看图。

3.1 混合检索：两套后端，一套语义
关键词路走 SQLite FTS5 的 BM25，中文先过 jieba 分词再拼成 OR 短语查询；向量路走 sqlite-vec 扩展做余弦相似度。两路并行，各取 maxResults * 3 个候选：
MemoryCore/src/core/hooks/auto-recall.ts:648-651
```typescript
// Run keyword and embedding searches in parallel
const candidateK = maxResults * 3; // retrieve more for merging

const [keywordResult, embeddingResult] = await Promise.all([
  // Keyword search: FTS5 only (no in-memory fallback)
```
融合用 RRF，实现干净得可以直接抄走：
MemoryCore/src/core/store/search-utils.ts:18-62
```typescript
/**
 * Standard RRF constant from the original RRF paper.
 * Higher k → more weight on lower-ranked items (smoother distribution).
 */
export const RRF_K = 60;

export function rrfMerge&lt;T&gt;(
  lists: T[][],
  getId: (item: T) =&gt; string,
  k: number = RRF_K,
): Array&lt;T &amp; { rrfScore: number }&gt; {
  const map = new Map&lt;string, { item: T; rrfScore: number }&gt;();

  for (const list of lists) {
    for (let rank = 0; rank &lt; list.length; rank++) {
      const item = list[rank];
      const id = getId(item);
      const score = 1 / (k + rank + 1);
      const existing = map.get(id);
      if (existing) {
        existing.rrfScore += score;
      } else {
        map.set(id, { item, rrfScore: score });
      }
    }
  }

  return [...map.values()]
    .sort((a, b) =&gt; b.rrfScore - a.rrfScore)
    .map(({ item, rrfScore }) =&gt; ({ ...item, rrfScore }));
}
```
RRF 只看排名不看原始分数，这正是它适合异构检索的原因：BM25 的分数和余弦相似度根本不在一个量纲上，加权求和需要调一个玄学权重，而按排名取倒数天然免疫量纲问题。k = 60 是原始论文的取值，k 越大，低排名条目的权重越高、分布越平滑。
换到云端时，同一套语义走的是腾讯云 VectorDB 的原生 hybridSearch，稀疏向量在客户端生成后一并发过去，由服务端完成融合。同一份召回逻辑抽象出两套后端实现，这是它敢宣称「完全本地化、零外部 API 依赖」同时又能上云的原因。
3.2 分层召回其实不分层
README 说「生成和召回都分层」，容易让人以为有个路由器在判断该查哪一层。源码里没有这个路由器：L3 画像和 L2 场景索引只要存在就全量注入，只有 L1 走语义召回。
这个选择是对的。persona 和场景索引本身就是被压缩过的高密度内容，再对它们做一次语义筛选，只会引入「该进上下文的没进来」的风险。而 L1 是原子事实，数量会持续增长，必须靠检索收敛。
3.3 注入位置：一处很精妙的账单级优化
召回结果不是一股脑塞进 system prompt。代码里的注释把动机写得很清楚：
MemoryCore/src/core/hooks/auto-recall.ts:257-281
```typescript
// Split recall context into stable and dynamic parts to optimize prompt caching.
//
// appendSystemContext (system prompt end — stable, cacheable):
//   persona, scene navigation, memory tools guide
//   These change infrequently; when content is identical across turns,
//   providers with prompt caching (Anthropic/OpenAI) can cache this region.
//
// prependContext (user prompt prefix — dynamic, per-turn):
//   L1 relevant memories — different every turn, moved out of system prompt
//   so it doesn't bust the system prompt cache.
const stableParts: string[] = [];
if (personaContent) {
  stableParts.push(`&lt;user-persona&gt;\n${personaContent}\n&lt;/user-persona&gt;`);
}
if (sceneNavigation) {
  stableParts.push(`&lt;scene-navigation&gt;\n${sceneNavigation}\n&lt;/scene-navigation&gt;`);
}

// Dynamic part: L1 relevant memories (changes every turn) → prependContext (user prompt)
let prependContext: string | undefined;
if (memoryLines.length &gt; 0) {
  prependContext =
    `&lt;relevant-memories&gt;\n以下是当前对话召回的相关记忆，不代表当前任务进程，仅作为参考：\n\n${memoryLines.join(RECALL_LINE_SEPARATOR)}\n&lt;/relevant-memories&gt;`;
}
```
稳定内容（画像、场景导航、工具指南）放 system prompt 尾部，每轮变化的 L1 记忆放 user message 头部。如果把 L1 记忆也塞进 system prompt，每轮 prompt 内容都不同，prompt cache 每轮击穿一次——同样的效果，账单可能差几倍。
注入文案里那句「不代表当前任务进程，仅作为参考」也是被坑出来的。不加这句，模型容易把召回的历史记忆当成当前任务的已完成步骤，然后接着往下做。
3.4 从被动注入升级到主动检索
预算裁剪之后，注入的记忆一定是不完整的。系统的应对是附一份工具指南，让 Agent 自己接着查：
MemoryCore/src/core/hooks/auto-recall.ts:41-57
```text
&lt;memory-tools-guide&gt;
## 记忆工具调用指南

当上方注入的记忆片段不足以回答用户问题时，可主动调用以下工具获取更多信息：

- **tdai_memory_search**：搜索结构化记忆（L1），适用于回忆用户偏好、历史事件节点、规则等关键信息。
- **tdai_conversation_search**：搜索原始对话（L0），适用于查找具体消息原文、时间线、上下文细节。
- **read_file**（Scene Navigation 中的路径）：当已定位到相关情境，且需要该场景的完整画像、
  事件经过或阶段结论时使用。

### ⚠️ 调用次数限制
每轮对话中，tdai_memory_search 和 tdai_conversation_search **合计最多调用 3 次**。
- 首次搜索无结果时，可换关键词或换工具重试，但总调用次数不要超过 3 次。
- 若 3 次搜索后仍无结果，说明该信息不在记忆中，请直接根据已有信息回复用户，不要继续搜索。
&lt;/memory-tools-guide&gt;
```
「合计最多 3 次」这条限制是从事故里长出来的：不设上限，Agent 会在找不到答案时反复换关键词搜索，把一轮对话拖成十几次工具调用。这句 prompt 的本质是给 Agent 装了个熔断器。
3.5 降级优先于正确
召回整体包在一个 Promise.race 里，超时就返回空注入：
MemoryCore/src/core/hooks/auto-recall.ts:107-131
```typescript
const timeoutMs = cfg.recall.timeoutMs ?? 5000;

return Promise.race([
  performAutoRecallInner(params).finally(() =&gt; {
    if (timer) clearTimeout(timer);
  }),
  new Promise&lt;RecallResult&gt;((resolve) =&gt; {
    timer = setTimeout(() =&gt; {
      logger?.warn?.(
        `${TAG} ⚠️ Recall timed out after ${timeoutMs}ms — surfacing as RecallResult.error`,
      );
      resolve({
        prependContext: "",
        appendSystemContext: "",
        recalledL1Memories: [],
        recalledL3Persona: null,
        error: RecallErrors.dependencyTimeout("recall").recallError,
        partial: false,
      });
    }, timeoutMs);
  }),
]);
```
这是我认为整个项目里最值得学的一行判断：宁可让 Agent 在无记忆状态下回答，也不让用户多等一秒。记忆是增强功能，不是必需功能，它不该有能力拖垮主流程。
字符预算的截断处理也带着同样的克制。截断后缀写着「…（已截断；可用 tdai_memory_search 或 tdai_conversation_search 查看详情）」，把「我这里还有更多」这个信号明确传给模型，而不是悄悄切掉。

四、被大多数文章漏掉的第四种记忆
讲 Agent 记忆的文章几乎都在讲长期记忆。但「上下文快满了」这个问题每天都在发生，而且它才是「省 61% token」的真正来源。

三级阈值的默认值写在同一处：
MemoryCore/src/offload_server/types.ts:139-141
```typescript
    mildOffloadRatio: 0.5,
    aggressiveCompressRatio: 0.85,
    emergencyCompressRatio: 0.95,
```
配置注释把每一档的动作说得很细：
MemoryCore/src/offload/types.ts:168-186（节选）
```typescript
/** Mild offload: replace non-current-task tool results when context &gt;= this ratio. Default: 0.5 */
mildOffloadRatio?: number;
/** Mild offload scan range: scan the last N% of messages (0.7 = last 70%). Default: 0.7 */
mildOffloadScanRatio?: number;
/** Mild offload phase-1: replace top N% highest-score (most replaceable) entries first. Default: 0.4 */
mildScoreTopRatio?: number;
/** Aggressive compress: delete tail messages when context &gt;= this ratio. Default: 0.85 */
aggressiveCompressRatio?: number;
/**
 * Aggressive compress: target fraction of **message** tokens to remove from the **oldest**
 * messages each round (0.4 ≈ oldest 40% of total per-message token sum). Default: 0.4
 */
aggressiveDeleteRatio?: number;
/** Emergency trigger: when tokens &gt;= contextWindow * emergencyCompressRatio, fire emergency. Default: 0.95 */
emergencyCompressRatio?: number;
/** Emergency target: delete until tokens &lt;= contextWindow * emergencyTargetRatio. Default: 0.6 */
emergencyTargetRatio?: number;
/** Max ratio of total tokens that injected MMDs may occupy. Default: 0.2 */
mmdMaxTokenRatio?: number;
```
Mild 档的两个参数体现了「先动最不重要的」这个直觉：只扫最近 70% 的消息，并且优先替换分数最高（即最可替换）的前 40%。分数机制的存在说明系统对「哪条工具结果可以扔」是有排序的，不是先进先出。
Aggressive 档才是真正的手术。它从最老的消息开始物理删除，每轮削掉约 40% 的消息 token，同时靠一个 L1.5 阶段判定任务边界，保证不会把一个任务切成两半。被删掉的整段，用一张 L2 Mermaid 状态图回填。
一句话概括这个机制：删掉 50 条工具调用原文，换成 1 张状态图。这就是长任务里 token 消耗下降的来源——不是压缩算法有多神，而是承认「50 条 toolResult 原文对当前决策的价值，抵不上一张说明「我们走到哪一步了」的图」。
mmdMaxTokenRatio: 0.2 这个参数是配套的刹车：回填的图最多只能占 20% token。否则压缩会退化成「用另一种方式塞满上下文」。

五、从个人记忆到团队资产
v2.0 真正的野心不在算法，在治理。四类记忆资产被统一登记，经过权限判定后装配给不同 Agent。

5.1 Wiki：让 LLM 当维护者，不只当消费者
Wiki 的构建受 Karpathy 的「LLM Wiki」启发，落地方式是两阶段：先让 LLM 产出结构化抽取计划，再据此生成页面。分析阶段的 prompt 定位很明确：
MemoryKnowledge/src/engines/wiki/ingest-v2/prompts.ts:44-60（节选）
```text
You are a knowledge base analyst. Your job is to read a source document and plan how to
integrate it into the existing wiki. You do NOT write final pages — you only produce a
structured "extraction plan" for the next (generation) stage.

## Your Analysis Output (markdown, structured, concise)
1. **Source Summary**: Summarize this source in 2–4 sentences.
2. **Entities**: Concrete entities (people, products, systems, organizations, etc.)
3. **Concepts**: Abstract concepts (theories, methods, mechanisms, etc.)
4. **Relationship to Existing Pages**: Which entities/concepts already appear in the
   existing page list (update/merge rather than create new), and which are brand new.
5. **Suggested Cross-References**: Which entity/concept pairs should be connected via [[wikilink]].
```
把「抽什么」和「怎么落盘」拆成两次调用，源码注释给的理由是「质量更稳、格式更规整」。这是 LLM 工程里一条很实用的经验：一次调用同时承担判断和格式约束，两边都会打折。
LLM 写不了文件，于是有了一套边界标记协议：
MemoryKnowledge/src/engines/wiki/ingest-v2/prompts.ts:128-145（节选）
```text
## Output Protocol (FILE blocks, MUST be followed strictly)
You cannot write files directly. Wrap each page to be written in the following boundary markers:

&lt;&lt;&lt;FILE path="wiki/&lt;dir&gt;/&lt;slug&gt;.md"&gt;&gt;&gt;
---
type: ...
title: ...
---

body...
&lt;&lt;&lt;END&gt;&gt;&gt;

Directory conventions (use plural directory names):
- source → wiki/sources/
- entity → wiki/entities/
- concept → wiki/concepts/
```
注意第 4 项分析要求：「哪些实体已经在已有页面里（更新/合并而不是新建）」。这决定了 Wiki 是增量演进的知识库，而不是每次 ingest 都堆一批新页面的垃圾场。跟 L2 场景块的 MERGE 逻辑是同一个思路：让 LLM 承担归并责任，而不是把归并留给检索时的读者。
5.2 CodeGraph 与 Skill
CodeGraph 复用了 colbymchenry/codegraph，底层用 tree-sitter 解析语法树，索引符号、文件和调用边，支持 callers / callees / impact 查询。影响分析的遍历深度默认 2、上限 10——这个上限本质上是上下文预算的另一种表达：图遍历三层以上，返回的节点数就会超出模型能有效处理的范围。
Skill 的装配方式比它的数据结构更值得看。它没有把所有 Skill 全文注入，而是先给一份名录，让 Agent 自己决定要不要拉全文：
MemoryProxy/src/injection/injectors/skill-injector.ts:61-77
```typescript
const SKILL_LISTING_HEADER =
  "## Skills (mandatory)\n"
  + "Before replying, scan the skills below. If a skill matches or is even partially relevant "
  + "to your task, you MUST load it by calling the `skill_view` skill-bridge tool "
  + "(see the `&lt;skill_tools&gt;` block above for the exact curl recipe) and follow its instructions. "
  + "Err on the side of loading — it is always better to have context you don't need "
  + "than to miss critical steps, pitfalls, or established workflows. "
  ...
  + "Skills also encode the user's preferred approach, conventions, and quality standards "
  + "for tasks like code review, planning, and testing — load them even for tasks you "
  + "already know how to do, because the skill defines how it should be done here.\n";
```
「宁可多加载也不要漏」这句措辞值得玩味：它承认了渐进式披露的真实失效模式——Agent 看到简短描述后觉得「这个我会」，于是不加载 Skill，结果错过了团队沉淀的关键步骤。这句 prompt 是在跟模型的过度自信对抗。
5.3 权限判定：private 连管理员也拒绝
治理才是「记忆资产」和「RAG 语料」的分界线。判定逻辑是一个纯函数，顺序经过刻意优化：
MemoryCore/src/metadata/service/permission-checker.ts:5-11
```text
 * 设计要点：
 *   - 判定顺序优化为「资源 → owner → 成员 → visibility → 角色默认 → ACL → deny」，
 *     高频场景（admin 读写 / member 只读）在角色默认即放行，无需查 ACL 表。
 *   - role 默认权限是代码级硬编码常量，无需为 role 预先配置数据。
 *   - 一期 allow-only 模型。
```
把高频场景放在 ACL 查询之前，是很常规但很有效的性能设计。真正体现产品判断的是 private 的语义：
MemoryCore/src/metadata/service/permission-checker.ts:68-84（节选）
```typescript
case "private":
  // 私密语义（2026-07 变更）：严格私密，只有 owner_user_id 能访问。
  // 团队 admin 也不放行 —— 因为第 2 步 owner 判定已优先返回 ALLOW，
  // 走到这里说明当前 user 不是 owner，即使是 admin 也一律拒绝。
  //
  // 语义解释：
  //   - private = 个人隐私资产，团队里没人能看到（包括管理员）
  //   - team    = 共享给整个团队（team 成员可读，owner/admin 可写）
  //   - restricted = 严格 ACL 白名单（走下面 case）
  //
  // 影响面：
  //   - list-accessible 不返回其他人的 private asset（对 admin 也生效）
  //   - 若管理员确实需要看，让 owner 主动切到 team 或通过 acl/grant 授权
  logger.debug(`[META] perm_check DENY: visibility=private, role=${membership.role}`);
  return { allowed: false, reason: "visibility_restricted" };
```
注释里那句「2026-07 变更」说明这是改过的——早期版本大概是允许 admin 看的。改成严格私有的理由不难猜：Chat Memory 里存的是用户的偏好、习惯和私下吐槽，如果团队管理员能看，没人敢开这个功能。这是一条产品决策，不是技术决策。
5.4 知识不整库注入，而是变成工具
Wiki 和 CodeGraph 的对外接口是 /v3/tools/list 和 /v3/tools/call——Agent 先发现能力，再按需调用。Wiki 侧暴露 search / read_page / get_graph 等工具，CodeGraph 侧暴露 search / explore / callers / impact / files 等。
这个取舍指向一个更普适的结论：当知识规模超过上下文窗口时，「检索并注入」这个范式就该让位给「暴露工具让模型自己找」。前者是系统替模型决定看什么，后者是模型自己决定。规模越大，后者的优势越明显。

六、接入机制的演进：从改代码到改一行配置

v0.x/v1.x 走的是插件路线，MemoryCore/openclaw-plugin 和 hermes-plugin 是遗迹。插件要 Hook Agent 框架的生命周期，意味着每个框架单独适配一次，闭源客户端根本接不进来。
v2.x 换成 Proxy 拦截。它同时挂了 Anthropic 的 /v1/messages、OpenAI 的 /v1/chat/completions，还有 /codex/*/responses 这类客户端特化路由。用户只需要把 base URL 指向 MemoryProxy:8096。
难点在流式响应。要在 SSE 流过时把 assistant 回复和 tool_calls 解析出来落库，又不能增加首字延迟。做法是插一个 TransformStream 在中间「抽吸」：
MemoryProxy/src/handler.ts:1783-1803（节选）
```typescript
function createUsageTapTransform(ctx: TapContext): TransformStream&lt;Uint8Array, Uint8Array&gt; {
  const decoder = new TextDecoder();
  let sseBuf = "";
  let lastUsage: Record&lt;string, unknown&gt; | null = null;
  let assistantContent = "";
  const toolCallAccumulators = new Map&lt;number, ToolCallAccumulator&gt;();

  function processSseChunk(chunk: string): void {
    sseBuf += chunk;
    const parts = sseBuf.split("\n\n");
    sseBuf = parts.pop() ?? "";
    for (const part of parts) {
      const usage = extractSseUsage(part);
      if (usage) lastUsage = usage;
      const { content, toolCallDeltas } = extractSseContentAndTools(part);
      assistantContent += content;
      mergeToolCallDeltas(toolCallAccumulators, toolCallDeltas);
    }
  }
```
数据原样透传给客户端，同时在旁路累积内容，流结束后异步写 L0。sseBuf 那三行是关键：SSE 的事件边界是 \n\n，网络分片不保证对齐边界，所以最后一段不完整的必须留在缓冲区等下一个 chunk。
无状态代理怎么认会话？靠 header 逐个试：
MemoryProxy/src/session/session-key.ts:8-19
```typescript
/** Extract conversation ID from request headers. Returns null if no valid ID found. */
export function resolveConversationId(c: Context): string | null {
  const id =
    c.req.header("x-conversation-id") ??
    c.req.header("x-session-id") ??
    c.req.header("x-claude-code-session-id") ?? // Claude Code CLI sends this
    c.req.header("x-deepseek-harness-session-id") ?? // dsh (deepseek-harness) CLI/web sends this
    c.req.header("x-chat-id") ??
    c.req.header("x-thread-id") ??
    null;
  return id &amp;&amp; id.length &gt; 0 ? id : null;
}
```
这段代码很朴素，但它是「零侵入」的全部秘密，也是它的全部脆弱之处：换一个不发这些 header 的客户端，会话识别就失效了。所谓零代码接入，代价是把兼容性负担从用户转移到了这个 ?? 链条上。项目里 agent-adapters 目录的存在就是这个负担的具体化——比如 Claude Code 会往 user content 数组里塞大量 &lt;system-reminder&gt;，适配器得挑出最后一个真正的文本块；补全建议、compaction 这类辅助请求还得识别出来不触发记忆写回。
回到第一章那个比例：接入层 4.2 万行，知识引擎 1.1 万行。在 Agent 框架高度碎片化的今天，「怎么接进去」的工程量可能比「记忆算法本身」大得多。这是一个容易被低估的现实。

七、它做对了什么，还欠什么
7.1 三个我会直接借走的判断
让 LLM 当维护者。去重靠 LLM 判决而不是相似度阈值，L2 聚合靠 LLM 改文件而不是聚类算法，Wiki 更新靠 LLM 合并而不是覆盖写入。这套思路承认了一件事：归纳和取舍本身就是智能任务，用算法近似它，不如直接把工具交给模型。
用容量约束逼出质量。场景文件 15 个硬上限、回填图最多占 20% token、记忆搜索每轮最多 3 次。这些数字都不是最优解，但有上限比没上限重要——上限会强迫系统持续做归纳。
降级优先于正确。5 秒超时就放弃注入，FTS5 不可用就跳过关键词那一路，截断时留一句「可以继续查」。记忆是增强功能，它的失败必须是静默的。
7.2 代价与风险
这套设计的账单不便宜。抽取一轮、判决一轮、L2 聚合一轮、L3 重写一轮，每一层都是 LLM 调用。它靠异步流水线把延迟藏起来了，但 token 成本是实打实的。
更值得警惕的是不可复现性。LLM 判决去重、LLM 决定合并哪些场景、LLM 重写画像，这三处都没有确定性保证。同一批输入跑两次，得到的记忆结构可能不同。backupCount: 3 和 sceneBackupCount: 10 这两个备份参数，说明团队自己也清楚这个风险。
还有一个长期问题：画像漂移与错误记忆的自我强化。L3 每 50 条记忆重写一次，每次基于上一版增量更新。如果某一版写进了一个错误判断，后续版本会继承它，而且随着「它一直这么写」而显得越来越可信。目前我在源码里没看到针对这种漂移的校正机制。
规模上，SQLite + 本地文件的组合对个人和小团队够用，但 l0_conversations 表和 vec0 虚拟表在单机上有明确天花板。这也是为什么会有腾讯云 VectorDB 那条路径——不完全是商业化考虑，也是架构必然。
7.3 官方承认的局限
README 的「注意事项」写得比多数开源项目诚实：Wiki 和 CodeGraph 异步构建需要等待；CodeGraph 目前只支持公开 HTTPS 仓库（git-fetcher 还没接企业级 SSH 凭证或 OAuth 令牌注入）；Hub 目前是人工绑定资产，全自动记忆路由仍在迭代。
最后一条是整个产品叙事里最大的缺口。「按身份自动装配记忆」是它最吸引人的图景，而现在这一步还需要人在面板上手动点。第五章那张图里的「装配」环节，实际上是人的判断，不是系统的判断。
7.4 Benchmark 要打折看
README 给的数字是 PersonaMem 从 48% 提升到 76%（相对提升 59%）。这是官方自测，测试环境、模型版本、prompt 配置都没有公开到可复现的程度。分层记忆能改善长期交互中的用户信息理解，这个方向我认可；但具体数字建议当作「官方在自己的场景里测到的效果」，不要当成通用结论引用。
7.5 放在同类方案里看
mem0、Zep（Graphiti）、Letta（MemGPT）、LangMem 都在做 Agent 记忆，但重心不同。mem0 和 Zep 的核心竞争力在记忆算法和图结构，Letta 在探索 Agent 自主管理自己的记忆。TencentDB Agent Memory 在算法层面并没有独创的东西——分层、混合检索、RRF、LLM 判决去重，这些都是已知手法的组合。
它真正押注的地方是治理和接入：把记忆做成有 Owner、有版本、有可见性、能装配给具体 Agent 的资产，再用一个协议层把接入成本压到改一行配置。这两件事技术上不炫，但恰好是从「个人玩具」走到「团队工具」必须跨过的门槛。

结语：五条可迁移的结论
拆完这个仓库，我留下的不是「腾讯又开源了什么」，而是五条能用在别的产品上的判断。
记忆的第一性原理是取舍。「宁缺毋滥」写在 prompt 第一条，15 个场景上限写在配置里，Top-5 写在召回参数里。做记忆功能时，先想清楚要扔掉什么，再想存什么。
降级路径比主路径更值得设计。5 秒超时就放弃注入。任何增强型功能都该有一条「失败时静默退场」的路，否则它迟早会变成主流程的故障源。
给容量设硬上限，反而能逼出质量。没有上限的系统只会单向膨胀。上限会强迫它做归纳，而归纳才是记忆的价值所在。
让 LLM 当维护者，而不只是消费者。需要判断和归纳的环节，把工具权限交给模型，比自己写一套近似算法更省力也更准。
记忆一旦要在团队里流动，治理的重要性会超过算法。Owner、版本、可见性、装配关系——这些字段决定的是「敢不敢用」，而算法决定的只是「好不好用」。

写给做 AI 产品的同行：这个项目最好的地方，是它把「记忆」从一个技术概念还原成了一串具体的产品决策——private 要不要对管理员开放、超时了要不要还等、场景上限设几个、召回给几条。这些决策没有标准答案，但每一个都直接决定用户是否愿意把自己的偏好和历史交给它。
项目地址：TencentCloud/TencentDB-Agent-Memory。本文所有源码引用基于 commit 97f9465（v2.0.x），行号可能随版本变化。

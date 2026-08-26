# P10 实现进度

> 需求类型：使用过程中发现的缺陷对应的修复需求

## 已完成

- [x] P10-1 查询语句基础规范化
- [x] P10-2 静态中英文学术术语映射
- [x] P10-3 OOV 中文术语检测
- [x] P10-4 结构化 LLM 术语翻译兜底
- [x] P10-5 `pending` 动态术语缓存
- [x] LLM 翻译失败时保留原查询继续检索
- [x] 术语条目 JSON 原子持久化
- [x] 搜索结果按标题和摘要进行基础相关性重排
- [x] P10-6 术语冲突按领域、状态和置信度选择
- [x] P10-7 保留原查询并生成最多 3 路查询
- [x] P10-8 按 arXiv ID/URL 去重
- [x] P10-9 输出基础重排元数据和分数
- [x] P10-10 返回查询变体、OOV 术语和去重统计
- [x] P10-11 限制 OOV 数量、扩展查询数量和候选翻译数量
- [x] P10-12 提供 Recall@K、MRR、nDCG@K 基础评测函数

## 本阶段新增组件

```text
common/models/terminology.py
common/persistence/terminology_store.py
common/capabilities/terminology.py
```

`PaperSearchAdapter` 支持注入 `TerminologyService`。CLI 在启用 LLM 时自动启用该服务；无 LLM 的测试和离线调用保持兼容。

## 后续增强

- [ ] 接入人工审核 API，将 `pending` 升级为 `verified`
- [ ] 增加基于真实标注集的离线检索评测
- [ ] 增加术语使用频率和跨会话统计事件
- [ ] 使用领域 Embedding 做二阶段语义重排

## 当前验证

```text
P10 focused tests: 27 passed
全量测试：388 passed, 3 warnings
```

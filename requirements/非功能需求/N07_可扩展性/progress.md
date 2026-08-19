# N07 可扩展性 - 进展

## 当前状态：插件化架构完成，扩展新工具/新阶段非常方便

## 已完成
- [x] Tool Registry 插件式工具注册
  - register_tool() 动态注册
  - list_tools()/get_tool() 工具发现
  - 自动注入工具描述到Research Agent prompt
- [x] BaseTool 抽象基类（统一接口：name/description/execute）
- [x] 工具目录模块化：retrieval/filesystem/code/paper_processing/sandbox
- [x] register_all_tools() 自动发现注册
- [x] 7阶段可配置（config/default.yaml中stages配置）
- [x] Hook机制（phase_hooks/verdict_hooks/plan_validation_hooks）
- [x] LLM Provider可扩展（factory模式，支持新增OpenAI兼容API）
- [x] 阶段prompt模板化（文件系统加载，无需改代码）

## 扩展新工具步骤
1. 在tools/<category>/下新建工具文件
2. 继承BaseTool，实现name/description/execute()
3. 在tools/__init__.py register_all_tools()中添加注册
4. 无需修改Agent/Orchestrator代码，工具自动可用

## 扩展新阶段步骤
1. 在prompts/research_agent/phases/添加prompt模板
2. 在config/default.yaml添加阶段配置
3. 在TaskPhase枚举添加新阶段
4. 在Evaluation Agent添加对应检查清单
5. 在PHASE_TRANSITIONS添加转换规则

## 验证情况
- ✅ 新增arxiv_search/save_artifact等工具无需修改核心框架
- ✅ 所有工具描述自动注入prompt，LLM可发现并使用
- ✅ LLM provider从DeepSeek V3升级到V4-Flash/V4-Pro只需改config

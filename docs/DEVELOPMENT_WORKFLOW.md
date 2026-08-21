# Paper Research Agent 开发流程

本文档是本项目的标准研发流程，适用于新功能、行为变更和缺陷修复。

核心链路：

```text
需求澄清
  -> grill-me
规格与计划
  -> SuperSpec / OpenSpec
实现
  -> ss-coding-workflow
检查
  -> OpenSpec CLI + 测试 + ss-code-review
交付
  -> GitHub PR
归档
  -> ss-archive
```

文档目录总览见 [`docs/README.md`](./README.md)。新增需求相关文档统一遵循：

- 需求方案、进度、卡点和解决记录：`requirements/<需求目录>/`；
- 技术提案：`docs/proposals/`；
- 执行计划：`docs/plans/`；
- 跨需求长期设计决策：`docs/decisions/`；
- 普通历史文档：`docs/archive/`；
- OpenSpec baseline、active change 和 change archive：继续保留在 `openspec/`。

不要为了整理目录移动工作流规定的固定路径；文档失效时优先增加索引或状态说明，
需要归档时按本文件第 9 节执行。

## 1. 工具职责

| 工具 | 负责内容 | 不负责内容 |
|---|---|---|
| `grill-me` | 追问需求、边界、失败路径和验收标准 | 写代码、改文件、运行测试 |
| SuperSpec | proposal、delta spec、执行计划、TDD 实现、代码审查 | 替代业务决策 |
| OpenSpec CLI | 规格结构校验、关系检查、健康检查 | 代码正确性和业务验收 |
| `ss-code-review` | 审查代码、测试和规格覆盖 | 代替测试执行 |
| `ss-archive` | 将已完成 delta 合并到 baseline 并归档 | 合并 GitHub PR |

本项目使用 `.trae/skills/` 下的 SuperSpec Skill。OpenSpec CLI 当前使用官方包：

```bash
npm install -g @fission-ai/openspec@latest
openspec --version
```

不要安装同名的 `openspec` 占位包，也不要重复执行 `openspec init`。项目已经有
完整的 `openspec/` 结构。

## 2. 开始任务前

进入项目并确认主分支干净：

```bash
cd /Users/bytedance/workspace/paper_research_agent
git switch main
git pull --ff-only origin main
git status --short --branch
```

预期：

```text
## main...origin/main
```

如果工作树存在与当前任务无关的修改，先停止，不要 stash、reset 或覆盖用户改动。

创建任务分支：

```bash
git switch -c feat/<change-name>
```

分支命名建议：

```text
feat/<feature-name>       新功能
fix/<bug-name>            缺陷修复
refactor/<module-name>    内部重构
docs/<topic>              文档变更
```

禁止直接在 `main` 上实现业务代码。

## 3. grill-me 需求澄清

当需求存在任何歧义时，先在 TRAE 中执行：

```text
使用 grill-me 追问这个需求。
重点确认：
1. 需求所属模块、需求 ID 和优先级；
2. 使用者、触发阶段和入口；
3. 输入、输出、核心数据流和落盘位置；
4. 非法输入、依赖失败、状态冲突和资源超限；
5. Research Agent 和 Evaluation Agent 是否参与；
6. PASS、REVISE、BLOCKED 的判定条件；
7. 可执行的验收命令、回滚方式和影响范围。
不要修改文件。
```

需求至少要回答：

- 要解决什么问题？
- 哪些行为必须新增或改变？
- 哪些行为明确不在范围内？
- 正向和负向场景分别是什么？
- 哪些文件可能受影响？
- 如何证明实现完成？

如果需求已经足够明确，可以跳过 grill-me，但必须在后续 proposal 中明确记录
scope 和 acceptance。

## 4. 创建 proposal、delta spec 和计划

将 grill-me 的结果交给 SuperSpec：

```text
使用 ss-feature-workflow，根据上面的需求澄清结果：
1. 阅读 AGENTS.md、WORKFLOW.md、requirements/ 和相关 openspec/specs/；
2. 复用已有 capability，不重复创建；
3. 创建 proposal、delta spec 和执行计划；
4. 每个 Requirement 至少包含一个 #### Scenario；
5. 必须包含非法输入和依赖失败等负向场景；
6. 先不要修改业务代码。
```

通常会产生：

```text
openspec/changes/<change-id>/
├── proposal.md
└── specs/
    └── <capability>/
        └── spec.md

docs/plans/YYYY-MM-DD-<change-name>.md
```

delta spec 只描述可观察行为，不写实现细节。

修改已有能力时使用：

```markdown
## MODIFIED Requirements

### Requirement: <完整 Requirement>
The system SHALL ...

#### Scenario: <场景>
- **WHEN** ...
- **THEN** ...
```

增加新能力时使用 `## ADDED Requirements`。删除和重命名必须分别提供
`Reason`、`Migration` 或 `FROM/TO`。

生成后先检查：

```bash
openspec validate --all --strict
openspec doctor
openspec list --changes
openspec list --specs
```

如果 `openspec validate` 失败，先修规格，不要开始写代码。

## 5. 规格来源和兼容规则

当前项目有两套规格资料：

```text
requirements/       现有项目需求、历史方案和进度记录
openspec/specs/     当前系统行为的 living baseline
openspec/changes/   进行中的 delta spec
```

在明确完成迁移前，`requirements/` 仍是项目流程要求的权威资料。

涉及已有需求模块时，必须同步对应目录的：

```text
solution.md
progress.md
blockers.md
resolutions.md
```

不要把尚未实现的规划内容写进 baseline。baseline 应反映代码和测试已经证明的
当前行为。

## 6. 执行实现

计划文件准备好后，在当前功能分支执行：

```text
Use ss-coding-workflow in lite mode on
docs/plans/YYYY-MM-DD-<change-name>.md
```

执行顺序必须是：

```text
读代码和规格
  -> 写失败测试
  -> 确认测试失败
  -> 最小实现
  -> 运行测试
  -> 更新计划复选框
```

每个实现任务必须：

- 只修改计划中声明的文件；
- 先写负向测试，再写生产代码；
- 不丢弃上游错误；
- 不增加未被需求要求的抽象；
- 修改后立即运行最小验证；
- 不把 TODO、stub 或“后续实现”作为完成结果。

推荐的 Python 检查命令：

```bash
PYTHONPATH=src python3 -m pytest -q <affected-tests>
PYTHONPATH=src python3 -c "import paper_agent; print('paper_agent import: OK')"
git diff --check
```

如果 `ruff` 已安装，再运行：

```bash
ruff check <changed-files>
```

## 7. 代码审查和验收

实现完成后运行：

```text
Use ss-code-review to review the current branch against the active delta spec.
```

审查必须确认：

- 需求中的每个 Scenario 都有测试；
- 正向和负向路径都覆盖；
- 改动没有超出计划文件范围；
- 没有破坏旧行为；
- 错误信息、状态转换和持久化行为符合项目规则；
- `requirements/` 与 `openspec/` 文档已同步。

再运行完整的相关回归：

```bash
PYTHONPATH=src python3 -m pytest -q
openspec validate --all --strict
openspec doctor
git diff --check
```

当前环境如果没有 `.trae/skills/ss-verify/SKILL.md`，则按照 `WORKFLOW.md` 手工
逐条验收，并在报告中明确说明。

## 8. 提交和 PR

确认测试通过、审查通过、工作树只包含当前任务文件后：

```bash
git status --short
git add <changed-files>
git commit -m "type(scope): describe the change"
git push -u origin <branch-name>
```

提交信息格式示例：

```text
feat(paper-processing): add pdf validation
fix(paper-retrieval): validate max results
docs(spec): update paper retrieval baseline
```

创建 GitHub PR 时确认：

- base 是 `main`；
- head 是当前功能分支；
- PR 描述包含需求、范围、测试命令和已知警告；
- PR 没有混入其他任务；
- CI 和 required checks 已通过。

## 9. PR 合并后归档

PR 合并后同步主分支：

```bash
git switch main
git pull --ff-only origin main
git status --short --branch
```

确认没有 active change 冲突后，在 TRAE 中执行：

```text
使用 ss-archive 归档 <change-id>。
```

归档动作必须：

1. 将 delta 合并到 `openspec/specs/<capability>/spec.md`；
2. 更新 source-of-truth header；
3. 将 change 移动到：

```text
openspec/changes/archive/YYYY-MM-DD-<change-id>/
```

4. 创建归档提交；
5. 推送 `main`。

归档后检查：

```bash
openspec validate --all --strict
openspec list --changes
openspec list --specs
git status --short --branch
```

`openspec/changes/` 不应再出现已完成的 active change。

当前项目优先使用自定义 `ss-archive`，不要随意混用 CLI 的
`openspec archive`，避免 source-of-truth header、归档目录和项目规则不一致。

## 10. 失败处理

### 规格不清楚

停止实现，回到 `grill-me`，补充 proposal、Scenario 和验收标准。

### 计划路径错误

停止执行，修正 plan 中的真实文件路径，不要绕过计划直接改其他文件。

### 测试失败

记录完整错误、失败命令和复现条件。最多进行有限次针对性修复，不要通过删除
测试或放宽断言来“修绿”。

### 持久化失败

核心 state、manifest 写入失败必须终止主流程并报错。辅助错误现场 dump 只能在
项目规则允许时降级为 warning。

### GitHub PR 无法合并

先检查：

```bash
git fetch origin
git log --oneline --decorate --all -8
```

确认是否存在冲突、required checks、review 要求或权限问题。不要使用 force push
或绕过分支保护。

## 11. 新需求模板

在 TRAE 中可以直接使用下面的模板：

```text
使用 grill-me 澄清以下需求，不要改文件：

需求：
<描述需求>

重点确认输入输出、边界条件、失败路径、负向测试、影响文件和验收标准。
```

澄清完成后：

```text
使用 ss-feature-workflow，根据刚才的澄清结果生成 proposal、delta spec 和执行计划。
复用已有 capability，先不要写业务代码。
```

计划审阅后：

```text
Use ss-coding-workflow in lite mode on
docs/plans/<plan-file>.md
```

最后：

```text
Use ss-code-review to review the current branch against the active delta spec.
```

PR 合并后：

```text
使用 ss-archive 归档 <change-id>，并报告归档路径、变更数量、提交 SHA 和验证结果。
```

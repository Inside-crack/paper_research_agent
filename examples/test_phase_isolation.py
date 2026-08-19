"""
测试 A01 阶段间上下文隔离
正向：三阶段上下文隔离结构正确
反向：
  1. REVISE时history不清空
  2. 重复start_new_phase抛异常
  3. 空summaries（第一阶段）正常工作
  4. 未调start_new_phase就generate_plan抛异常
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from paper_agent.common.config import get_settings
from paper_agent.common.logging import setup_logging
from paper_agent.common.models.base import TaskPhase, EvaluationVerdict, Budget
from paper_agent.common.models.research_spec import ResearchSpec
from paper_agent.common.models.task_state import TaskState
from paper_agent.orchestrator import Orchestrator
from paper_agent.tools import get_default_registry


def check(condition: bool, description: str) -> bool:
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status}: {description}")
    return condition


async def test_negative_3_empty_summaries_first_phase():
    """反例3：第一阶段空summaries正常工作"""
    print("\n[反例3] 第一阶段空summaries不报错")
    settings = get_settings()
    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    user_query = "test query"
    research_spec = ResearchSpec(
        user_query=user_query,
        budget=Budget(max_tokens=10000, max_gpu_minutes=10, max_wall_time_minutes=5),
    )

    task_workspace = settings.workspace_dir / research_spec.id
    task_artifacts = settings.artifact_dir / research_spec.id
    task_workspace.mkdir(parents=True, exist_ok=True)
    task_artifacts.mkdir(parents=True, exist_ok=True)

    task_state = TaskState(
        research_spec_id=research_spec.id,
        workspace_dir=str(task_workspace),
        artifact_dir=str(task_artifacts),
    )
    task_state.metadata["user_query"] = user_query
    task_state.metadata["research_spec"] = research_spec.model_dump(mode="json")
    await orchestrator._ensure_stages_initialized(task_state)
    await orchestrator.evaluation.initialize(task_state)

    assert len(task_state.phase_summaries) == 0, "phase_summaries should be empty for first phase"

    stage_status = task_state.stages[TaskPhase.TASK_INITIALIZATION]
    stage_status.started_at = datetime.utcnow()

    eval_result = await orchestrator._execute_phase_flow(TaskPhase.TASK_INITIALIZATION, task_state)

    history = orchestrator.research.message_history
    has_system = any(m.role.value == "system" for m in history)
    has_spec = any("研究任务规格" in m.content or "Research Spec" in m.content for m in history if hasattr(m, 'content'))
    no_summaries_section = not any("已完成阶段进度" in m.content for m in history if hasattr(m, 'content'))

    ok = True
    ok &= check(eval_result is not None, "task_initialization executed without error")
    ok &= check(has_system, "System prompt present in history")
    ok &= check(no_summaries_section, "No '已完成阶段进度' section when summaries is empty")
    return ok


async def test_negative_2_duplicate_start_new_phase():
    """反例2：重复调用start_new_phase抛异常"""
    print("\n[反例2] 同阶段重复start_new_phase抛RuntimeError")
    settings = get_settings()
    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    research_spec = ResearchSpec(
        user_query="test",
        budget=Budget(max_tokens=10000, max_gpu_minutes=10, max_wall_time_minutes=5),
    )
    task_workspace = settings.workspace_dir / research_spec.id
    task_artifacts = settings.artifact_dir / research_spec.id
    task_workspace.mkdir(parents=True, exist_ok=True)
    task_artifacts.mkdir(parents=True, exist_ok=True)

    task_state = TaskState(
        research_spec_id=research_spec.id,
        workspace_dir=str(task_workspace),
        artifact_dir=str(task_artifacts),
    )
    task_state.metadata["user_query"] = "test"
    task_state.metadata["research_spec"] = research_spec.model_dump(mode="json")
    await orchestrator._ensure_stages_initialized(task_state)

    await orchestrator.research.start_new_phase(TaskPhase.TASK_INITIALIZATION, task_state, [])

    raised = False
    try:
        await orchestrator.research.start_new_phase(TaskPhase.TASK_INITIALIZATION, task_state, [])
    except RuntimeError as e:
        raised = True
        print(f"  ℹ️  Caught expected error: {str(e)[:80]}...")

    ok = check(raised, "Second start_new_phase for same phase raises RuntimeError")
    return ok


async def test_negative_4_generate_plan_without_init():
    """反例4：未调start_new_phase就generate_plan抛异常"""
    print("\n[反例4] generate_plan未初始化抛RuntimeError")
    settings = get_settings()
    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    research_spec = ResearchSpec(
        user_query="test",
        budget=Budget(max_tokens=10000, max_gpu_minutes=10, max_wall_time_minutes=5),
    )
    task_workspace = settings.workspace_dir / research_spec.id
    task_artifacts = settings.artifact_dir / research_spec.id
    task_workspace.mkdir(parents=True, exist_ok=True)
    task_artifacts.mkdir(parents=True, exist_ok=True)

    task_state = TaskState(
        research_spec_id=research_spec.id,
        workspace_dir=str(task_workspace),
        artifact_dir=str(task_artifacts),
    )
    task_state.metadata["user_query"] = "test"
    task_state.metadata["research_spec"] = research_spec.model_dump(mode="json")
    await orchestrator._ensure_stages_initialized(task_state)

    raised = False
    try:
        await orchestrator.research.generate_plan(TaskPhase.TASK_INITIALIZATION, task_state)
    except RuntimeError as e:
        raised = True
        print(f"  ℹ️  Caught expected error: {str(e)[:80]}...")

    ok = check(raised, "generate_plan without start_new_phase raises RuntimeError")
    return ok


async def test_summary_card_generation():
    """测试摘要卡确定性生成"""
    print("\n[单元测试] _build_phase_summary_card 确定性生成")
    settings = get_settings()
    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    from paper_agent.common.models.evaluation_result import EvaluationResult

    class MockEvalResult:
        def __init__(self, verdict_val, score, issues=None):
            self.verdict = EvaluationVerdict(verdict_val)
            self.score = score
            self.issues = issues or []

    ok = True

    init_output = {
        "research_spec": {"task_type": "topic_research", "domain": "LLM Multi-Agent", "keywords": ["a", "b", "c"]},
    }
    card = orchestrator._build_phase_summary_card(
        TaskPhase.TASK_INITIALIZATION, init_output, MockEvalResult("PASS", 0.95)
    )
    ok &= check(card["phase"] == "task_initialization", "phase name correct")
    ok &= check(card["verdict"] == "PASS", "verdict correct")
    ok &= check(card["score"] == 0.95, "score correct")
    ok &= check("research_spec" in card["artifact_ids"], "artifact_ids includes research_spec")
    ok &= check("keywords" in card["key_info"], "key_info includes keywords")
    ok &= check(len(card["conclusion"]) <= 100, "conclusion <= 100 chars")
    print(f"  ℹ️  init card conclusion: {card['conclusion']}")

    retrieval_output = {
        "candidates": [{"arxiv_id": "2401.00001"}, {"arxiv_id": "2401.00002"}, {"arxiv_id": "2401.00003"}, {"arxiv_id": "2401.00004"}],
        "candidate_set_id": "paper_candidates_abc",
    }
    from paper_agent.common.models.evaluation_result import EvaluationIssue, SeverityLevel
    issues = [EvaluationIssue(
        issue_type="quality", severity=SeverityLevel.HIGH,
        description="missing URL metadata for all papers",
    )]
    card2 = orchestrator._build_phase_summary_card(
        TaskPhase.PAPER_RETRIEVAL, retrieval_output, MockEvalResult("PASS", 0.80, issues)
    )
    ok &= check(card2["phase"] == "paper_retrieval", "phase name correct")
    ok &= check("paper_candidates_abc" in card2["artifact_ids"], "candidate_set_id in artifacts")
    ok &= check("top3" in card2["key_info"], "top3 in key_info")
    ok &= check(len(card2["key_info"]["top3"]) == 3, "top3 has 3 ids")
    ok &= check("待改进项" in card2["notes"], "notes mentions issues")
    print(f"  ℹ️  retrieval card conclusion: {card2['conclusion']}")
    print(f"  ℹ️  retrieval card key_info: {card2['key_info']}")

    return ok


async def test_format_summary_card():
    """测试摘要卡文本格式化"""
    print("\n[单元测试] _format_summary_card 文本格式化 + 200字硬限制")
    settings = get_settings()
    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    card = {
        "phase": "paper_retrieval",
        "verdict": "PASS",
        "score": 0.82,
        "conclusion": "检索去重后保留10篇候选论文",
        "artifact_ids": ["paper_candidates"],
        "key_info": {"top3": ["2401.07324", "2412.05449", "2406.12544"]},
        "notes": "",
    }
    text = orchestrator.research._format_summary_card(card)
    print(f"  Formatted card:\n{text}")
    ok = True
    ok &= check(len(text) <= 200, f"card length {len(text)} <= 200 chars")
    ok &= check("paper_retrieval" in text, "contains phase name")
    ok &= check("0.82" in text, "contains score")
    ok &= check("paper_candidates" in text, "contains artifact")
    ok &= check("2401.07324" in text, "contains key_info")

    long_card = {
        "phase": "test_phase",
        "verdict": "PASS",
        "score": 1.0,
        "conclusion": "x" * 300,
        "artifact_ids": ["a", "b", "c"],
        "key_info": {},
        "notes": "",
    }
    long_text = orchestrator.research._format_summary_card(long_card)
    ok &= check(len(long_text) <= 200, f"long card truncated to {len(long_text)} <= 200 chars")
    ok &= check(long_text.endswith("..."), "truncated card ends with ...")

    return ok


async def test_failure_recording():
    """测试失败信息记录"""
    print("\n[单元测试] _record_phase_failure 失败信息存入metadata")
    settings = get_settings()
    registry = get_default_registry()
    orchestrator = Orchestrator(tool_registry=registry)

    from paper_agent.common.models.evaluation_result import EvaluationResult, EvaluationIssue, SeverityLevel

    research_spec = ResearchSpec(
        user_query="test",
        budget=Budget(max_tokens=10000, max_gpu_minutes=10, max_wall_time_minutes=5),
    )
    task_workspace = settings.workspace_dir / research_spec.id
    task_artifacts = settings.artifact_dir / research_spec.id
    task_workspace.mkdir(parents=True, exist_ok=True)
    task_artifacts.mkdir(parents=True, exist_ok=True)

    task_state = TaskState(
        research_spec_id=research_spec.id,
        workspace_dir=str(task_workspace),
        artifact_dir=str(task_artifacts),
    )
    task_state.metadata["user_query"] = "test"
    task_state.metadata["research_spec"] = research_spec.model_dump(mode="json")
    await orchestrator._ensure_stages_initialized(task_state)

    issues = [
        EvaluationIssue(
            issue_type="quality", severity=SeverityLevel.HIGH,
            description="missing URL metadata for all papers",
        ),
        EvaluationIssue(
            issue_type="quality", severity=SeverityLevel.MEDIUM,
            description="code availability not verified",
        ),
    ]
    eval_result = EvaluationResult(
        task_state_id=task_state.id, phase=TaskPhase.PAPER_RETRIEVAL,
        verdict=EvaluationVerdict.REVISE, score=0.6, issues=issues,
    )

    orchestrator._record_phase_failure(task_state, TaskPhase.PAPER_RETRIEVAL, eval_result, {})

    failures = task_state.metadata.get("phase_failures", {})
    ok = True
    ok &= check("paper_retrieval" in failures, "failure recorded for paper_retrieval")
    ok &= check(len(failures["paper_retrieval"]) == 1, "one failure record")
    ok &= check(failures["paper_retrieval"][0]["score"] == 0.6, "score recorded")
    ok &= check(len(failures["paper_retrieval"][0]["issues"]) == 2, "issues recorded")
    ok &= check("timestamp" in failures["paper_retrieval"][0], "timestamp present")
    print(f"  ℹ️  failures metadata keys: {list(failures.keys())}")

    return ok


async def main():
    setup_logging()

    print("=" * 70)
    print("A01 阶段间上下文隔离 - 测试套件")
    print("=" * 70)

    results = []

    results.append(("反例4: generate_plan无初始化抛异常", await test_negative_4_generate_plan_without_init()))
    results.append(("反例2: 重复start_new_phase抛异常", await test_negative_2_duplicate_start_new_phase()))
    results.append(("单元测试: 摘要卡格式化", await test_format_summary_card()))
    results.append(("单元测试: 摘要卡确定性生成", await test_summary_card_generation()))
    results.append(("单元测试: 失败信息记录", await test_failure_recording()))

    print("\n" + "=" * 70)
    print("反例3需要真实LLM调用，正在运行（可能需要30-60秒）...")
    print("=" * 70)
    results.append(("反例3: 第一阶段空summaries正常执行", await test_negative_3_empty_summaries_first_phase()))

    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)

    all_pass = True
    for name, ok in results:
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status}: {name}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("🎉 所有测试通过！")
    else:
        print("⚠️  部分测试失败，需要修复")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

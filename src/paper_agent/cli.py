from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .common.config import get_settings
from .common.capabilities import (
    CapabilityCatalog,
    CapabilityRegistry,
    LLMIntentDecisionRouter,
    LLMIntentRouterProvider,
    register_default_capabilities,
)
from .common.conversation_service import ConversationService
from .common.llm import create_llm
from .common.logging import setup_logging
from .common.persistence import ConversationStore, StatePersistence
from .orchestrator import Orchestrator
from .tools import get_default_registry


def _json_out(data, exit_code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    sys.exit(exit_code)


def _error(error_code: str, message: str, task_id: str | None = None, exit_code: int = 1, **extra):
    err = {"error": error_code, "message": message}
    if task_id:
        err["task_id"] = task_id
    err.update(extra)
    _json_out(err, exit_code=exit_code)


async def cmd_run(args) -> None:
    setup_logging()
    orchestrator = Orchestrator()
    task_state = await orchestrator.start_task(
        user_query=args.query or "",
        target_paper_url=args.paper,
        resume_from_checkpoint=args.resume,
    )
    _json_out({
        "task_id": task_state.id,
        "status": task_state.current_phase.value,
        "artifacts_dir": task_state.artifact_dir,
        "final_report": task_state.final_report_id,
    })


async def cmd_tasks_list(args) -> None:
    sp = StatePersistence()
    tasks = sp.list_tasks()
    _json_out({"tasks": tasks, "total": len(tasks)})


async def cmd_task_show(args) -> None:
    sp = StatePersistence()
    task_dir = sp.base_dir / args.task_id
    if not task_dir.exists():
        _error("task_not_found", f"Task directory not found: {args.task_id}", task_id=args.task_id)
    m = sp.load_manifest(args.task_id)
    if m is None:
        _error("manifest_corrupted", f"Failed to load manifest for task {args.task_id}", task_id=args.task_id)
    _json_out(json.loads(m.model_dump_json(exclude_none=False)))


async def cmd_task_errors(args) -> None:
    sp = StatePersistence()
    task_dir = sp.base_dir / args.task_id
    if not task_dir.exists():
        _error("task_not_found", f"Task directory not found: {args.task_id}", task_id=args.task_id)
    m = sp.load_manifest(args.task_id)
    if m is None:
        _error("manifest_corrupted", f"Failed to load manifest for task {args.task_id}", task_id=args.task_id)
    all_errors = []
    for phase_name, pe in m.phases.items():
        for err in pe.errors:
            err_with_phase = {"phase": phase_name, **err}
            all_errors.append(err_with_phase)
    _json_out({"task_id": args.task_id, "errors": all_errors, "total": len(all_errors)})


async def cmd_task_artifacts(args) -> None:
    sp = StatePersistence()
    task_dir = sp.base_dir / args.task_id
    if not task_dir.exists():
        _error("task_not_found", f"Task directory not found: {args.task_id}", task_id=args.task_id)
    m = sp.load_manifest(args.task_id)
    if m is None:
        _error("manifest_corrupted", f"Failed to load manifest for task {args.task_id}", task_id=args.task_id)
    files_out = []
    for fe in m.files:
        fpath = task_dir / fe.name
        files_out.append({
            "name": fe.name,
            "type": fe.type,
            "phase": fe.phase,
            "step_id": fe.step_id,
            "size_bytes": fe.size_bytes,
            "exists": fpath.exists(),
        })
    _json_out({"task_id": args.task_id, "files": files_out, "total": len(files_out)})


async def cmd_task_resume(args) -> None:
    setup_logging()
    sp = StatePersistence()
    checkpoint = sp.get_latest_checkpoint(args.task_id)
    if checkpoint is None:
        _error("no_checkpoint_found", f"No checkpoint found for task {args.task_id}", task_id=args.task_id)
    orchestrator = Orchestrator()
    task_state = await orchestrator.start_task(
        user_query="",
        resume_from_checkpoint=str(checkpoint),
    )
    _json_out({
        "task_id": task_state.id,
        "status": "resumed",
        "checkpoint": str(checkpoint),
        "final_phase": task_state.current_phase.value,
    })


async def cmd_chat(args) -> None:
    setup_logging()
    settings = get_settings()
    store = ConversationStore(settings.artifact_dir)
    if args.session_id:
        session = store.load_session(args.session_id)
        if session is None:
            _error("session_not_found", f"Conversation session not found: {args.session_id}")
    else:
        session = store.create_session()

    capability_registry = CapabilityRegistry()
    register_default_capabilities(capability_registry, get_default_registry())
    llm_router = LLMIntentDecisionRouter(
        LLMIntentRouterProvider(create_llm()),
        CapabilityCatalog.from_registry(capability_registry),
    )
    service = ConversationService(
        store,
        capability_registry,
        llm_router=llm_router,
    )

    print(json.dumps({
        "session_id": session.session_id,
        "status": "active",
        "message": "Chat started. Type /exit to quit.",
    }, ensure_ascii=False))

    while True:
        try:
            content = await asyncio.to_thread(input, "> ")
        except EOFError:
            break
        if content.strip().lower() in {"/exit", "/quit", "exit", "quit"}:
            break
        if not content.strip():
            continue
        response = await service.handle_message(session.session_id, content)
        print(json.dumps(response, ensure_ascii=False, default=str))


def main():
    parser = argparse.ArgumentParser(description="论文研究与实验复现 Agent")
    parser.add_argument("--paper", "-p", help="目标论文URL或arXiv ID")
    parser.add_argument("--resume", "-r", help="从checkpoint恢复")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    p_run = subparsers.add_parser("run", help="运行研究任务")
    p_run.add_argument("query", nargs="?", help="研究主题、论文标题或复现目标")
    p_run.set_defaults(func=cmd_run)

    p_chat = subparsers.add_parser("chat", help="启动最小论文检索聊天")
    p_chat.add_argument("--session-id", help="复用已有会话")
    p_chat.set_defaults(func=cmd_chat)

    p_tasks = subparsers.add_parser("tasks", help="任务管理")
    tasks_sub = p_tasks.add_subparsers(dest="tasks_cmd")
    p_tasks_list = tasks_sub.add_parser("list", help="列出所有任务")
    p_tasks_list.set_defaults(func=cmd_tasks_list)

    p_task = subparsers.add_parser("task", help="单个任务操作")
    task_sub = p_task.add_subparsers(dest="task_cmd")

    p_task_show = task_sub.add_parser("show", help="展示任务manifest")
    p_task_show.add_argument("task_id", help="任务ID")
    p_task_show.set_defaults(func=cmd_task_show)

    p_task_errors = task_sub.add_parser("errors", help="列出任务错误")
    p_task_errors.add_argument("task_id", help="任务ID")
    p_task_errors.set_defaults(func=cmd_task_errors)

    p_task_artifacts = task_sub.add_parser("artifacts", help="列出任务artifact文件")
    p_task_artifacts.add_argument("task_id", help="任务ID")
    p_task_artifacts.set_defaults(func=cmd_task_artifacts)

    p_task_resume = task_sub.add_parser("resume", help="从checkpoint恢复任务")
    p_task_resume.add_argument("task_id", help="任务ID")
    p_task_resume.set_defaults(func=cmd_task_resume)

    args = parser.parse_args()

    if args.command is None:
        if args.query or args.resume:
            asyncio.run(cmd_run(args))
        else:
            parser.print_help()
            sys.exit(1)
        return

    if not hasattr(args, "func"):
        if args.command == "tasks" and not args.tasks_cmd:
            p_tasks.print_help()
        elif args.command == "task" and not args.task_cmd:
            p_task.print_help()
        else:
            parser.print_help()
        sys.exit(1)

    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()

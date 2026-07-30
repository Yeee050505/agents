import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END

from app.agents.planner import PlannerAgent
from app.agents.retriever import RetrieverAgent
from app.agents.tool_agent import ToolAgent
from app.agents.validator import ValidatorAgent
from app.agents.summarizer import SummarizerAgent
from app.memory import short_memory, long_memory
from app.quality import quality_tracker, whitelist, cross_validator, fact_extractor
from app.harness import save_checkpoint, load_checkpoint, delete_checkpoint, compress_context, should_compress
from app.utils.logger import logger


class GameState(TypedDict):
    question: str
    session_id: str
    request_id: str
    sub_queries: list
    retrieved: list
    tool_results: list
    context_ctx: str
    draft: str
    feedback: str
    attempt: int
    validation_ok: bool
    validation_issues: list
    events: Annotated[list, operator.add]
    human_review: bool
    _paused: bool


MAX_RETRY = 1
MAX_NODE_RETRY = 2

planner = PlannerAgent()
retriever = RetrieverAgent()
tool_agent = ToolAgent()
validator = ValidatorAgent()
summarizer = SummarizerAgent()

# Human review signal store
_resume_events: dict[str, asyncio.Future[dict]] = {}


def signal_resume(request_id: str, action: str, feedback: str = ""):
    future = _resume_events.get(request_id)
    if future and not future.done():
        future.set_result({"action": action, "feedback": feedback})
        return True
    return False


def _ev(agent: str, status: str, content: str, detail: dict | None = None) -> dict:
    return {"event": "step", "agent": agent, "status": status, "content": content, "detail": detail or {}}


async def node_planner(state: GameState) -> dict:
    for attempt in range(MAX_NODE_RETRY):
        try:
            plan = await planner.run(state["question"])
            sq = plan.get("sub_queries", [state["question"]])
            logger.info(f"[Graph] Planner: {sq}", extra={"request_id": state.get("request_id", "")})
            return {
                "sub_queries": sq,
                "events": [_ev("planner", "done", f"拆解为 {len(sq)} 个子查询",
                               {"sub_queries": sq, "reasoning": plan.get("reasoning", "")})],
            }
        except Exception as e:
            logger.warning(f"[Graph] planner 异常 (第{attempt+1}/{MAX_NODE_RETRY}): {e}")
            if attempt < MAX_NODE_RETRY - 1:
                await asyncio.sleep(1)
    return {"sub_queries": [state["question"]], "events": [_ev("planner", "error", f"重试{MAX_NODE_RETRY}次均失败")]}


async def node_retriever(state: GameState) -> dict:
    for attempt in range(MAX_NODE_RETRY):
        try:
            result = await retriever.run(state["sub_queries"])
            lst = result.get("retrieved", [])
            logger.info(f"[Graph] Retriever: {len(lst)} hits", extra={"request_id": state.get("request_id", "")})
            return {
                "retrieved": lst,
                "events": [
                    _ev("retriever", "running", "正在检索知识库..."),
                    _ev("retriever", "done", f"知识库命中 {len(lst)} 条结果", {"count": len(lst)}),
                ],
            }
        except Exception as e:
            logger.warning(f"[Graph] retriever 异常 (第{attempt+1}/{MAX_NODE_RETRY}): {e}")
            if attempt < MAX_NODE_RETRY - 1:
                await asyncio.sleep(1)
    return {"retrieved": [], "events": [_ev("retriever", "error", f"重试{MAX_NODE_RETRY}次均失败")]}


async def node_tool(state: GameState) -> dict:
    for attempt in range(MAX_NODE_RETRY):
        try:
            result = await tool_agent.run(state["sub_queries"])
            lst = result.get("tool_results", [])
            logger.info(f"[Graph] ToolAgent: {len(lst)} results", extra={"request_id": state.get("request_id", "")})
            return {
                "tool_results": lst,
                "events": [
                    _ev("tool", "running", "正在查询 TapTap API..."),
                    _ev("tool", "done", f"工具获取 {len(lst)} 条数据", {"count": len(lst)}),
                ],
            }
        except Exception as e:
            logger.warning(f"[Graph] tool 异常 (第{attempt+1}/{MAX_NODE_RETRY}): {e}")
            if attempt < MAX_NODE_RETRY - 1:
                await asyncio.sleep(1)
    return {"tool_results": [], "events": [_ev("tool", "error", f"重试{MAX_NODE_RETRY}次均失败")]}


async def node_summarizer(state: GameState) -> dict:
    for attempt in range(MAX_NODE_RETRY):
        try:
            cur = state.get("attempt", 0)
            feedback = state.get("feedback", "")
            label = f"第 {cur+1} 次重写" if cur > 0 else "正在整合素材撰写回答"
            draft = await summarizer.run(
                state["question"],
                state.get("retrieved", []),
                state.get("tool_results", []),
                context=state.get("context_ctx", ""),
                feedback=feedback,
            )
            logger.info(f"[Graph] Summarizer: {len(draft)} chars (attempt {cur+1})",
                        extra={"request_id": state.get("request_id", "")})
            return {
                "draft": draft,
                "attempt": cur + 1,
                "events": [
                    _ev("summarizer", "running", label),
                    _ev("summarizer", "done", f"草稿完成 ({len(draft)} 字)"),
                ],
            }
        except Exception as e:
            logger.warning(f"[Graph] summarizer 异常 (第{attempt+1}/{MAX_NODE_RETRY}): {e}")
            if attempt < MAX_NODE_RETRY - 1:
                await asyncio.sleep(1)
    return {"draft": "生成失败，请稍后重试", "attempt": state.get("attempt", 0) + 1,
            "events": [_ev("summarizer", "error", f"重试{MAX_NODE_RETRY}次均失败")]}


async def node_validator(state: GameState) -> dict:
    for attempt in range(MAX_NODE_RETRY):
        try:
            result = await validator.run(
                state["question"],
                state.get("retrieved", []),
                state.get("tool_results", []),
                state.get("draft", ""),
            )
            ok = result.get("passed", True)
            issues = result.get("issues", [])
            logger.info(f"[Graph] Validator: {'passed' if ok else f'failed ({len(issues)} issues)'}",
                        extra={"request_id": state.get("request_id", "")})
            feedback = "\n".join(issues) if not ok else ""
            ev = _ev("validator", "done", "审核通过，无幻觉") if ok else \
                 _ev("validator", "failed", f"发现 {len(issues)} 个问题", result)
            return {"validation_ok": ok, "validation_issues": issues, "feedback": feedback, "events": [ev]}
        except Exception as e:
            logger.warning(f"[Graph] validator 异常 (第{attempt+1}/{MAX_NODE_RETRY}): {e}")
            if attempt < MAX_NODE_RETRY - 1:
                await asyncio.sleep(1)
    return {"validation_ok": True, "validation_issues": [], "feedback": "",
            "events": [_ev("validator", "error", f"重试{MAX_NODE_RETRY}次均失败")]}


def route_validator(state: GameState) -> str:
    if state.get("validation_ok", True):
        return "end"
    if state.get("attempt", 0) <= MAX_RETRY:
        return "rewrite"
    return "end"


graph = StateGraph(GameState)
graph.add_node("planner", node_planner)
graph.add_node("retriever", node_retriever)
graph.add_node("tool", node_tool)
graph.add_node("summarizer", node_summarizer)
graph.add_node("validator", node_validator)
graph.set_entry_point("planner")
graph.add_edge("planner", "retriever")
graph.add_edge("planner", "tool")
graph.add_edge("retriever", "summarizer")
graph.add_edge("tool", "summarizer")
graph.add_edge("summarizer", "validator")
graph.add_conditional_edges("validator", route_validator, {"rewrite": "summarizer", "end": END})

compiled = graph.compile()


async def run(question: str, session_id: str = "", request_id: str = "") -> str:
    last = ""
    async for event in run_stream(question, session_id, request_id):
        if event["event"] == "done":
            last = event["content"]
    return last


def _default_state(question: str, session_id: str, request_id: str, human_review: bool) -> dict:
    return {
        "question": question, "session_id": session_id, "request_id": request_id,
        "sub_queries": [], "retrieved": [], "tool_results": [], "context_ctx": "",
        "draft": "", "feedback": "", "attempt": 0, "validation_ok": True, "validation_issues": [],
        "events": [], "human_review": human_review, "_paused": False,
    }


async def run_stream(question: str, session_id: str = "", request_id: str = "", human_review: bool = False):
    quality_tracker.begin(question, "game", request_id=request_id)

    # Check whitelist first — if exact match, return directly
    wl_match = whitelist.match(question)
    if wl_match:
        logger.info(f"Whitelist hit: {wl_match.question[:40]}")
        for chunk in _chunk(wl_match.answer):
            yield {"event": "token", "content": chunk}
        yield {"event": "done", "content": wl_match.answer}
        _finish({"draft": wl_match.answer, "attempt": 0}, question, session_id, wl_match.answer)
        return

    # Try to resume from checkpoint
    restored = load_checkpoint(session_id) if session_id else None
    if restored and restored.get("question") == question:
        logger.info(f"Resumed from checkpoint: session={session_id}")
        history = short_memory.get_history(session_id)
        memories = long_memory.retrieve(question)
        context_ctx = restored.get("context_ctx", "")
        # Re-compress if needed
        if should_compress(context_ctx):
            context_ctx = await compress_context(context_ctx, history[-4:] if history else [])
        restored["context_ctx"] = context_ctx
        initial = GameState(**{k: restored.get(k, v) for k, v in _default_state(question, session_id, request_id, human_review).items()})
    else:
        if restored:
            logger.info(f"Question mismatch, starting fresh: got '{question}', expected '{restored.get('question')}'")
            delete_checkpoint(session_id)
        history = short_memory.get_history(session_id)
        memories = long_memory.retrieve(question)
        context_ctx = _build_context(history, memories)
        if should_compress(context_ctx):
            context_ctx = await compress_context(context_ctx, history[-4:] if history else [])
        initial = GameState(
            question=question, session_id=session_id, request_id=request_id,
            sub_queries=[], retrieved=[], tool_results=[], context_ctx=context_ctx,
            draft="", feedback="", attempt=0, validation_ok=True, validation_issues=[],
            events=[], human_review=human_review, _paused=False,
        )

    if memories:
        yield {"event": "step", "agent": "memory", "status": "done",
               "content": f"长记忆命中 {len(memories)} 条",
               "detail": {"short_turns": len(history) // 2, "long_memories": memories}}

    try:
        if human_review:
            async for final in _run_with_review(initial):
                yield final
                if final.get("event") == "_final":
                    final_state = final.get("_state", {})
                    break
        else:
            # Save pre-execution checkpoint for crash recovery
            save_checkpoint(initial)
            final_state = await compiled.ainvoke(initial)
            answer = final_state.get("draft", "")
            seen = set()
            for ev in final_state.get("events", []):
                key = (ev["agent"], ev["status"], ev["content"][:30])
                if key not in seen:
                    seen.add(key)
                    yield ev
            _finish(final_state, question, session_id, answer)
            delete_checkpoint(session_id)
            for chunk in _chunk(answer):
                yield {"event": "token", "content": chunk}
            yield {"event": "done", "content": answer}

    except Exception as e:
        logger.error(f"[Graph] 异常: {e}", extra={"request_id": request_id})
        quality_tracker.finish("", 0)
        yield {"event": "error", "content": f"处理失败: {e}"}
        yield {"event": "done", "content": f"处理失败: {e}"}


async def _run_with_review(initial: GameState):
    """Step-by-step execution with human review at key nodes."""
    request_id = initial["request_id"]
    session_id = initial.get("session_id", "")
    phase = 0
    save_checkpoint({**initial, "_phase": 0})
    pause_nodes = ["planner", "retriever_tool", "summarizer", "validator"]
    final_state = None

    async for step in compiled.astream(initial, stream_mode="updates"):
        for node_name, node_output in step.items():
            if node_name == "__end__":
                continue

            # Forward events
            for ev in node_output.get("events", []):
                yield ev

            # Prepare pause data
            pause_data = {k: v for k, v in node_output.items() if k != "events"}

            # --- Determine pause point ---
            if node_name == "planner":
                yield {"event": "pause", "agent": "planner",
                       "title": "规划完成",
                       "data": {"sub_queries": node_output.get("sub_queries", [])}}
                if final_state:
                    save_checkpoint({**final_state, **node_output, "_phase": 1})
                result = await _wait_resume(request_id)
                if result.get("action") == "modify":
                    node_output["sub_queries"] = [result.get("feedback", node_output.get("sub_queries", [""])[0])]

            elif node_name in ("retriever", "tool"):
                # Wait for BOTH parallel nodes before pausing
                pass  # pause will happen when tool fires (second parallel node)

            elif node_name == "tool":
                yield {"event": "pause", "agent": "retriever_tool",
                       "title": "检索完成",
                       "data": {
                           "retrieved": initial.get("retrieved", []) + node_output.get("retrieved", []),
                           "tool_results": node_output.get("tool_results", []),
                       }}
                if final_state:
                    save_checkpoint({**final_state, **node_output, "_phase": 2})
                await _wait_resume(request_id)

            elif node_name == "summarizer":
                yield {"event": "pause", "agent": "summarizer",
                       "title": "草稿完成",
                       "data": {"draft": node_output.get("draft", "")[:500]}}
                if final_state:
                    save_checkpoint({**final_state, **node_output, "_phase": 3})
                result = await _wait_resume(request_id)
                if result.get("action") == "modify":
                    node_output["feedback"] = result.get("feedback", "")
                    # Force rewrite by setting validation_ok=False
                    node_output["validation_ok"] = False
                    node_output["validation_issues"] = [result["feedback"]]

            elif node_name == "validator":
                ok = node_output.get("validation_ok", True)
                issues = node_output.get("validation_issues", [])
                if not ok:
                    yield {"event": "pause", "agent": "validator",
                           "title": "校验发现异常",
                           "data": {"issues": issues, "draft": node_output.get("draft", initial.get("draft", ""))[:500]}}
                    result = await _wait_resume(request_id)
                    if result.get("action") == "override":
                        node_output["validation_ok"] = True
                        node_output["feedback"] = ""
                    elif result.get("action") == "modify":
                        node_output["feedback"] = result.get("feedback", "")
                        # Let the rewrite loop handle it

            # Accumulate state manually
            if final_state is None:
                final_state = dict(initial)
            final_state.update(node_output)

    # After stream ends, final_state has all accumulated data
    if final_state and "draft" in final_state:
        answer = final_state.get("draft", "")
        _finish(final_state, initial["question"], initial["session_id"], answer)
        delete_checkpoint(session_id)
        for chunk in _chunk(answer):
            yield {"event": "token", "content": chunk}
        yield {"event": "done", "content": answer}

    yield {"event": "_final", "_state": final_state or initial}


async def _wait_resume(request_id: str) -> dict:
    future = _resume_events.setdefault(request_id, asyncio.Future())
    try:
        return await asyncio.wait_for(future, timeout=600)
    except asyncio.TimeoutError:
        return {"action": "continue", "feedback": ""}


def _finish(final_state: dict, question: str, session_id: str, answer: str):
    short_memory.add_turn(session_id, question, answer)
    if session_id:
        asyncio.create_task(long_memory.process_turn(session_id, question, answer))
    quality_tracker.finish(answer, final_state.get("attempt", 1))


def _chunk(text: str, size: int = 8):
    return [text[i:i+size] for i in range(0, len(text), size)]


def _build_context(history: list, memories: list) -> str:
    parts = []
    if memories:
        parts.append("[用户长期记忆]\n" + "\n".join(memories))
    if history:
        recent = history[-6:]
        lines = [f"{'用户' if m['role']=='user' else '助手'}: {m['content'][:200]}" for m in recent]
        parts.append("[对话历史]\n" + "\n".join(lines))
    return "\n\n".join(parts)

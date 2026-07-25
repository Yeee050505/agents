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
from app.quality import quality_tracker
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


MAX_RETRY = 1
MAX_NODE_RETRY = 2

planner = PlannerAgent()
retriever = RetrieverAgent()
tool_agent = ToolAgent()
validator = ValidatorAgent()
summarizer = SummarizerAgent()


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
                    _ev("tool", "running", "正在查询 Steam API..."),
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


async def run_stream(question: str, session_id: str = "", request_id: str = ""):
    quality_tracker.begin(question, "game", request_id=request_id)
    history = short_memory.get_history(session_id)
    memories = long_memory.retrieve(question)
    context_ctx = _build_context(history, memories)

    initial = GameState(
        question=question, session_id=session_id, request_id=request_id,
        sub_queries=[], retrieved=[], tool_results=[], context_ctx=context_ctx,
        draft="", feedback="", attempt=0, validation_ok=True, validation_issues=[], events=[],
    )

    if memories:
        yield {"event": "step", "agent": "memory", "status": "done",
               "content": f"长记忆命中 {len(memories)} 条",
               "detail": {"short_turns": len(history) // 2, "long_memories": memories}}

    try:
        final = await compiled.ainvoke(initial)
        answer = final.get("draft", "")
        seen = set()

        for ev in final.get("events", []):
            key = (ev["agent"], ev["status"], ev["content"][:30])
            if key not in seen:
                seen.add(key)
                yield ev

        short_memory.add_turn(session_id, question, answer)
        if session_id:
            asyncio.create_task(long_memory.process_turn(session_id, question, answer))
        quality_tracker.finish(answer, final.get("attempt", 1))

        for chunk in _chunk(answer):
            yield {"event": "token", "content": chunk}
        yield {"event": "done", "content": answer}

    except Exception as e:
        logger.error(f"[Graph] 异常: {e}", extra={"request_id": request_id})
        quality_tracker.finish("", 0)
        yield {"event": "error", "content": f"处理失败: {e}"}
        yield {"event": "done", "content": f"处理失败: {e}"}


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

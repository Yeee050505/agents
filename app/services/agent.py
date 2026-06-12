from __future__ import annotations
import asyncio
from typing import Dict, Any, List, Optional, Callable, Awaitable

from langchain_core.messages import SystemMessage, HumanMessage

from app.config import settings
from app.services.llm_pool import llm_pool
from app.services.history import get_history, save_history
from app.tools import search_web, needs_realtime_search, is_stale_response
from app.mcp import mcp_registry
from app.utils.logger import logger


MAX_LOOPS = 3


def _get_mcp_tools_prompt() -> str:
    tools = mcp_registry.list_tools()
    if not tools:
        return ""
    lines = ["你可以调用以下工具："]
    for t in tools:
        params = ", ".join(t.inputSchema.get("properties", {}).keys()) if t.inputSchema.get("properties") else "无"
        lines.append(f"- {t.name}: {t.description}（参数: {params}）")
    lines.append("调用方式：说「用 xxx 工具」即可。")
    return "\n".join(lines)


INTENT_PROMPT = """你是一个意图识别主管。分析用户消息，判断属于以下哪一类：
- code: 编程、代码、Bug修复、技术实现等
- knowledge: 知识问答、概念解释、信息查询等
- chat: 日常闲聊、情感交流、开放对话等
- tool: 需要调用外部工具（搜索、查状态、管理会话等）

只返回类别名称，不要其他内容。"""

CODE_AGENT_PROMPT = """你是一个专业的代码助手。帮助用户解决编程问题：提供清晰的代码示例，解释技术方案，给出最佳实践建议。注意代码质量和安全性。回答要简洁直接。"""

KNOWLEDGE_AGENT_PROMPT = """你是一个博学的知识顾问，具备联网搜索能力。回答规则：
1. 优先使用下方提供的联网搜索结果回答实时问题
2. 搜索结果不符合需求时，基于自身知识回答
3. 回答简洁直接，条理清晰。"""

CHAT_AGENT_PROMPT = """你是一个友善的聊天伙伴。具备联网搜索能力，如提供搜索结果请基于搜索内容回答。语气亲切自然，回复简洁有温度。"""

SUPERVISOR_PROMPT = """你是一个任务主管。检查子智能体的回答是否完整回答了用户问题。如果满意，回复"COMPLETE"直接结束。如果不满意，一句话说明需要补充什么。"""


class AgentState:
    def __init__(
        self,
        message: str,
        user_id: str,
        session_id: str,
        request_id: str,
        history: Optional[List[Dict[str, str]]] = None,
    ):
        self.messages: List[Dict[str, str]] = list(history) if history else []
        self.messages.append({"role": "human", "content": message})
        self.request_id = request_id
        self.user_id = user_id
        self.session_id = session_id
        self.intent: str = ""
        self.loop_count: int = 0
        self.task_complete: bool = False
        self.final_answer: str = ""
        self.error: str = ""


class AgentNode:
    def __init__(self, name: str, fn: Callable[[AgentState], Awaitable[None]]):
        self.name = name
        self.fn = fn

    async def run(self, state: AgentState) -> None:
        logger.info(
            f"Agent node: {self.name}",
            extra={"request_id": state.request_id},
        )
        await self.fn(state)


class ConditionalEdge:
    def __init__(
        self,
        source: str,
        router: Callable[[AgentState], str],
        target_map: Dict[str, str],
    ):
        self.source = source
        self.router = router
        self.target_map = target_map


class AgentGraph:
    def __init__(self):
        self.nodes: Dict[str, AgentNode] = {}
        self.edges: List[tuple[str, str]] = []
        self.conditional_edges: List[ConditionalEdge] = []
        self.start_node: Optional[str] = None

    def add_node(self, name: str, fn: Callable[[AgentState], Awaitable[None]]):
        self.nodes[name] = AgentNode(name, fn)

    def add_edge(self, source: str, target: str):
        self.edges.append((source, target))

    def add_conditional_edges(
        self,
        source: str,
        router: Callable[[AgentState], str],
        target_map: Dict[str, str],
    ):
        self.conditional_edges.append(ConditionalEdge(source, router, target_map))

    def set_start(self, name: str):
        self.start_node = name

    def _get_next(self, current: str, state: AgentState) -> Optional[str]:
        for ce in self.conditional_edges:
            if ce.source == current:
                route = ce.router(state)
                return ce.target_map.get(route)
        for src, tgt in self.edges:
            if src == current:
                return tgt
        return None

    async def run(self, state: AgentState) -> AgentState:
        if not self.start_node:
            raise ValueError("Graph has no start node")

        current = self.start_node
        visited = set()
        max_steps = 50

        for _ in range(max_steps):
            if current in visited and current != "supervisor":
                logger.warning(
                    f"Cycle detected at node: {current}",
                    extra={"request_id": state.request_id},
                )
                break
            visited.add(current)

            node = self.nodes.get(current)
            if not node:
                logger.error(
                    f"Node not found: {current}",
                    extra={"request_id": state.request_id},
                )
                break

            await node.run(state)

            next_node = self._get_next(current, state)
            if next_node is None or next_node == "end":
                break
            current = next_node

        return state


async def _call_llm(system_prompt: str, user_message: str, temperature: float = 0.7, enable_search: bool = False) -> str:
    search_context = ""
    if enable_search and needs_realtime_search(user_message):
        search_context = await search_web(user_message, max_results=5)
        if search_context:
            system_prompt += f"\n\n[联网搜索结果——必须基于以下信息回答]\n{search_context}"
            logger.info("Injected search results into prompt")

    instances = await llm_pool.get_healthy_instances()
    if not instances:
        return llm_pool.degradation_message()

    last_error = ""
    for inst in instances:
        try:
            from langchain_openai import ChatOpenAI
            # 每次调用创建独立的 LLM 实例，避免温度配置竞争
            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                openai_api_key=inst.api_key,
                openai_api_base=settings.LLM_BASE_URL,
                timeout=settings.LLM_TIMEOUT,
                temperature=temperature,
                max_retries=1,
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            result = await asyncio.wait_for(
                llm.ainvoke(messages),
                timeout=settings.LLM_TIMEOUT,
            )
            await inst.record_success()

            answer = result.content

            # 降级：如果回复显示知识过时，用搜索结果重试
            if enable_search and is_stale_response(answer) and not search_context:
                search_context = await search_web(user_message, max_results=5)
                if search_context:
                    logger.info("Retrying with search results (stale response detected)")
                    return await _call_llm(
                        system_prompt + f"\n\n[联网搜索结果——必须基于以下信息回答]\n{search_context}",
                        user_message,
                        temperature,
                        enable_search=False,
                    )

            return answer
        except asyncio.TimeoutError:
            last_error = "timeout"
            await inst.record_failure()
            logger.warning(f"LLM timeout, key={inst.api_key[:8]}...")
        except Exception as e:
            last_error = str(e)
            await inst.record_failure()
            logger.warning(f"LLM failed, key={inst.api_key[:8]}...: {e}")

    return llm_pool.degradation_message()


def _build_context(state: AgentState, max_turns: int = 10) -> str:
    """构建对话上下文，取最近 N 轮"""
    recent = state.messages[-max_turns * 2:]  # 每轮 = user + ai
    if len(recent) <= 1:
        return state.messages[-1]["content"]
    lines = []
    for msg in recent:
        role = "用户" if msg["role"] == "human" else "助手" if msg["role"] == "ai" else msg["role"]
        lines.append(f"[{role}]: {msg['content']}")
    return "\n".join(lines)


async def intent_node(state: AgentState):
    last_msg = state.messages[-1]["content"]
    intent = await _call_llm(INTENT_PROMPT, last_msg, temperature=0.1)
    intent = intent.strip().lower()
    # 工具类关键词快捷路由
    if intent not in ("code", "knowledge", "chat", "tool"):
        intent = "chat"
    state.intent = intent
    logger.info(f"Intent identified: {intent}", extra={"request_id": state.request_id})


async def code_agent(state: AgentState):
    content = _build_context(state)
    prompt = CODE_AGENT_PROMPT + "\n\n" + _get_mcp_tools_prompt()
    answer = await _call_llm(prompt, content)
    state.messages.append({"role": "ai", "content": answer})
    state.final_answer = answer


async def knowledge_agent(state: AgentState):
    content = _build_context(state)
    prompt = KNOWLEDGE_AGENT_PROMPT + "\n\n" + _get_mcp_tools_prompt()
    answer = await _call_llm(prompt, content, enable_search=True)
    state.messages.append({"role": "ai", "content": answer})
    state.final_answer = answer


async def chat_agent(state: AgentState):
    content = _build_context(state)
    answer = await _call_llm(CHAT_AGENT_PROMPT, content, enable_search=True)
    state.messages.append({"role": "ai", "content": answer})
    state.final_answer = answer
    state.task_complete = True  # 闲聊跳过 supervisor 审查


async def tool_agent(state: AgentState):
    """MCP 工具调用 Agent — 解析用户意图，调用对应工具"""
    content = state.messages[-1]["content"]
    tools = mcp_registry.list_tools()
    tool_names = [t.name for t in tools]

    # 让 LLM 决定调用哪个工具
    select_prompt = f"""你有以下工具可用：
{_get_mcp_tools_prompt()}

用户消息：{content}

请只返回要调用的工具名称和参数（JSON格式），如：
{{"tool": "web_search", "args": {{"query": "热搜"}}}}
如果不需要调用工具，返回 {{"tool": "none"}}"""

    result = await _call_llm("你是一个工具调度器，根据用户消息选择合适的工具。", select_prompt, temperature=0.1)

    try:
        import json
        parsed = json.loads(result.strip().replace("```json", "").replace("```", ""))
        tool_name = parsed.get("tool", "none")
        if tool_name != "none" and tool_name in tool_names:
            tool_result = await mcp_registry.call_tool(tool_name, parsed.get("args", {}))
            answer = f"工具「{tool_name}」执行结果：\n{tool_result}"
        else:
            answer = "当前没有适合的工具处理你的请求。"

    except Exception:
        answer = f"工具调用解析失败，原始回复：{result}"

    state.messages.append({"role": "ai", "content": answer})
    state.final_answer = answer
    state.task_complete = True


async def supervisor_node(state: AgentState):
    state.loop_count += 1
    if state.loop_count >= MAX_LOOPS:
        state.task_complete = True
        logger.info(f"Max loops ({MAX_LOOPS}) reached", extra={"request_id": state.request_id})
        return

    check_prompt = (
        f"用户问题: {state.messages[0]['content']}\n\n"
        f"助手回答: {state.final_answer}\n\n"
        f"{SUPERVISOR_PROMPT}"
    )
    result = await _call_llm("你是一个严谨的质检员", check_prompt, temperature=0.1)

    if "COMPLETE" in result:
        state.task_complete = True
        answer_part = result.replace("COMPLETE", "").strip()
        if answer_part:
            state.final_answer = answer_part
    else:
        state.messages.append({"role": "human", "content": f"请优化: {result}"})
        logger.info(f"Supervisor refine (loop {state.loop_count})", extra={"request_id": state.request_id})


def route_worker(state: AgentState) -> str:
    intent_map = {
        "code": "code_agent",
        "knowledge": "knowledge_agent",
        "chat": "chat_agent",
        "tool": "tool_agent",
    }
    return intent_map.get(state.intent, "chat_agent")


def route_supervisor(state: AgentState) -> str:
    if state.task_complete:
        return "end"
    # code/knowledge 回到各自 agent 重新回答
    return state.intent + "_agent"


def build_agent_graph() -> AgentGraph:
    graph = AgentGraph()

    graph.add_node("intent", intent_node)
    graph.add_node("code_agent", code_agent)
    graph.add_node("knowledge_agent", knowledge_agent)
    graph.add_node("chat_agent", chat_agent)
    graph.add_node("tool_agent", tool_agent)
    graph.add_node("supervisor", supervisor_node)

    graph.set_start("intent")
    graph.add_conditional_edges("intent", route_worker, {
        "code_agent": "code_agent",
        "knowledge_agent": "knowledge_agent",
        "chat_agent": "chat_agent",
        "tool_agent": "tool_agent",
    })
    graph.add_edge("chat_agent", "end")  # 闲聊直出，不过 supervisor
    graph.add_edge("tool_agent", "end")  # 工具调用直出
    graph.add_edge("code_agent", "supervisor")
    graph.add_edge("knowledge_agent", "supervisor")
    graph.add_conditional_edges("supervisor", route_supervisor, {
        "code_agent": "code_agent",
        "knowledge_agent": "knowledge_agent",
        "end": "end",
    })

    return graph


agent_graph = build_agent_graph()


async def run_agent(
    message: str,
    user_id: str,
    session_id: str,
    request_id: str,
) -> Dict[str, Any]:
    if llm_pool.is_degraded:
        return {
            "answer": llm_pool.degradation_message(),
            "intent": "degraded",
            "loop_count": 0,
            "session_id": session_id,
        }

    history = await get_history(session_id)
    logger.info(
        f"Session {session_id}: {len(history)} history messages loaded",
        extra={"request_id": request_id},
    )

    state = AgentState(
        message=message,
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        history=history,
    )

    try:
        final_state = await asyncio.wait_for(
            agent_graph.run(state),
            timeout=settings.AGENT_TIMEOUT,
        )

        await save_history(session_id, final_state.messages)

        logger.info(
            f"Agent completed: intent={final_state.intent}, loops={final_state.loop_count}",
            extra={"request_id": request_id, "user_id": user_id},
        )

        return {
            "answer": final_state.final_answer,
            "intent": final_state.intent,
            "loop_count": final_state.loop_count,
            "session_id": session_id,
        }
    except asyncio.TimeoutError:
        logger.error("Agent graph timeout", extra={"request_id": request_id})
        return {
            "answer": "处理超时，请简化问题后重试",
            "intent": "error",
            "loop_count": 0,
            "session_id": session_id,
        }
    except Exception as e:
        logger.error(
            f"Agent failed: {e}", exc_info=True,
            extra={"request_id": request_id},
        )
        return {
            "answer": "系统异常，请稍后重试",
            "intent": "error",
            "loop_count": 0,
            "session_id": session_id,
        }

from __future__ import annotations
import asyncio
import json
import re
from typing import Dict, Any, List, Optional, Literal, TypedDict

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from app.config import settings
from app.services.llm_pool import llm_pool
from app.services.history import get_history, save_history
from app.tools import search_web, needs_realtime_search, is_stale_response
from app.mcp import mcp_registry
from app.rag import rag_engine
from app.services.llm_cache import llm_cache
from app.utils.logger import logger


MAX_LOOPS = 3

NODE_TIMEOUTS = {
    "intent": 10,
    "code_agent": 60,
    "knowledge_agent": 60,
    "chat_agent": 30,
    "data_agent": 60,
    "tool_agent": 30,
    "lora_agent": 30,
    "supervisor": 10,
    "merger": 15,
}

PARALLEL_INTENTS = ("code", "knowledge", "data")


class AgentState(TypedDict):
    messages: List[Dict[str, str]]
    intent: str
    loop_count: int
    task_complete: bool
    final_answer: str
    request_id: str
    user_id: str
    session_id: str
    parallel_results: Dict[str, str]


async def _inject_rag_context(system_prompt: str, query: str) -> str:
    ctx = await rag_engine.format_context(query, k=3)
    if ctx:
        system_prompt += f"\n\n{ctx}"
    return system_prompt


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


MAX_REACT_STEPS = 5

REACT_PROMPT = """你是一个可以使用工具的智能助手。当前日期：{date}。

可用工具：
{tool_descriptions}

使用方式：
1. 优先使用内置函数调用能力直接调用工具
2. 如果不支持函数调用，用以下文本格式：

调用工具时：
Action: 工具名称
Action Input: {{"参数名": "参数值"}}

已有答案时：
Final Answer: 最终回答

注意事项：
1. 最多 {max_steps} 轮工具调用
2. 工具返回空时换关键词重试，连续 2 次空结果则直接告知用户未找到，用 Final Answer 结束
3. 收到足够信息后立即用 Final Answer 回答
4. 涉及时间、日期、赛事结果等时效性信息，必须基于[联网搜索结果]回答，你的训练知识可能过时"""



async def _run_react_loop(
    user_message: str,
    *,
    node_name: str = "react",
    tool_names: Optional[List[str]] = None,
    max_steps: int = MAX_REACT_STEPS,
) -> str:
    """通用 ReAct 循环：通过 Function Calling 或文本格式调用工具。
    所有外部工具调用统一通过 MCP，禁止节点直接访问 RAG/搜索。"""
    tools = mcp_registry.list_tools()
    if tool_names:
        tools = [t for t in tools if t.name in tool_names]
    desc_lines = []
    for i, t in enumerate(tools, 1):
        params = ", ".join(t.inputSchema.get("properties", {}).keys()) if t.inputSchema.get("properties") else "无参数"
        desc_lines.append(f"{i}. {t.name}（参数: {params}）: {t.description}")
    tool_descriptions = "\n".join(desc_lines) if desc_lines else "无可用工具"

    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    prompt = REACT_PROMPT.format(date=now, tool_descriptions=tool_descriptions, max_steps=max_steps)
    conversation = f"当前日期：{now}\n用户消息：{user_message}\n\n"
    tool_name_set = {t.name for t in tools}
    tools_schema = _build_tools_schema(tools) if tools else None

    # 对时效性查询，预热搜索注入上下文，避免 LLM 不主动调 web_search
    has_web_search = "web_search" in tool_name_set
    pre_searched = False
    if has_web_search and needs_realtime_search(user_message):
        try:
            pre_search = await search_web(user_message, max_results=5)
            if pre_search:
                conversation += f"[联网搜索结果——必须基于以下信息回答]\n{pre_search}\n\n"
                pre_searched = True
        except Exception:
            pass

    empty_count = 0

    for step in range(max_steps):
        content, tool_calls = await _call_llm(prompt, conversation, temperature=0.1, tools=tools_schema)

        # Path 1: API-level Function Calling
        if tool_calls:
            all_empty = True
            for tc in tool_calls:
                tool_name = tc["name"]
                args = tc["args"]
                conversation += f"Assistant: 调用工具 {tool_name}({args})\n"
                try:
                    tool_result = await mcp_registry.call_tool(tool_name, args)
                    if not tool_result or "未找到相关内容" in str(tool_result):
                        tool_result = f"工具「{tool_name}」未返回有效结果"
                    else:
                        all_empty = False
                except Exception as e:
                    tool_result = f"工具「{tool_name}」调用失败: {e}"
                conversation += f"Observation: {tool_result}\n\n"
            if all_empty:
                empty_count += 1
                if empty_count >= 2:
                    conversation += "注意：已连续多次未查到，请直接告知用户无法获取相关信息，用 Final Answer 结束。\n\n"
            else:
                empty_count = 0
            continue

        # Path 2: Text-format ReAct fallback (for local/LoRA models)
        if not content:
            return "处理失败，请稍后重试。"

        answer = ""
        if "Final Answer:" in content:
            answer = content.split("Final Answer:")[-1].strip()
        elif re.search(r"Action:\s*(\w+)", content):
            pass  # text ReAct tool call, handled below
        else:
            answer = content

        # 已生成最终回答 → 检查过时，非过时才返回
        if answer:
            if pre_searched and is_stale_response(answer):
                conversation += f"Assistant: {answer}\n注意：以上回答使用了过时的训练知识。当前日期是 {now}，请严格根据[联网搜索结果]重新回答。\n\n"
                continue
            return answer

        action_match = re.search(r"Action:\s*(\w+)", content)
        if not action_match:
            continue

        tool_name = action_match.group(1).strip()
        if tool_name not in tool_name_set:
            conversation += f"Assistant: {content}\nObservation: 错误：工具「{tool_name}」不可用，可选工具有 {', '.join(sorted(tool_name_set))}\n\n"
            continue

        args = {}
        action_input_match = re.search(r"Action Input:\s*(.*?)(?=\n(?:Thought|Action|Final Answer)|\Z)", content, re.DOTALL)
        if action_input_match:
            raw = action_input_match.group(1).strip()
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {"query": raw.strip("\"'")}

        conversation += f"Assistant: {content}\n"
        try:
            tool_result = await mcp_registry.call_tool(tool_name, args)
            if not tool_result or "未找到相关内容" in str(tool_result):
                empty_count += 1
                tool_result = f"工具「{tool_name}」未返回有效结果"
                if empty_count >= 2:
                    tool_result += "，连续未查到，请告知用户无法获取相关信息"
            else:
                empty_count = 0
        except Exception as e:
            tool_result = f"工具「{tool_name}」调用失败: {e}"
        conversation += f"Observation: {tool_result}\n\n"

    return "已达最大推理步数，请简化问题后重试。"


def _is_sports_query(text: str) -> bool:
    keywords = [
        "世界杯", "足球", "欧冠", "梅西", "C罗", "姆巴佩",
        "贝利", "马拉多纳", "克洛泽", "罗纳尔多",
    ]
    t = text.lower()
    return any(kw in t for kw in keywords)


INTENT_PROMPT = """你是一个意图识别主管。分析用户消息，判断属于以下哪一类：
- code: 编程、代码、Bug修复、技术实现等
- knowledge: 知识问答、概念解释、信息查询等
- chat: 日常闲聊、情感交流、开放对话等
- tool: 需要调用外部工具（搜索、查状态、管理会话等）
- data: 数据分析、CSV/JSON处理、统计分析、数据可视化等

只返回类别名称，不要其他内容。"""

CODE_AGENT_PROMPT = """你是一个专业的代码助手。帮助用户解决编程问题：提供清晰的代码示例，解释技术方案，给出最佳实践建议。注意代码质量和安全性。回答要简洁直接。"""

CHAT_AGENT_PROMPT = """你是一个友善的聊天伙伴。具备联网搜索能力，如提供搜索结果请基于搜索内容回答。语气亲切自然，回复简洁有温度。"""

DATA_AGENT_PROMPT = """你是一个数据分析专家。帮助用户处理和分析数据：解读CSV/JSON等结构化数据，执行统计分析，生成可视化建议，发现数据趋势和异常。回答要简洁专业，附上关键数字和结论。"""


async def _run_with_timeout(node_name: str, coro, default: str = ""):
    timeout = NODE_TIMEOUTS.get(node_name, 30)
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Node timeout: {node_name} ({timeout}s)")
        return default
    except Exception as e:
        logger.warning(f"Node failed: {node_name} - {e}")
        return default


# ─── LangGraph 节点函数 ───

async def intent_node(state: AgentState) -> dict:
    last_msg = state["messages"][-1]["content"]
    if _is_sports_query(last_msg):
        intent = "lora"
    else:
        intent = await _run_with_timeout("intent", _call_llm_text(INTENT_PROMPT, last_msg, temperature=0.1), "chat")
        intent = intent.strip().lower()
        if intent not in ("code", "knowledge", "chat", "tool", "data"):
            intent = "chat"
    logger.info(f"Intent identified: {intent}", extra={"request_id": state["request_id"]})
    return {"intent": intent, "parallel_results": {}}


async def code_agent(state: AgentState) -> dict:
    content = _build_context(state)
    prompt = CODE_AGENT_PROMPT + "\n\n" + _get_mcp_tools_prompt()
    answer = await _run_with_timeout("code_agent", _call_llm_text(prompt, content), "代码助手暂时不可用，请稍后重试。")
    new_messages = list(state["messages"]) + [{"role": "ai", "content": answer}]
    return {"messages": new_messages, "final_answer": answer}


async def knowledge_agent(state: AgentState) -> dict:
    content = _build_context(state)
    answer = await _run_with_timeout(
        "knowledge_agent",
        _run_react_loop(content, node_name="knowledge_agent", tool_names=["rag_search", "web_search", "sports_search"]),
        "知识库暂时不可用，请稍后重试。",
    )
    new_messages = list(state["messages"]) + [{"role": "ai", "content": answer}]
    return {"messages": new_messages, "final_answer": answer}


async def chat_agent(state: AgentState) -> dict:
    content = _build_context(state)
    answer = await _run_with_timeout("chat_agent", _call_llm_text(CHAT_AGENT_PROMPT, content, enable_search=True), "聊天助手暂时不可用。")
    new_messages = list(state["messages"]) + [{"role": "ai", "content": answer}]
    return {"messages": new_messages, "final_answer": answer, "task_complete": True}


async def data_agent(state: AgentState) -> dict:
    content = _build_context(state)
    prompt = DATA_AGENT_PROMPT + "\n\n" + _get_mcp_tools_prompt()
    answer = await _run_with_timeout("data_agent", _call_llm_text(prompt, content), "数据分析助手暂时不可用，请稍后重试。")
    new_messages = list(state["messages"]) + [{"role": "ai", "content": answer}]
    return {"messages": new_messages, "final_answer": answer}


async def tool_agent(state: AgentState) -> dict:
    content = _build_context(state)
    answer = await _run_with_timeout(
        "tool_agent",
        _run_react_loop(content, node_name="tool_agent"),
        "工具调用失败，请稍后重试。",
    )
    new_messages = list(state["messages"]) + [{"role": "ai", "content": answer}]
    return {"messages": new_messages, "final_answer": answer, "task_complete": True}


async def lora_agent(state: AgentState) -> dict:
    content = _build_context(state)
    try:
        from app.lora import trainer as lora_trainer
        # LoRA 推理（L1 模型层，不经过 MCP）
        ctx = await asyncio.wait_for(rag_engine.format_context(content, k=5), timeout=10)
        input_text = f"{ctx}\n\n用户问：{content}" if ctx else content
        answer = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, lora_trainer.infer, "世界杯助手", input_text, 256),
            timeout=20,
        )
        if len(answer) >= 10 and not is_stale_response(answer):
            new_messages = list(state["messages"]) + [{"role": "ai", "content": answer}]
            return {"messages": new_messages, "final_answer": answer, "task_complete": True}
        logger.info("LoRA quality low, fallback to ReAct-MCP")
    except Exception as e:
        logger.warning(f"LoRA failed, fallback to ReAct-MCP: {e}")
    # 降级走 ReAct 知识路径（L3 MCP → L2 RAG）
    answer = await _run_with_timeout(
        "lora_agent",
        _run_react_loop(content, node_name="lora_agent", tool_names=["rag_search", "web_search", "sports_search"]),
        "知识库暂时不可用。",
    )
    new_messages = list(state["messages"]) + [{"role": "ai", "content": answer}]
    return {"messages": new_messages, "final_answer": answer, "task_complete": True}


async def merger_node(state: AgentState) -> dict:
    results = state.get("parallel_results", {})
    if not results:
        return {"task_complete": True}
    parts = [v for v in results.values() if v]
    combined = "\n\n---\n\n".join(parts) if parts else state.get("final_answer", "")
    if not combined:
        combined = "处理完成，但未能生成有效回答。"
    new_messages = list(state["messages"]) + [{"role": "ai", "content": combined}]
    return {"messages": new_messages, "final_answer": combined, "task_complete": True}


async def supervisor_node(state: AgentState) -> dict:
    loop_count = state["loop_count"] + 1
    if loop_count >= MAX_LOOPS:
        return {"loop_count": loop_count, "task_complete": True}
    answer = state["final_answer"]
    if not answer or len(answer) < 20:
        new_messages = list(state["messages"]) + [{"role": "human", "content": "请补充详细回答"}]
        logger.info(f"Supervisor refine (loop {loop_count}) - empty/short answer", extra={"request_id": state["request_id"]})
        return {"messages": new_messages, "loop_count": loop_count}
    if is_stale_response(answer):
        new_messages = list(state["messages"]) + [{"role": "human", "content": "请基于最新信息回答"}]
        logger.info(f"Supervisor refine (loop {loop_count}) - stale response", extra={"request_id": state["request_id"]})
        return {"messages": new_messages, "loop_count": loop_count}
    # supervisor 重新分类意图
    last_msg = state["messages"][-1]["content"] if state["messages"] else ""
    if "不知道" in answer[:50] or "我不清楚" in answer[:50] or "无法回答" in answer[:50]:
        new_intent = await _run_with_timeout("supervisor", _call_llm_text(INTENT_PROMPT, last_msg, temperature=0.1), "chat")
        new_intent = new_intent.strip().lower()
        if new_intent in ("code", "knowledge", "chat", "tool", "data"):
            logger.info(f"Supervisor reclassify: {state['intent']} -> {new_intent}", extra={"request_id": state["request_id"]})
            return {"intent": new_intent, "loop_count": loop_count}
    return {"loop_count": loop_count, "task_complete": True}


# ─── 路由函数 ───

def route_worker(state: AgentState) -> Literal["code_agent", "knowledge_agent", "chat_agent", "tool_agent", "data_agent", "lora_agent"]:
    return {
        "code": "code_agent",
        "knowledge": "knowledge_agent",
        "chat": "chat_agent",
        "tool": "tool_agent",
        "data": "data_agent",
        "lora": "lora_agent",
    }.get(state["intent"], "chat_agent")


def route_supervisor(state: AgentState) -> str:
    if state["task_complete"]:
        return END
    intent = state["intent"]
    if intent in PARALLEL_INTENTS and state.get("parallel_results", {}):
        return "merger"
    return intent + "_agent"


# ─── 构建 LangGraph ───

def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intent", intent_node)
    graph.add_node("code_agent", code_agent)
    graph.add_node("knowledge_agent", knowledge_agent)
    graph.add_node("chat_agent", chat_agent)
    graph.add_node("data_agent", data_agent)
    graph.add_node("tool_agent", tool_agent)
    graph.add_node("lora_agent", lora_agent)
    graph.add_node("merger", merger_node)
    graph.add_node("supervisor", supervisor_node)
    graph.set_entry_point("intent")
    graph.add_conditional_edges("intent", route_worker, {
        "code_agent": "code_agent",
        "knowledge_agent": "knowledge_agent",
        "chat_agent": "chat_agent",
        "data_agent": "data_agent",
        "tool_agent": "tool_agent",
        "lora_agent": "lora_agent",
    })
    graph.add_edge("chat_agent", END)
    graph.add_edge("tool_agent", END)
    graph.add_edge("lora_agent", END)
    graph.add_edge("code_agent", "supervisor")
    graph.add_edge("knowledge_agent", "supervisor")
    graph.add_edge("data_agent", "supervisor")
    graph.add_conditional_edges("supervisor", route_supervisor, {
        "code_agent": "code_agent",
        "knowledge_agent": "knowledge_agent",
        "data_agent": "data_agent",
        "merger": "merger",
        END: END,
    })
    graph.add_edge("merger", END)
    return graph.compile()


agent_graph = build_agent_graph()


# ─── LLM 调用 ───

def _build_tools_schema(tools: list) -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.inputSchema,
        }
    } for t in tools]


async def _call_llm(system_prompt: str, user_message: str, temperature: float = 0.7, enable_search: bool = False, tools: Optional[list[dict]] = None) -> tuple:
    cache_key_prompt = system_prompt
    cached = await llm_cache.get(cache_key_prompt, user_message, temperature)
    if cached is not None:
        return cached, []
    if enable_search:
        system_prompt = await _inject_rag_context(system_prompt, user_message)
    search_context = ""
    if enable_search and needs_realtime_search(user_message):
        search_context = await search_web(user_message, max_results=5)
        if search_context:
            system_prompt += f"\n\n[联网搜索结果——必须基于以下信息回答]\n{search_context}"
    first = await llm_pool.get_next_instance()
    if not first:
        return llm_pool.degradation_message(), []
    remaining = [i for i in await llm_pool.get_healthy_instances() if i is not first]
    last_error = ""
    for inst in [first] + remaining:
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                openai_api_key=inst.api_key,
                openai_api_base=settings.LLM_BASE_URL,
                timeout=settings.LLM_TIMEOUT,
                temperature=temperature,
                max_retries=1,
            )
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
            result = await asyncio.wait_for(llm.ainvoke(messages, tools=tools) if tools else llm.ainvoke(messages), timeout=settings.LLM_TIMEOUT)
            await inst.record_success()
            answer = result.content
            tool_calls = []
            if tools and result.tool_calls:
                for tc in result.tool_calls:
                    tool_calls.append({
                        "name": tc["name"],
                        "args": tc["args"] if isinstance(tc["args"], dict) else json.loads(tc["args"]),
                    })
            if enable_search and is_stale_response(answer) and not search_context:
                search_context = await search_web(user_message, max_results=5)
                if search_context:
                    logger.info("Retrying with search results (stale response detected)")
                    return await _call_llm(
                        system_prompt + f"\n\n[联网搜索结果——必须基于以下信息回答]\n{search_context}",
                        user_message, temperature, enable_search=False)
            if not tool_calls:
                await llm_cache.set(cache_key_prompt, user_message, temperature, answer)
            return answer, tool_calls
        except asyncio.TimeoutError:
            last_error = "timeout"
            await inst.record_failure()
            logger.warning(f"LLM timeout, key={inst.api_key[:8]}...")
        except Exception as e:
            last_error = str(e)
            await inst.record_failure()
            logger.warning(f"LLM failed, key={inst.api_key[:8]}...: {e}")
    return llm_pool.degradation_message(), []


async def _call_llm_text(*args, **kwargs) -> str:
    """Convenience wrapper around _call_llm that returns just the text content."""
    content, _ = await _call_llm(*args, **kwargs)
    return content


async def _call_llm_stream(system_prompt: str, user_message: str, temperature: float = 0.7, enable_search: bool = False):
    cache_key_prompt = system_prompt
    cached = await llm_cache.get(cache_key_prompt, user_message, temperature)
    if cached is not None:
        yield cached
        return
    if enable_search:
        system_prompt = await _inject_rag_context(system_prompt, user_message)
    search_context = ""
    if enable_search and needs_realtime_search(user_message):
        search_context = await search_web(user_message, max_results=5)
        if search_context:
            system_prompt += f"\n\n[联网搜索结果——必须基于以下信息回答]\n{search_context}"
    first = await llm_pool.get_next_instance()
    if not first:
        yield llm_pool.degradation_message()
        return
    remaining = [i for i in await llm_pool.get_healthy_instances() if i is not first]
    full_answer = ""
    for inst in [first] + remaining:
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                openai_api_key=inst.api_key,
                openai_api_base=settings.LLM_BASE_URL,
                timeout=settings.LLM_TIMEOUT,
                temperature=temperature,
            )
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
            async for chunk in llm.astream(messages):
                text = chunk.content if hasattr(chunk, "content") else str(chunk)
                full_answer += text
                yield text
            await inst.record_success()
            await llm_cache.set(cache_key_prompt, user_message, temperature, full_answer)
            return
        except Exception as e:
            await inst.record_failure()
            logger.warning(f"LLM stream failed, key={inst.api_key[:8]}...: {e}")
    yield llm_pool.degradation_message()


def _build_context(state: AgentState, max_turns: int = 10) -> str:
    recent = state["messages"][-max_turns * 2:]
    if len(recent) <= 1:
        return state["messages"][-1]["content"]
    lines = []
    for msg in recent:
        role = "用户" if msg["role"] == "human" else "助手" if msg["role"] == "ai" else msg["role"]
        lines.append(f"[{role}]: {msg['content']}")
    return "\n".join(lines)


# ─── stream 入口（使用 graph.astream 实现节点级流式） ───

async def run_agent_stream(message: str, user_id: str, session_id: str, request_id: str):
    if llm_pool.is_degraded:
        yield {"token": llm_pool.degradation_message()}
        yield {"intent": "degraded", "session_id": session_id, "loop_count": 0}
        return

    history = await get_history(session_id)
    logger.info(f"Session {session_id}: {len(history)} history messages", extra={"request_id": request_id})
    full_messages = list(history) + [{"role": "human", "content": message}]

    # 快速路径：LoRA 不走图
    if _is_sports_query(message):
        try:
            from app.lora import trainer as lora_trainer
            ctx = await asyncio.wait_for(rag_engine.format_context(message, k=5), timeout=5)
            input_text = f"{ctx}\n\n用户问：{message}" if ctx else message
            answer = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, lora_trainer.infer, "世界杯助手", input_text, 256),
                timeout=25,
            )
            if len(answer) >= 10 and not is_stale_response(answer):
                yield {"token": answer}
                await save_history(session_id, full_messages + [{"role": "ai", "content": answer}])
                yield {"intent": "lora", "session_id": session_id, "loop_count": 0}
                return
        except Exception:
            logger.info("LoRA stream fallback to graph")

    initial_state: AgentState = {
        "messages": full_messages,
        "intent": "",
        "loop_count": 0,
        "task_complete": False,
        "final_answer": "",
        "request_id": request_id,
        "user_id": user_id,
        "session_id": session_id,
        "parallel_results": {},
    }

    full_answer = ""
    intent = ""
    try:
        async for event in agent_graph.astream(initial_state):
            for node_name, output in event.items():
                if "intent" in output and output["intent"]:
                    intent = output["intent"]
                if "final_answer" in output and output["final_answer"]:
                    chunk = output["final_answer"]
                    if chunk not in (full_answer, full_answer + "\n"):
                        new_part = chunk[len(full_answer):]
                        if new_part:
                            full_answer = chunk
                            yield {"token": new_part}
        await save_history(session_id, full_messages + [{"role": "ai", "content": full_answer}])
        yield {"intent": intent or "chat", "session_id": session_id, "loop_count": 0}
    except Exception as e:
        logger.error(f"Agent stream failed: {e}", exc_info=True)
        yield {"token": "系统异常，请稍后重试。"}
        yield {"intent": "error", "session_id": session_id, "loop_count": 0}


# ─── 非流式入口（使用图 ainvoke） ───

async def run_agent(
    message: str,
    user_id: str,
    session_id: str,
    request_id: str,
) -> Dict[str, Any]:
    if llm_pool.is_degraded:
        return {"answer": llm_pool.degradation_message(), "intent": "degraded", "loop_count": 0, "session_id": session_id}

    history = await get_history(session_id)
    logger.info(f"Session {session_id}: {len(history)} history messages loaded", extra={"request_id": request_id})

    initial_state: AgentState = {
        "messages": (list(history) if history else []) + [{"role": "human", "content": message}],
        "intent": "",
        "loop_count": 0,
        "task_complete": False,
        "final_answer": "",
        "request_id": request_id,
        "user_id": user_id,
        "session_id": session_id,
        "parallel_results": {},
    }

    try:
        final_state = await asyncio.wait_for(
            agent_graph.ainvoke(initial_state), timeout=settings.AGENT_TIMEOUT)
        await save_history(session_id, final_state["messages"])
        logger.info(f"Agent completed: intent={final_state['intent']}, loops={final_state['loop_count']}",
                    extra={"request_id": request_id, "user_id": user_id})
        return {
            "answer": final_state["final_answer"],
            "intent": final_state["intent"],
            "loop_count": final_state["loop_count"],
            "session_id": session_id,
        }
    except asyncio.TimeoutError:
        logger.error("Agent graph timeout", extra={"request_id": request_id})
        return {"answer": "处理超时，请简化问题后重试", "intent": "error", "loop_count": 0, "session_id": session_id}
    except Exception as e:
        logger.error(f"Agent failed: {e}", exc_info=True, extra={"request_id": request_id})
        return {"answer": "系统异常，请稍后重试", "intent": "error", "loop_count": 0, "session_id": session_id}

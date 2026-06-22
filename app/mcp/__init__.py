from __future__ import annotations
import json
from typing import Any, Callable, Dict, List, Literal
from mcp.types import Tool
from app.utils.logger import logger


class MCPToolRegistry:
    """MCP 工具注册中心 — 统一管理所有 Agent 可调用工具"""

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: Callable,
        parameters: dict | None = None,
    ):
        self._tools[name] = {
            "name": name,
            "description": description,
            "handler": handler,
            "parameters": parameters or {"type": "object", "properties": {}},
        }
        logger.info(f"MCP tool registered: {name}")

    def list_tools(self) -> List[Tool]:
        return [
            Tool(
                name=info["name"],
                description=info["description"],
                inputSchema=info["parameters"],
            )
            for info in self._tools.values()
        ]

    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        info = self._tools.get(name)
        if not info:
            return json.dumps({"error": f"Tool not found: {name}"})

        handler = info["handler"]
        args = arguments or {}
        try:
            import inspect
            if inspect.iscoroutinefunction(handler):
                result = await handler(**args)
            else:
                result = handler(**args)
            return json.dumps(result, ensure_ascii=False, default=str) if not isinstance(result, str) else result
        except Exception as e:
            logger.error(f"MCP tool call failed: {name}: {e}")
            return json.dumps({"error": str(e)})


mcp_registry = MCPToolRegistry()


# ====== 注册已有工具 ======

async def _tool_web_search(query: str = ""):
    from app.tools import search_web
    results = await search_web(query, max_results=5)
    return {"query": query, "results": results[:500] if results else "未找到结果"}

mcp_registry.register(
    name="web_search",
    description="搜索互联网获取实时信息。传入关键词，返回搜索结果标题、摘要和链接。",
    handler=_tool_web_search,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["query"],
    },
)


def _tool_rate_stats():
    from app.middleware.rate_limiter import rate_limiter
    from app.services.llm_pool import llm_pool
    return {
        "global": rate_limiter.get_global_stats(),
        "llm_pool": llm_pool.stats(),
    }

mcp_registry.register(
    name="rate_stats",
    description="查看系统限流状态和 LLM 密钥池健康情况",
    handler=_tool_rate_stats,
)


async def _tool_session_info(session_id: str = ""):
    from app.services.history import get_history
    history = await get_history(session_id) if session_id else []
    return {"session_id": session_id, "message_count": len(history)}

mcp_registry.register(
    name="session_info",
    description="查看指定会话的历史消息数量",
    handler=_tool_session_info,
    parameters={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "会话ID"}
        },
        "required": ["session_id"],
    },
)


# ═══════ 体育赛事数据 ═══════

async def _tool_sports_search(query: str = ""):
    from app.tools.sports import search_sports
    results = await search_sports(query)
    return {"query": query, "results": results[:500] if results else "未找到相关比赛数据"}

mcp_registry.register(
    name="sports_search",
    description="搜索体育赛事比分、赛程、比赛结果等数据。传入比赛描述（球队、日期、赛事），返回比分和赛程信息。适用于足球、篮球等体育赛事查询。",
    handler=_tool_sports_search,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "比赛描述，如「日本 vs 荷兰 2026年6月15日 世界杯」"},
        },
        "required": ["query"],
    },
)


# ═══════ L2: RAG 知识库 ═══════

async def _tool_rag_search(query: str = "", k: int = 3):
    from app.rag import rag_engine
    hits = await rag_engine.search(query, k=k)
    if not hits:
        return {"query": query, "results": "未找到相关内容"}
    lines = []
    for h in hits:
        lines.append(f"[相关性 {h['score']:.2f}] {h['text']}")
    return {"query": query, "results": "\n\n".join(lines)}

mcp_registry.register(
    name="rag_search",
    description="搜索本地知识库（世界杯、体育、通用文档）。传入关键词，返回最相关的文档片段。用于查询历届赛事、规则、历史数据等。",
    handler=_tool_rag_search,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "k": {"type": "integer", "description": "返回结果数量（默认3）"},
        },
        "required": ["query"],
    },
)

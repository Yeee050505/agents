from __future__ import annotations
import json
from typing import Callable, List
from mcp.types import Tool
from app.utils.logger import logger


class MCPToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, handler: Callable, parameters: dict | None = None):
        self._tools[name] = {
            "name": name,
            "description": description,
            "handler": handler,
            "parameters": parameters or {"type": "object", "properties": {}},
        }
        logger.info(f"Tool registered: {name}")

    def list_tools(self) -> List[Tool]:
        return [Tool(name=info["name"], description=info["description"], inputSchema=info["parameters"]) for info in self._tools.values()]

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
            logger.error(f"Tool call failed: {name}: {e}")
            return json.dumps({"error": str(e)})


mcp_registry = MCPToolRegistry()


async def _tool_web_search(query: str = ""):
    from app.tools import search_web
    results = await search_web(query, max_results=5)
    return {"query": query, "results": results[:500] if results else "未找到结果"}

mcp_registry.register(
    name="web_search",
    description="搜索互联网获取游戏相关信息。传入关键词，返回搜索结果。",
    handler=_tool_web_search,
    parameters={"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]},
)


async def _tool_game_search(query: str = ""):
    from app.tools.game import search_game
    results = await search_game(query)
    return {"query": query, "results": results[:500] if results else "未找到相关游戏数据"}

mcp_registry.register(
    name="game_search",
    description="搜索游戏数据（TapTap）。传入游戏名称，返回价格、评分、标签、开发商、简介等信息。",
    handler=_tool_game_search,
    parameters={"type": "object", "properties": {"query": {"type": "string", "description": "游戏名称或关键词，如「黑神话悟空」「艾尔登法环」"}}, "required": ["query"]},
)


def _tool_rag_search(query: str = "", k: int = 3):
    from app.rag import rag_engine
    hits = rag_engine.search(query, k=k)
    if not hits:
        return {"query": query, "results": "未找到相关内容"}
    lines = []
    for h in hits:
        lines.append(f"[相关性 {h['score']:.2f}] {h['content']}")
    return {"query": query, "results": "\n\n".join(lines)}

mcp_registry.register(
    name="rag_search",
    description="搜索本地知识库（游戏百科、游戏类型、历史、术语）。传入关键词，返回相关文档片段。",
    handler=_tool_rag_search,
    parameters={"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}, "k": {"type": "integer", "description": "返回数量"}}, "required": ["query"]},
)

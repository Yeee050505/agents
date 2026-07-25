from __future__ import annotations
import json
from app.agents.base import BaseAgent

TOOL_AGENT_PROMPT = """你是一个游戏数据查询专家。
调用 Steam API 获取游戏实时动态数据（评分、价格、在线人数、新闻），整理结果。
不处理静态行业知识，静态知识由知识库负责。
返回 JSON 格式：{"tool_results": [合并后的数据文本], "sources": ["steam_api"]}"""


class ToolAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="tool_agent", system_prompt=TOOL_AGENT_PROMPT, temperature=0.1)

    async def run(self, sub_queries: list[str]) -> dict:
        all_results = []
        sources = []
        for q in sub_queries:
            raw = await self.call_tool("game_search", query=q)
            try:
                data = json.loads(raw)
                r = data.get("results", "")
                if r and "未找到" not in r:
                    all_results.append(f"[SteamAPI] {r}")
                    sources.append("steam_api")
            except (json.JSONDecodeError, TypeError):
                pass

        if not all_results:
            return {"tool_results": [], "sources": []}

        merged = "\n\n".join(all_results)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"工具返回：\n{merged}"},
        ]
        raw = await self._call_llm(messages)
        try:
            result = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            return result
        except (json.JSONDecodeError, AttributeError):
            return {"tool_results": [merged], "sources": sources}

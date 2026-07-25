from __future__ import annotations
import json
from app.agents.base import BaseAgent

RETRIEVER_PROMPT = """你是一个知识库检索结果整理专家。
将检索到的多段内容去重、排序、摘要，保留关键信息。
返回 JSON 格式：{"retrieved": [合并后的文本], "sources": [来源文档名]}"""


class RetrieverAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="retriever", system_prompt=RETRIEVER_PROMPT, temperature=0.1)

    async def run(self, sub_queries: list[str]) -> dict:
        all_hits = []
        seen = set()
        for q in sub_queries:
            raw = await self.call_tool("rag_search", query=q, k=3)
            try:
                data = json.loads(raw)
                results = data.get("results", "")
                if results and "未找到" not in results:
                    for line in results.split("\n\n"):
                        content = line.strip()
                        if content and content not in seen:
                            seen.add(content)
                            all_hits.append(content)
            except (json.JSONDecodeError, TypeError):
                pass

        if not all_hits:
            return {"retrieved": [], "sources": []}

        merged = "\n\n".join(all_hits)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"检索结果：\n{merged}"},
        ]
        raw = await self._call_llm(messages)
        try:
            result = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            return result
        except (json.JSONDecodeError, AttributeError):
            return {"retrieved": [merged], "sources": []}

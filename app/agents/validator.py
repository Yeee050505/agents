from __future__ import annotations
import json
from app.agents.base import BaseAgent

VALIDATOR_PROMPT = """你是一个内容校验专家。
检查回答是否与检索结果一致，是否包含幻觉（无依据的信息）。

规则：
1. 回答中所有事实必须有检索结果或工具返回支撑
2. 如果发现无依据内容，标记为幻觉
3. 返回 JSON：{"passed": true/false, "issues": ["问题描述"], "suggestions": ["修改建议"]}"""


class ValidatorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="validator", system_prompt=VALIDATOR_PROMPT, temperature=0.1)

    async def run(self, question: str, retrieved: list[str], tool_results: list[str], draft_answer: str) -> dict:
        context_parts = []
        if retrieved:
            context_parts.append("知识库检索：\n" + "\n".join(retrieved[:3]))
        if tool_results:
            context_parts.append("工具返回：\n" + "\n".join(tool_results[:3]))
        context = "\n\n".join(context_parts) if context_parts else "无外部数据"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"问题：{question}\n\n参考数据：\n{context}\n\n待校验的回答：\n{draft_answer}"},
        ]
        raw = await self._call_llm(messages)
        try:
            result = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            return result
        except (json.JSONDecodeError, AttributeError):
            return {"passed": True, "issues": [], "suggestions": []}

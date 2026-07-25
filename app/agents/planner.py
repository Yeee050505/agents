from __future__ import annotations
import json
from app.agents.base import BaseAgent

PLANNER_PROMPT = """你是一个游戏问答的问题拆解专家。
将用户问题拆解为 1-3 个独立子查询，每个子查询应当只包含一个检索需求。

规则：
1. 如果问题很简单（评分、价格、类型），只返回 1 个子查询
2. 返回 JSON 格式：{"sub_queries": ["查询1", "查询2"], "reasoning": "拆解思路"}
3. 只返回 JSON，不要多余文字"""


class PlannerAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="planner", system_prompt=PLANNER_PROMPT, temperature=0.3)

    async def run(self, question: str) -> dict:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"问题：{question}"},
        ]
        raw = await self._call_llm(messages)
        try:
            plan = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            if "sub_queries" not in plan:
                plan = {"sub_queries": [question], "reasoning": "无需拆分"}
            return plan
        except (json.JSONDecodeError, AttributeError):
            return {"sub_queries": [question], "reasoning": "解析失败，使用原始问题"}

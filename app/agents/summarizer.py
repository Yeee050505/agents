from __future__ import annotations
from app.agents.base import BaseAgent

SUMMARIZER_PROMPT = """你是一个游戏问答的写作专家。
基于以下素材，撰写完整的最终回答。要求：
1. 条理清晰，按逻辑分段
2. 引用来源标记（知识库/SteamAPI/网页）
3. 如果素材不足，明确指出无法回答的部分
4. 语气专业、中立
5. 参考对话历史，保持回答连贯"""


class SummarizerAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="summarizer", system_prompt=SUMMARIZER_PROMPT, temperature=0.3)

    async def run(self, question: str, retrieved: list[str], tool_results: list[str], context: str = "", feedback: str = "") -> str:
        context_parts = []
        if context:
            context_parts.append(context)
        if retrieved:
            context_parts.append("【知识库检索】\n" + "\n\n".join(retrieved))
        if tool_results:
            context_parts.append("【外部工具数据】\n" + "\n\n".join(tool_results))
        merged = "\n\n".join(context_parts) if context_parts else "无可用数据"

        user_content = f"问题：{question}\n\n素材：\n{merged}"
        if feedback:
            user_content += f"\n\n校验反馈（请据此修改）：\n{feedback}"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        return await self._call_llm(messages)

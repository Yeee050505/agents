from __future__ import annotations
from typing import List

from app.utils.logger import logger

EXTRACT_PROMPT = """从以下对话中提取关于用户的重要事实和偏好。
每行输出一条，格式为：
[category] 文本内容

category 只能是以下之一：
- preference: 用户的偏好、喜好、兴趣
- fact: 关于用户的事实信息（身份、背景、说过的话）
- experience: 用户的经历、遇到过的事

要求：
1. 只提取明确提到的信息，不要编造
2. 不要提取常识性、通用性信息
3. 多条信息分多行输出
4. 如果没有任何值得记录的信息，只输出"无"

对话：
{conversation}"""


async def extract_facts(conversation: str, llm_func) -> List[dict]:
    """调用 LLM 从对话中提取记忆片段，返回 [{"category":..., "content":...}]"""
    if not conversation.strip():
        return []

    try:
        result = await llm_func(EXTRACT_PROMPT.format(conversation=conversation[-2000:]), temperature=0.1)
    except Exception as e:
        logger.warning(f"Memory extraction failed: {e}")
        return []

    facts = []
    for line in result.strip().split("\n"):
        line = line.strip()
        if not line or line == "无":
            continue
        for cat in ("preference", "fact", "experience"):
            prefix = f"[{cat}] "
            if line.startswith(prefix):
                content = line[len(prefix):].strip()
                if content:
                    facts.append({"category": cat, "content": content})
                break
    return facts

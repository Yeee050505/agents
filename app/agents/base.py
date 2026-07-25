from __future__ import annotations
import asyncio
import json
from typing import Optional

from app.config import settings
from app.services.llm_pool import llm_pool
from app.mcp import mcp_registry
from app.utils.logger import logger


class BaseAgent:
    def __init__(self, name: str, system_prompt: str, temperature: float = 0.1):
        self.name = name
        self.system_prompt = system_prompt
        self.temperature = temperature

    async def _call_llm(self, messages: list[dict], tools: Optional[list[dict]] = None) -> str:
        if llm_pool.is_degraded:
            return llm_pool.degradation_message()
        first = await llm_pool.get_next_instance()
        if not first:
            return llm_pool.degradation_message()
        remaining = [i for i in await llm_pool.get_healthy_instances() if i is not first]

        for inst in [first] + remaining:
            try:
                from langchain_openai import ChatOpenAI
                from langchain_core.messages import SystemMessage, HumanMessage
                llm = ChatOpenAI(
                    model=settings.LLM_MODEL,
                    openai_api_key=inst.api_key,
                    openai_api_base=settings.LLM_BASE_URL,
                    timeout=settings.LLM_TIMEOUT,
                    temperature=self.temperature,
                    max_retries=1,
                )
                lc_messages = []
                for m in messages:
                    if m["role"] == "system":
                        lc_messages.append(SystemMessage(content=m["content"]))
                    else:
                        lc_messages.append(HumanMessage(content=m["content"]))
                result = await asyncio.wait_for(
                    llm.ainvoke(lc_messages, tools=tools) if tools else llm.ainvoke(lc_messages),
                    timeout=settings.LLM_TIMEOUT,
                )
                await inst.record_success()
                return result.content
            except asyncio.TimeoutError:
                await inst.record_failure()
                logger.warning(f"Agent {self.name} LLM timeout, key={inst.api_key[:8]}...")
            except Exception as e:
                await inst.record_failure()
                logger.warning(f"Agent {self.name} LLM failed: {e}")
        return llm_pool.degradation_message()

    async def call_tool(self, name: str, **kwargs) -> str:
        try:
            return await mcp_registry.call_tool(name, kwargs)
        except Exception as e:
            logger.warning(f"Agent {self.name} tool {name} failed: {e}")
            return json.dumps({"error": str(e)})

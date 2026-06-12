from __future__ import annotations
import asyncio
import time
import random
from enum import Enum
from typing import Optional, List
from app.config import settings
from app.utils.logger import logger


class CircuitState(Enum):
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断
    HALF_OPEN = "half_open" # 半开探测


class LLMInstance:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.failures = 0
        self.last_used = 0.0
        self.last_failure_time = 0.0
        self.state = CircuitState.CLOSED
        self.open_at = 0.0
        self._lock = asyncio.Lock()

    # 熔断冷却时间（秒）
    COOLDOWN_BASE = 10
    COOLDOWN_MAX = 120

    @property
    def cooldown(self) -> float:
        return min(self.COOLDOWN_BASE * (2 ** (self.failures - 1)), self.COOLDOWN_MAX)

    async def record_success(self):
        async with self._lock:
            self.failures = 0
            self.last_used = time.time()
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                logger.info(f"Circuit CLOSED (recovered), key={self.api_key[:8]}...")

    async def record_failure(self):
        async with self._lock:
            self.failures += 1
            self.last_used = time.time()
            self.last_failure_time = time.time()

            if self.failures >= settings.LLM_MAX_RETRIES and self.state == CircuitState.CLOSED:
                self.state = CircuitState.OPEN
                self.open_at = time.time()
                logger.warning(
                    f"Circuit OPEN (blown), key={self.api_key[:8]}..., "
                    f"failures={self.failures}, cooldown={self.cooldown}s"
                )
            elif self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.open_at = time.time()
                logger.warning(f"Half-open probe FAILED, circuit OPEN again, key={self.api_key[:8]}...")

    async def allow_request(self) -> bool:
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                elapsed = time.time() - self.open_at
                if elapsed >= self.cooldown:
                    self.state = CircuitState.HALF_OPEN
                    logger.info(f"Circuit HALF_OPEN (probing), key={self.api_key[:8]}...")
                    return True
                return False
            if self.state == CircuitState.HALF_OPEN:
                return True
            return True

    def to_dict(self) -> dict:
        return {
            "api_key": self.api_key[:8] + "...",
            "state": self.state.value,
            "failures": self.failures,
            "cooldown_remaining": max(0, self.cooldown - (time.time() - self.open_at)) if self.state == CircuitState.OPEN else 0,
        }


class LLMAPIPool:
    def __init__(self):
        self._instances: list[LLMInstance] = []
        self._lock = asyncio.Lock()
        self._init_from_config()

    def _init_from_config(self):
        keys = settings.LLM_API_KEYS
        if not keys or keys == [""]:
            logger.warning("No LLM API keys configured, using placeholder")
            return
        for key in keys:
            if key.strip():
                self._instances.append(
                    LLMInstance(
                        api_key=key.strip(),
                        base_url=settings.LLM_BASE_URL,
                        model=settings.LLM_MODEL,
                    )
                )
        logger.info(f"LLM API pool initialized with {len(self._instances)} key(s)")

    async def get_healthy_instances(self) -> list[LLMInstance]:
        results = []
        for inst in self._instances:
            if await inst.allow_request():
                results.append(inst)
        return results

    @property
    def is_degraded(self) -> bool:
        """所有实例都熔断了"""
        return all(
            inst.state == CircuitState.OPEN and
            time.time() - inst.open_at < inst.cooldown
            for inst in self._instances
        )

    def degradation_message(self) -> str:
        wait_times = [
            max(0, inst.cooldown - (time.time() - inst.open_at))
            for inst in self._instances
            if inst.state == CircuitState.OPEN
        ]
        if not wait_times:
            return "服务暂时不可用，请稍后重试"
        min_wait = int(min(wait_times))
        return f"服务繁忙，预计 {min_wait}s 后恢复，请稍后再试"

    def stats(self) -> list[dict]:
        return [i.to_dict() for i in self._instances]


llm_pool = LLMAPIPool()

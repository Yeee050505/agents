from __future__ import annotations
import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from app.config import settings


SENSITIVE_PATTERN = re.compile(
    "|".join(re.escape(w) for w in settings.SENSITIVE_WORDS),
    re.IGNORECASE,
) if settings.SENSITIVE_WORDS else None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=settings.MAX_TEXT_LENGTH)
    session_id: Optional[str] = None
    user_id: Optional[str] = None

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        v = v.strip()
        if SENSITIVE_PATTERN:
            found = SENSITIVE_PATTERN.search(v)
            if found:
                raise ValueError("消息包含敏感词汇，请修改后重试")
        return v


class TokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)

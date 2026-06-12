from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


class APIResponse(BaseModel):
    code: int = 200
    msg: str = "ok"
    data: Any = None
    request_id: Optional[str] = None


def success(data: Any = None, msg: str = "ok", request_id: Optional[str] = None) -> dict:
    return APIResponse(code=200, msg=msg, data=data, request_id=request_id).model_dump()


def error(code: int = 400, msg: str = "error", request_id: Optional[str] = None) -> dict:
    return APIResponse(code=code, msg=msg, request_id=request_id).model_dump()

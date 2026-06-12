from __future__ import annotations
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Request

from app.middleware.rate_limiter import apply_rate_limit, rate_limiter
from app.auth.jwt import create_access_token, get_current_user, require_user
from app.auth.blacklist import blacklist
from app.models.request import ChatRequest, RegisterRequest
from app.models.response import success, error
from app.services.agent import run_agent
from app.services.llm_pool import llm_pool
from app.services.history import clear_history
from app.services.cache import cache
from app.mcp import mcp_registry
from app.utils.logger import logger

router = APIRouter()


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user_id: str | None = Depends(get_current_user),
):
    apply_rate_limit(user_id)

    session_id = req.session_id or str(uuid.uuid4())
    uid = req.user_id or user_id or "anonymous"
    request_id = getattr(request.state, "request_id", "-")

    logger.info(
        f"Chat request: intent detection starting",
        extra={"request_id": request_id, "user_id": uid, "session_id": session_id},
    )

    result = await run_agent(
        message=req.message,
        user_id=uid,
        session_id=session_id,
        request_id=request_id,
    )

    return success(
        data={
            "answer": result["answer"],
            "intent": result["intent"],
            "session_id": result["session_id"],
            "loop_count": result["loop_count"],
        },
        request_id=request_id,
    )


@router.post("/auth/login")
async def login(req: RegisterRequest):
    from app.database.models import SessionLocal, User
    import hashlib
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == req.user_id).first()
        if not user:
            return error(code=401, msg="用户不存在")
        pw_hash = hashlib.sha256(req.password.encode()).hexdigest()
        if user.password_hash != pw_hash:
            return error(code=401, msg="密码错误")
        token = create_access_token(user_id=req.user_id)
        return success(data={"token": token, "user_id": req.user_id})
    finally:
        db.close()


@router.post("/auth/register")
async def register(req: RegisterRequest):
    from app.database.models import SessionLocal, User
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.user_id == req.user_id).first()
        if existing:
            return error(code=409, msg="用户已存在")
        import hashlib
        user = User(
            user_id=req.user_id,
            password_hash=hashlib.sha256(req.password.encode()).hexdigest(),
        )
        db.add(user)
        db.commit()
        token = create_access_token(user_id=req.user_id)
        return success(data={"token": token, "user_id": req.user_id})
    finally:
        db.close()


@router.post("/auth/blacklist")
async def blacklist_user(
    req: RegisterRequest,
    _=Depends(require_user),
):
    blacklist.add(req.user_id)
    return success(msg=f"用户 {req.user_id} 已加入黑名单")


@router.get("/rate-limit/stats")
async def rate_limit_stats(request: Request):
    user_id = getattr(request.state, "user_id", None)
    global_stats = rate_limiter.get_global_stats()
    user_stats = rate_limiter.get_user_stats(user_id) if user_id else None
    pool_stats = llm_pool.stats()
    return success(data={"global": global_stats, "user": user_stats, "llm_pool": pool_stats})


@router.get("/health")
async def health():
    return success(data={"status": "running"})


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    await clear_history(session_id)
    return success(msg=f"会话 {session_id} 已清空")


# ====== MCP 工具端点 ======

@router.get("/mcp/tools")
async def mcp_list_tools():
    tools = mcp_registry.list_tools()
    return success(data=[{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in tools])


@router.post("/mcp/tools/{tool_name}")
async def mcp_call_tool(tool_name: str, body: dict):
    result = await mcp_registry.call_tool(tool_name, body.get("arguments", {}))
    return success(data={"result": result})

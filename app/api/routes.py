from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Request, UploadFile, HTTPException
from fastapi.responses import StreamingResponse

from app.middleware.rate_limiter import apply_rate_limit, rate_limiter
from app.auth.jwt import create_access_token, get_current_user, require_user
from app.auth.blacklist import blacklist
from app.models.request import ChatRequest, RegisterRequest
from app.models.response import success, error
from app.services.agent import run_agent, run_agent_stream
from app.services.llm_pool import llm_pool
from app.services.history import clear_history
from app.services.cache import cache
from app.mcp import mcp_registry
from app.rag import rag_engine
from app.services.llm_cache import llm_cache

try:
    from app.lora import trainer as lora_trainer
    from app.models.request import LoRATrainRequest, LoRAInferRequest

    LORA_AVAILABLE = True
except Exception:
    LORA_AVAILABLE = False
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


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    user_id: str | None = Depends(get_current_user),
):
    apply_rate_limit(user_id)

    session_id = req.session_id or str(uuid.uuid4())
    uid = req.user_id or user_id or "anonymous"
    request_id = getattr(request.state, "request_id", "-")

    logger.info("Chat stream request", extra={"request_id": request_id, "user_id": uid, "session_id": session_id})

    async def event_stream():
        async for event in run_agent_stream(
            message=req.message,
            user_id=uid,
            session_id=session_id,
            request_id=request_id,
        ):
            if "token" in event:
                yield f"data: {json.dumps({'token': event['token']})}\n\n"
            else:
                yield f"data: {json.dumps({'intent': event.get('intent'), 'session_id': event.get('session_id'), 'loop_count': event.get('loop_count', 0)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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


# ====== 知识库端点 ======

from app.rag import UPLOAD_DIR

@router.post("/kb/upload")
async def kb_upload(file: UploadFile):
    if not file.filename:
        raise HTTPException(400, "No file")
    ext = Path(file.filename).suffix.lower()
    if ext not in (".txt", ".md", ".pdf"):
        raise HTTPException(400, f"Unsupported file type: {ext}")

    save_path = UPLOAD_DIR / file.filename
    content = await file.read()
    save_path.write_bytes(content)

    try:
        meta = await rag_engine.add_document(str(save_path))
        return success(data=meta, msg=f"文档「{file.filename}」已导入")
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, str(e))

@router.get("/kb/documents")
async def kb_list():
    docs = rag_engine.list_documents()
    return success(data=docs)

@router.delete("/kb/documents/{doc_id}")
async def kb_delete(doc_id: str):
    ok = await rag_engine.delete_document(doc_id)
    if not ok:
        raise HTTPException(404, "Document not found")
    return success(msg="文档已删除")


# ─── LoRA ───


@router.get("/lora/status")
async def lora_status():
    if not LORA_AVAILABLE:
        return success(data={"available": False, "device": "", "error": "LoRA dependencies not installed"})
    return success(
        data={
            "available": True,
            "device": lora_trainer.device,
            "base_model": lora_trainer.base_model,
            "adapters": lora_trainer.adapter_manager.list_adapters(),
        }
    )


@router.get("/lora/adapters")
async def lora_list_adapters():
    if not LORA_AVAILABLE:
        raise HTTPException(503, "LoRA not available")
    return success(data=lora_trainer.adapter_manager.list_adapters())


@router.post("/lora/train")
async def lora_train(req: LoRATrainRequest):
    if not LORA_AVAILABLE:
        raise HTTPException(503, "LoRA not available")
    try:
        result = lora_trainer.train(
            dataset=req.dataset,
            adapter_name=req.adapter_name,
            base_model=req.base_model,
            num_epochs=req.num_epochs,
            learning_rate=req.learning_rate,
            r=req.r,
        )
        return success(data=result, msg=f"Adapter「{req.adapter_name}」训练完成")
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/lora/infer")
async def lora_infer(req: LoRAInferRequest):
    if not LORA_AVAILABLE:
        raise HTTPException(503, "LoRA not available")
    try:
        output = lora_trainer.infer(adapter_name=req.adapter_name, text=req.text, max_length=req.max_length)
        return success(data={"adapter_name": req.adapter_name, "output": output, "input": req.text})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/lora/unload")
async def lora_unload():
    if not LORA_AVAILABLE:
        raise HTTPException(503, "LoRA not available")
    lora_trainer.unload()
    return success(msg="Model unloaded")


@router.post("/bench/echo")
async def bench_echo(body: dict):
    return {"ok": True, "echo": body.get("message", "")}


@router.get("/llm-cache/stats")
async def cache_stats():
    return llm_cache.stats()

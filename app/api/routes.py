from __future__ import annotations
import json
import uuid
import tempfile
from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File, Query
from fastapi.responses import StreamingResponse, JSONResponse

from app.agents import orchestrator
from app.mcp import mcp_registry
from app.quality import quality_tracker
from app.rag import rag_engine
from app.utils.logger import logger
from app.services.llm_pool import llm_pool

router = APIRouter()


def _ok(data=None, msg: str = "ok"):
    r = {"code": 200, "msg": msg}
    if data is not None:
        r["data"] = data
    return r


def _err(code: int, msg: str):
    return JSONResponse(status_code=code, content={"code": code, "msg": msg})


# ========== Chat ==========

@router.post("/chat")
async def chat(request: Request, body: dict):
    message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))
    request_id = getattr(request.state, "request_id", "-")
    logger.info("Chat request", extra={"request_id": request_id, "session_id": session_id})
    answer = await orchestrator.run(question=message, session_id=session_id, request_id=request_id)
    return _ok({"answer": answer, "session_id": session_id})


@router.post("/chat/stream")
async def chat_stream(request: Request, body: dict):
    message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))
    request_id = getattr(request.state, "request_id", "-")
    logger.info("Chat stream request", extra={"request_id": request_id, "session_id": session_id})

    async def event_stream():
        answer = await orchestrator.run(question=message, session_id=session_id, request_id=request_id)
        for chunk in [answer[i:i+10] for i in range(0, len(answer), 10)]:
            yield f"data: {json.dumps({'token': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat/flow")
async def chat_flow(request: Request, body: dict):
    message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))
    request_id = getattr(request.state, "request_id", "-")
    logger.info("Chat flow stream", extra={"request_id": request_id, "session_id": session_id})

    async def event_stream():
        async for event in orchestrator.run_stream(question=message, session_id=session_id, request_id=request_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ========== Health & MCP ==========

@router.get("/health")
async def health():
    return _ok({"status": "running"})


@router.get("/mcp/tools")
async def mcp_list_tools():
    tools = mcp_registry.list_tools()
    return _ok([{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in tools])


# ========== Quality ==========

@router.get("/quality/stats")
async def quality_stats():
    return _ok(quality_tracker.compute_stats())


@router.get("/quality/records")
async def quality_records(limit: int = 50, offset: int = 0):
    records = quality_tracker.read_records(limit=limit, offset=offset)
    return _ok({"records": records, "total": len(records)})


# ========== Knowledge Base (RAG) ==========

@router.post("/rag/upload")
async def rag_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".txt", ".md", ".pdf"):
        return _err(400, f"不支持的文件类型: {suffix}，仅支持 txt/md/pdf")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.close()
        meta = await rag_engine.add_document(tmp.name)
        return _ok(meta)
    except Exception as e:
        return _err(500, f"上传失败: {e}")
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@router.get("/rag/documents")
async def rag_list_documents():
    docs = rag_engine.list_documents()
    return _ok({"documents": docs, "total": len(docs)})


@router.get("/rag/documents/{doc_id}")
async def rag_get_document(doc_id: str):
    doc = rag_engine.get_document(doc_id)
    if not doc:
        return _err(404, "文档不存在")
    return _ok(doc)


@router.delete("/rag/documents/{doc_id}")
async def rag_delete_document(doc_id: str):
    ok = rag_engine.delete_document(doc_id)
    if not ok:
        return _err(404, "文档不存在或已删除")
    return _ok(msg="删除成功")


@router.get("/rag/search")
async def rag_search(q: str = Query(..., description="搜索关键词"), k: int = Query(5, description="返回数量")):
    hits = rag_engine.search(q, k=k)
    return _ok({"query": q, "results": hits, "total": len(hits)})


@router.post("/rag/rebuild")
async def rag_rebuild():
    result = rag_engine.rebuild_index()
    return _ok(result)


@router.get("/rag/stats")
async def rag_stats():
    return _ok(rag_engine.stats())


# ========== Frontend compat aliases (KB = RAG) ==========

@router.get("/kb/documents")
async def kb_list_documents():
    docs = rag_engine.list_documents()
    items = []
    for d in docs:
        items.append({
            "doc_id": d["doc_id"],
            "file_name": d["file_name"],
            "chunks": d["chunks"],
            "total_chars": d.get("char_count", 0),
        })
    return _ok(items)


@router.delete("/kb/documents/{doc_id}")
async def kb_delete_document(doc_id: str):
    ok = rag_engine.delete_document(doc_id)
    if not ok:
        return _err(404, "文档不存在或已删除")
    return _ok(msg="删除成功")


@router.post("/kb/upload")
async def kb_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".txt", ".md", ".pdf"):
        return _err(400, f"不支持的文件类型: {suffix}，仅支持 txt/md/pdf")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.close()
        meta = await rag_engine.add_document(tmp.name)
        return _ok(meta)
    except Exception as e:
        return _err(500, f"上传失败: {e}")
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# ========== Rate limit stats ==========

@router.get("/rate-limit/stats")
async def rate_limit_stats():
    pool_status = []
    for i, st in enumerate(llm_pool.stats()):
        pool_status.append({
            "key_index": i,
            "state": st.get("state", "closed"),
            "fail_count": st.get("failures", 0),
            "cooldown_until": st.get("cooldown_remaining", 0),
        })
    return _ok({
        "global": {"tokens": 99999999, "capacity": 99999999},
        "user": None,
        "llm_pool": pool_status,
    })


# ========== Session ==========

@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    from app.memory import short_memory
    short_memory.clear(session_id)
    return _ok(msg="会话已清除")


# ========== Auth stubs ==========

@router.post("/auth/login")
async def auth_login(body: dict):
    user_id = body.get("user_id", "")
    return _ok({"token": f"token-{user_id}", "user_id": user_id})


@router.post("/auth/register")
async def auth_register(body: dict):
    user_id = body.get("user_id", "")
    return _ok({"token": f"token-{user_id}", "user_id": user_id})


# ========== LoRA stubs (removed) ==========

@router.get("/lora/status")
async def lora_status():
    return _ok({"available": False, "device": "cpu", "base_model": "", "adapters": {}})


@router.get("/lora/adapters")
async def lora_adapters():
    return _ok({})

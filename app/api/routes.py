from __future__ import annotations
import json
import uuid
import tempfile
from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File, Query, Form
from fastapi.responses import StreamingResponse

from app.agents import orchestrator
from app.config import settings
from app.mcp import mcp_registry
from app.quality import quality_tracker
from app.rag import rag_engine
from app.utils.logger import logger

router = APIRouter()

# ========== Chat ==========

@router.post("/chat")
async def chat(request: Request, body: dict):
    message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))
    request_id = getattr(request.state, "request_id", "-")
    logger.info("Chat request", extra={"request_id": request_id, "session_id": session_id})
    answer = await orchestrator.run(question=message, session_id=session_id, request_id=request_id)
    return {
        "code": 200,
        "data": {"answer": answer, "session_id": session_id},
        "request_id": request_id,
    }


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
    return {"code": 200, "data": {"status": "running"}}


@router.get("/mcp/tools")
async def mcp_list_tools():
    tools = mcp_registry.list_tools()
    return {"code": 200, "data": [{"name": t.name, "description": t.description} for t in tools]}

# ========== Quality ==========

@router.get("/quality/stats")
async def quality_stats():
    return {"code": 200, "data": quality_tracker.compute_stats()}


@router.get("/quality/records")
async def quality_records(limit: int = 50, offset: int = 0):
    records = quality_tracker.read_records(limit=limit, offset=offset)
    return {"code": 200, "data": {"records": records, "total": len(records)}}

# ========== Knowledge Base (RAG) ==========

@router.post("/rag/upload")
async def rag_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".txt", ".md", ".pdf"):
        return {"code": 400, "message": f"不支持的文件类型: {suffix}，仅支持 txt/md/pdf"}
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        content = await file.read()
        tmp.write(content)
        tmp.close()
        meta = await rag_engine.add_document(tmp.name)
        return {"code": 200, "data": meta}
    except Exception as e:
        return {"code": 500, "message": f"上传失败: {e}"}
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@router.get("/rag/documents")
async def rag_list_documents():
    docs = rag_engine.list_documents()
    return {"code": 200, "data": {"documents": docs, "total": len(docs)}}


@router.get("/rag/documents/{doc_id}")
async def rag_get_document(doc_id: str):
    doc = rag_engine.get_document(doc_id)
    if not doc:
        return {"code": 404, "message": "文档不存在"}
    return {"code": 200, "data": doc}


@router.delete("/rag/documents/{doc_id}")
async def rag_delete_document(doc_id: str):
    ok = rag_engine.delete_document(doc_id)
    if not ok:
        return {"code": 404, "message": "文档不存在或已删除"}
    return {"code": 200, "message": "删除成功"}


@router.get("/rag/search")
async def rag_search(q: str = Query(..., description="搜索关键词"), k: int = Query(5, description="返回数量")):
    hits = rag_engine.search(q, k=k)
    return {"code": 200, "data": {"query": q, "results": hits, "total": len(hits)}}


@router.post("/rag/rebuild")
async def rag_rebuild():
    result = rag_engine.rebuild_index()
    return {"code": 200, "data": result}


@router.get("/rag/stats")
async def rag_stats():
    return {"code": 200, "data": rag_engine.stats()}

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
from app.memory.short_term import short_memory
from app.memory.long_term import long_memory as long_term_memory
from app.config import settings

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
    human_review = body.get("human_review", False)
    logger.info("Chat flow stream", extra={"request_id": request_id, "session_id": session_id})

    async def event_stream():
        async for event in orchestrator.run_stream(question=message, session_id=session_id, request_id=request_id, human_review=human_review):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ========== Health & MCP ==========

@router.get("/health")
async def health():
    return _ok({"status": "running"})


@router.get("/system/self-check")
async def self_check():
    results = []
    all_pass = True

    # 1. LLM Pool
    pool_stats = llm_pool.stats()
    llm_total = len(pool_stats)
    llm_closed = sum(1 for s in pool_stats if s["state"] == "closed")
    llm_open = sum(1 for s in pool_stats if s["state"] == "open")
    llm_ok = llm_closed > 0
    all_pass = all_pass and llm_ok
    results.append({
        "name": "LLM API 密钥池",
        "status": "[OK]" if llm_ok else "[FAIL]",
        "detail": f"共{llm_total}密钥, {llm_closed}可用, {llm_open}熔断",
    })

    # 2. Knowledge Base
    try:
        kb_stats = rag_engine.stats()
        chunk_count = kb_stats["chunks"]
        doc_count = kb_stats["documents"]
        char_count = kb_stats["total_chars"]
        kb_ok = chunk_count > 0
        all_pass = all_pass and kb_ok
        results.append({
            "name": "知识库 (KB)",
            "status": "[OK]" if kb_ok else "[FAIL]",
            "detail": f"{doc_count}文档 / {chunk_count}分块 / {char_count}字符",
        })
    except Exception as e:
        all_pass = False
        results.append({"name": "知识库 (KB)", "status": "[FAIL]", "detail": str(e)})

    # 3. BM25 索引缓存
    try:
        from app.rag import _bm25, _get_bm25
        if _bm25 is None:
            _get_bm25(rag_engine._chunks)
        all_pass = all_pass and True
        results.append({
            "name": "BM25 检索索引",
            "status": "[OK]",
            "detail": f"缓存就绪，{len(rag_engine._chunks)} 个分块",
        })
    except Exception as e:
        all_pass = False
        results.append({"name": "BM25 检索索引", "status": "[FAIL]", "detail": str(e)})

    # 4. Long-Term Memory
    try:
        ltm = long_term_memory
        memory_count = len(ltm._memories)
        embedder_ok = ltm._embedder is not None
        ltm_ok = memory_count >= 0
        all_pass = all_pass and ltm_ok
        results.append({
            "name": "长时记忆 (BGE)",
            "status": "[OK]" if ltm_ok else "[FAIL]",
            "detail": f"{'模型已加载' if embedder_ok else '模型未加载（惰性加载）'}, {memory_count}条记忆",
        })
    except Exception as e:
        all_pass = False
        results.append({"name": "长时记忆 (BGE)", "status": "[FAIL]", "detail": str(e)})

    # 5. Short-Term Memory
    stm_sessions = len(short_memory._sessions) if hasattr(short_memory, "_sessions") else 0
    results.append({
        "name": "短时记忆 (会话)",
        "status": "[OK]",
        "detail": f"{stm_sessions}活跃会话",
    })

    # 6. MCP 工具注册
    try:
        tools = mcp_registry.list_tools()
        tool_names = [t.name for t in tools]
        tools_ok = len(tools) > 0
        all_pass = all_pass and tools_ok
        results.append({
            "name": "MCP 工具注册",
            "status": "[OK]" if tools_ok else "[FAIL]",
            "detail": f"{len(tools)}个: {', '.join(tool_names)}",
        })
    except Exception as e:
        all_pass = False
        results.append({"name": "MCP 工具注册", "status": "[FAIL]", "detail": str(e)})

    # 7. Harness / Checkpoints
    try:
        from app.harness import list_checkpoints
        cps = list_checkpoints()
        cp_ok = len(cps) <= 10  # having too many old checkpoints is a warning
        results.append({
            "name": "Harness 检查点",
            "status": "[OK]",
            "detail": f"{len(cps)}个活跃检查点" if cps else "无活跃检查点",
        })
    except Exception as e:
        results.append({"name": "Harness 检查点", "status": "[FAIL]", "detail": str(e)})

    # 8. System Config
    results.append({
        "name": "系统配置",
        "status": "[OK]",
        "detail": f"模型={settings.LLM_MODEL}, 端点={settings.LLM_BASE_URL}, API密钥={llm_total}个",
    })

    return _ok({
        "pass": all_pass,
        "summary": "全部正常" if all_pass else "部分异常，请检查详情",
        "checks": results,
    })


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


# ========== Harness ==========

@router.get("/harness/checkpoints")
async def harness_checkpoints():
    from app.harness import list_checkpoints
    return _ok({"checkpoints": list_checkpoints()})


@router.get("/harness/checkpoints/recycle-bin")
async def harness_recycle_bin():
    from app.harness import list_recycle_bin
    return _ok({"items": list_recycle_bin()})


@router.get("/harness/checkpoints/{session_id}")
async def harness_session_checkpoints(session_id: str, include_deleted: bool = False):
    from app.harness import list_session_snapshots
    snaps = list_session_snapshots(session_id, include_deleted=include_deleted)
    if not snaps:
        return _err(404, "该会话无检查点")
    return _ok({"session_id": session_id, "snapshots": snaps})


@router.post("/harness/checkpoints/{session_id}/rollback")
async def harness_rollback(session_id: str, body: dict):
    from app.harness import load_checkpoint
    phase = body.get("phase", 0)
    state = load_checkpoint(session_id, phase=phase)
    if not state:
        return _err(404, f"阶段 {phase} 的检查点不存在")
    return _ok({
        "session_id": session_id,
        "phase": phase,
        "state": {k: v for k, v in state.items() if k not in ("events", "retrieved", "tool_results")},
    })


@router.post("/harness/checkpoints/{session_id}/save")
async def harness_save_checkpoint(session_id: str, body: dict = {}):
    from app.harness import save_checkpoint
    from app.memory.short_term import short_memory
    from app.memory.long_term import long_memory
    history = short_memory.get_history(session_id)
    memories = long_memory.retrieve(session_id)
    last_question = ""
    last_answer = ""
    if history:
        for m in reversed(history):
            if m["role"] == "user":
                last_question = m["content"]
                break
        for m in reversed(history):
            if m["role"] == "assistant":
                last_answer = m["content"]
                break
    ctx_parts = []
    if memories:
        ctx_parts.append("[用户长期记忆]\n" + "\n".join(memories))
    if history:
        recent = history[-6:]
        lines = [f"{'用户' if m['role']=='user' else '助手'}: {m['content'][:200]}" for m in recent]
        ctx_parts.append("[对话历史]\n" + "\n".join(lines))
    state = {
        "question": last_question,
        "session_id": session_id,
        "request_id": f"manual_{session_id}",
        "sub_queries": [last_question] if last_question else [],
        "retrieved": [],
        "tool_results": [],
        "context_ctx": "\n\n".join(ctx_parts),
        "draft": last_answer,
        "feedback": "",
        "attempt": 0,
        "validation_ok": True,
        "validation_issues": [],
        "events": [],
        "human_review": False,
        "_paused": False,
        "_phase": 5,
    }
    tags = body.get("tags", [])
    bind_node_id = body.get("bind_node_id", "")
    save_checkpoint(state, tags=tags, bind_node_id=bind_node_id)
    return _ok({"session_id": session_id, "phase": 5, "question": last_question[:60]})


@router.post("/harness/checkpoints/{session_id}/restore")
async def harness_restore_checkpoint(session_id: str, body: dict):
    from app.harness import load_checkpoint
    phase = body.get("phase")
    state = load_checkpoint(session_id, phase=phase)
    if not state:
        return _err(404, "检查点不存在")
    return _ok({
        "session_id": session_id,
        "phase": state.get("_phase", phase or 0),
        "question": state.get("question", ""),
        "draft": state.get("draft", ""),
        "context_ctx": state.get("context_ctx", ""),
    })


@router.patch("/harness/checkpoints/{session_id}/{phase}")
async def harness_update_metadata(session_id: str, phase: int, body: dict):
    from app.harness import update_checkpoint_metadata
    ok = update_checkpoint_metadata(session_id, phase,
                                     tags=body.get("tags"),
                                     bind_node_id=body.get("bind_node_id"))
    if not ok:
        return _err(404, "检查点不存在")
    return _ok(msg=f"阶段 {phase} 元数据已更新")


@router.delete("/harness/checkpoints/{session_id}")
async def harness_delete_checkpoint(session_id: str, phase: int = Query(default=None),
                                    permanent: bool = Query(default=False)):
    from app.harness import delete_checkpoint, restore_checkpoint
    if permanent:
        delete_checkpoint(session_id, phase=phase, permanent=True)
        label = f"阶段 {phase}" if phase is not None else "全部"
        return _ok(msg=f"{label} 检查点已永久删除")
    if phase is not None:
        delete_checkpoint(session_id, phase=phase)
        return _ok(msg=f"阶段 {phase} 检查点已移入回收站")
    delete_checkpoint(session_id)
    return _ok(msg=f"会话 {session_id} 全部检查点已移入回收站")


@router.post("/harness/checkpoints/{session_id}/{phase}/restore")
async def harness_restore_from_bin(session_id: str, phase: int):
    from app.harness import restore_checkpoint
    ok = restore_checkpoint(session_id, phase)
    if not ok:
        return _err(404, "该检查点不在回收站或不存")
    return _ok(msg=f"阶段 {phase} 检查点已恢复")


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


# ========== Human review resume ==========

@router.post("/chat/resume")
async def chat_resume(body: dict):
    from app.agents.orchestrator import signal_resume
    request_id = body.get("request_id", "")
    action = body.get("action", "continue")
    feedback = body.get("feedback", "")
    ok = signal_resume(request_id, action, feedback)
    if ok:
        return _ok(msg="已继续执行")
    return _err(404, "未找到对应的暂停会话或已超时")


# ========== Graph workflow (白盒流程图) ==========

WORKFLOW_GRAPH = {
    "nodes": [
        {"id": "planner", "label": "规划 Agent", "description": "问题拆解"},
        {"id": "retriever", "label": "检索 Agent", "description": "BM25 知识库"},
        {"id": "tool", "label": "工具 Agent", "description": "TapTap"},
        {"id": "summarizer", "label": "摘要 Agent", "description": "整合撰写"},
        {"id": "validator", "label": "校验 Agent", "description": "幻觉检测"},
    ],
    "edges": [
        {"from": "planner", "to": "retriever", "label": ""},
        {"from": "planner", "to": "tool", "label": "并行扇出"},
        {"from": "retriever", "to": "summarizer", "label": ""},
        {"from": "tool", "to": "summarizer", "label": ""},
        {"from": "summarizer", "to": "validator", "label": ""},
        {"from": "validator", "to": "summarizer", "label": "条件重写 ↺", "condition": "validation_ok=false"},
        {"from": "validator", "to": "__end__", "label": "输出", "condition": "validation_ok=true"},
    ],
}


@router.get("/graph/workflow")
async def graph_workflow():
    return _ok(WORKFLOW_GRAPH)


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

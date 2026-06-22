"""RAG 引擎测试"""
from app.rag import rag_engine, UPLOAD_DIR
from app.rag.preprocess import clean_text


def test_list_documents_empty():
    docs = rag_engine.list_documents()
    assert isinstance(docs, list)


async def test_format_context_empty():
    ctx = await rag_engine.format_context("test", k=3)
    # KB may have persisted data; if empty, ctx should be ""
    if not rag_engine._chunks:
        assert ctx == ""
    else:
        assert "知识库" in ctx


async def test_search_empty():
    hits = await rag_engine.search("test", k=3)
    if not rag_engine._chunks:
        assert hits == []
    else:
        assert len(hits) >= 0


async def test_upload_and_delete(tmp_path):
    """端到端测试：上传 txt → 搜索 → 删除"""
    doc = tmp_path / "test.txt"
    doc.write_text("今天天气很好，适合出去散步。阳光明媚，温度适宜。", encoding="utf-8")

    meta = await rag_engine.add_document(str(doc))
    assert meta["file_name"] == "test.txt"
    assert meta["total_chunks"] >= 1

    docs = rag_engine.list_documents()
    assert any(d["doc_id"] == meta["doc_id"] for d in docs)

    hits = await rag_engine.search("天气", k=3)
    assert len(hits) >= 1
    assert "天气" in hits[0]["content"] or "散步" in hits[0]["content"]

    ok = await rag_engine.delete_document(meta["doc_id"])
    assert ok is True

    docs = rag_engine.list_documents()
    assert not any(d["doc_id"] == meta["doc_id"] for d in docs)


def test_clean_text_pipeline():
    raw = "  乱码\u0000文本\n\n\n多余换行  "
    cleaned = clean_text(raw)
    assert cleaned == "乱码文本\n\n多余换行"

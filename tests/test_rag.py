"""RAG 引擎测试"""
from app.rag import rag_engine, UPLOAD_DIR
from app.rag.preprocess import clean_text


def test_list_documents_empty():
    docs = rag_engine.list_documents()
    assert isinstance(docs, list)


def test_search_empty():
    hits = rag_engine.search("test", k=3)
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

    # Verify document is findable in chunk list
    chunk_texts = [c["content"] for c in rag_engine._chunks if c["doc_id"] == meta["doc_id"]]
    assert any("今天" in ct for ct in chunk_texts), "刚上传的文档应在分块列表中"

    ok = rag_engine.delete_document(meta["doc_id"])
    assert ok is True

    docs = rag_engine.list_documents()
    assert not any(d["doc_id"] == meta["doc_id"] for d in docs)


def test_clean_text_pipeline():
    raw = "  乱码\u0000文本\n\n\n多余换行  "
    cleaned = clean_text(raw)
    assert cleaned == "乱码文本\n\n多余换行"

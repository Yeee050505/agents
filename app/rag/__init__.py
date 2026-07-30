from __future__ import annotations
import json
import uuid
import re
from pathlib import Path
from typing import List, Dict, Optional

from app.utils.logger import logger

DATA_DIR = Path(__file__).parent.parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
INDEX_FILE = DATA_DIR / "kb_index.json"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# BM25 全局缓存
_bm25 = None
_bm25_corpus_id = None


def _get_bm25(chunks: List[Dict]):
    global _bm25, _bm25_corpus_id
    cid = id(chunks)
    if _bm25 is not None and _bm25_corpus_id is cid:
        return _bm25
    from rank_bm25 import BM25Okapi
    import jieba
    texts = [c["content"] for c in chunks]
    tokenized = [list(jieba.cut(t)) for t in texts]
    _bm25 = BM25Okapi(tokenized)
    _bm25_corpus_id = cid
    return _bm25


def _invalidate_bm25():
    global _bm25, _bm25_corpus_id
    _bm25 = None
    _bm25_corpus_id = None


class RAGEngine:
    def __init__(self):
        self._chunks: List[Dict] = []
        self._documents: Dict[str, Dict] = {}
        self._load_index()

    def _load_index(self):
        if INDEX_FILE.exists():
            try:
                data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
                self._chunks = data.get("chunks", [])
                docs = {}
                for c in self._chunks:
                    did = c["doc_id"]
                    if did not in docs:
                        docs[did] = {"doc_id": did, "file_name": c["file_name"], "chunks": 0, "char_count": 0}
                    docs[did]["chunks"] += 1
                    docs[did]["char_count"] += len(c["content"])
                self._documents = docs
                logger.info(f"KB loaded: {len(self._chunks)} chunks from {len(docs)} docs")
            except Exception as e:
                logger.warning(f"KB index load failed: {e}")

    def _save_index(self):
        INDEX_FILE.write_text(
            json.dumps({"chunks": self._chunks}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _chunk_text(self, text: str, max_chunk: int = 800) -> List[str]:
        chunks = []
        sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            if len(sec) <= max_chunk:
                chunks.append(sec)
                continue
            paras = [p.strip() for p in sec.split("\n\n") if p.strip()]
            for para in paras:
                if not para:
                    continue
                if len(para) <= max_chunk:
                    chunks.append(para)
                    continue
                start = 0
                while start < len(para):
                    end = min(start + max_chunk, len(para))
                    if end < len(para):
                        nl = para.rfind("\n", start, end)
                        if nl > start + max_chunk // 2:
                            end = nl
                        else:
                            sent_end = max(
                                para.rfind("。", start, end),
                                para.rfind("！", start, end),
                                para.rfind("？", start, end),
                                para.rfind("\n", start, end),
                            )
                            if sent_end > start + max_chunk // 3:
                                end = sent_end + 1
                    chunks.append(para[start:end].strip())
                    start = end
        return chunks

    def _extract_text(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        if ext in (".txt", ".md"):
            return Path(file_path).read_text(encoding="utf-8", errors="replace")
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        raise ValueError(f"不支持的文件类型: {ext}")

    async def add_document(self, file_path: str) -> Dict:
        doc_id = str(uuid.uuid4())
        file_name = Path(file_path).name
        raw_text = self._extract_text(file_path)
        texts = self._chunk_text(raw_text)
        if not texts:
            raise ValueError("文档未提取到有效文本")

        meta = {"doc_id": doc_id, "file_name": file_name, "total_chunks": len(texts), "char_count": len(raw_text)}
        self._documents[doc_id] = {"doc_id": doc_id, "file_name": file_name, "chunks": len(texts), "char_count": len(raw_text)}

        for i, t in enumerate(texts):
            self._chunks.append({
                "doc_id": doc_id,
                "file_name": file_name,
                "chunk_idx": i,
                "content": t,
            })

        self._save_index()
        _invalidate_bm25()
        logger.info(f"Document added: {file_name} ({len(texts)} chunks, {len(raw_text)} chars)")
        return meta

    def search(self, query: str, k: int = 10) -> List[Dict]:
        if not self._chunks or not query.strip():
            return []
        import jieba
        bm25 = _get_bm25(self._chunks)
        tokenized_q = list(jieba.cut(query))
        scores = bm25.get_scores(tokenized_q)
        # Apply weights
        from app.quality.weight_manager import weight_manager
        weighted = []
        for i, score in enumerate(scores):
            w = weight_manager.get_weight(self._chunks[i]["doc_id"], self._chunks[i]["chunk_idx"])
            weighted.append((i, score * w))
        ranked = sorted(weighted, key=lambda x: x[1], reverse=True)
        top_k = min(k, len(ranked))
        hits = []
        for i, score in ranked[:top_k]:
            if score <= 0:
                continue
            c = self._chunks[i]
            hits.append({
                "content": c["content"][:800],
                "file_name": c["file_name"],
                "chunk_idx": c["chunk_idx"],
                "doc_id": c["doc_id"],
                "score": round(float(score), 4),
            })
        return hits

    def list_documents(self) -> List[Dict]:
        return sorted(self._documents.values(), key=lambda d: d["file_name"])

    def get_document(self, doc_id: str) -> Optional[Dict]:
        doc = self._documents.get(doc_id)
        if not doc:
            return None
        chunks = [c for c in self._chunks if c["doc_id"] == doc_id]
        return {**doc, "chunks_detail": chunks}

    def delete_document(self, doc_id: str) -> bool:
        before = len(self._chunks)
        self._chunks = [c for c in self._chunks if c["doc_id"] != doc_id]
        if len(self._chunks) == before:
            return False
        removed = before - len(self._chunks)
        self._documents.pop(doc_id, None)
        self._save_index()
        _invalidate_bm25()
        logger.info(f"Document deleted: {doc_id} ({removed} chunks)")
        return True

    def rebuild_index(self):
        self._save_index()
        _invalidate_bm25()
        _get_bm25(self._chunks)
        logger.info(f"Index rebuilt: {len(self._chunks)} chunks, {len(self._documents)} docs")
        return {"chunks": len(self._chunks), "documents": len(self._documents)}

    def stats(self) -> Dict:
        return {
            "documents": len(self._documents),
            "chunks": len(self._chunks),
            "total_chars": sum(len(c["content"]) for c in self._chunks),
        }


rag_engine = RAGEngine()

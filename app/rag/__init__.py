from __future__ import annotations
import json
import uuid
import re
import time
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np

from app.utils.logger import logger
from app.rag.preprocess import clean_text, clean_chunks
from app.rag.embedding import embed_service


DATA_DIR = Path(__file__).parent.parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
INDEX_FILE = DATA_DIR / "kb_index.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------- BM25 (lazy init) ----------
_bm25 = None
_bm25_corpus = None


def _get_bm25():
    global _bm25, _bm25_corpus
    from rank_bm25 import BM25Okapi
    import jieba

    # 如果 corpus 没变，复用已构建的 BM25
    corpus_id = id(rag_engine._chunks) if hasattr(rag_engine, "_chunks") else None
    if _bm25 is not None and _bm25_corpus is corpus_id:
        return _bm25
    texts = [c["content"] for c in rag_engine._chunks]
    tokenized = [list(jieba.cut(t)) for t in texts]
    _bm25 = BM25Okapi(tokenized)
    _bm25_corpus = corpus_id
    return _bm25


async def _rewrite_query(query: str) -> List[str]:
    """用 LLM 将用户 query 扩写成 2-3 个搜索方向"""
    from app.services.agent import _call_llm

    prompt = f"""用户搜索：{query}
请生成 2 个不同角度的搜索关键词用于知识库检索，每行一个，不要序号。"""
    try:
        result = await _call_llm("你是一个搜索关键词改写助手。", prompt, temperature=0.3)
        lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
        candidates = [query] + lines[:2]
        return candidates
    except Exception:
        return [query]


# -----------------------------------------------------------

class RAGEngine:
    def __init__(self):
        self._chunks: List[Dict] = []
        self._embeddings: List[List[float]] = []
        self._loaded = False
        self._load_index()

    # ---- persistence ----

    def _load_index(self):
        if INDEX_FILE.exists():
            try:
                data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
                self._chunks = data["chunks"]
                self._embeddings = data.get("embeddings", [])
                self._loaded = bool(self._embeddings)
                logger.info(f"KB loaded: {len(self._chunks)} chunks from {len(set(c['doc_id'] for c in self._chunks))} docs")
            except Exception as e:
                logger.warning(f"KB index load failed: {e}")

    def _save_index(self):
        INDEX_FILE.write_text(
            json.dumps({"chunks": self._chunks, "embeddings": self._embeddings}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # ---- chunking (按标题/段落分割，回退固定长度) ----

    def _chunk_text(self, text: str, max_chunk: int = 800) -> List[str]:
        chunks = []
        # 1. 按 Markdown 标题分割
        sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
        for sec in sections:
            sec = sec.strip()
            if not sec:
                continue
            if len(sec) <= max_chunk:
                chunks.append(sec)
                continue
            # 2. 长段落按双换行分割
            paras = [p.strip() for p in sec.split("\n\n") if p.strip()]
            for para in paras:
                if not para:
                    continue
                if len(para) <= max_chunk:
                    chunks.append(para)
                    continue
                # 3. 超长段落按边界截断（句号/问号/感叹号/换行）
                start = 0
                while start < len(para):
                    end = min(start + max_chunk, len(para))
                    if end < len(para):
                        nl = para.rfind("\n", start, end)
                        if nl > start + max_chunk // 2:
                            end = nl
                        else:
                            sentence_end = max(
                                para.rfind("。", start, end),
                                para.rfind("！", start, end),
                                para.rfind("？", start, end),
                                para.rfind("\n", start, end),
                            )
                            if sentence_end > start + max_chunk // 3:
                                end = sentence_end + 1
                    chunks.append(para[start:end].strip())
                    start = end
        return clean_chunks(chunks)

    def _extract_text(self, file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        if ext == ".txt":
            return Path(file_path).read_text(encoding="utf-8", errors="replace")
        elif ext == ".md":
            return Path(file_path).read_text(encoding="utf-8", errors="replace")
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        raise ValueError(f"Unsupported file type: {ext}")

    # ---- document ops ----

    async def add_document(self, file_path: str) -> Dict:
        doc_id = str(uuid.uuid4())
        file_name = Path(file_path).name
        raw_text = self._extract_text(file_path)
        texts = self._chunk_text(raw_text)

        if not texts:
            raise ValueError("No valid text chunks extracted from document")

        meta = {"doc_id": doc_id, "file_name": file_name, "total_chunks": len(texts), "char_count": len(raw_text)}

        for i, t in enumerate(texts):
            self._chunks.append({
                "doc_id": doc_id,
                "file_name": file_name,
                "chunk_idx": i,
                "content": t,
            })

        vecs = await embed_service.embed(texts, use_cache=False)

        self._embeddings.extend(vecs)
        self._loaded = True
        self._save_index()
        # BM25 缓存失效
        global _bm25, _bm25_corpus
        _bm25 = None
        _bm25_corpus = None
        logger.info(f"Document added: {file_name} ({len(texts)} chunks, {len(raw_text)} chars)")
        return meta

    async def search(self, query: str, k: int = 10) -> List[Dict]:
        if not self._chunks or not self._loaded:
            return []

        if not query.strip():
            return []

        # 1. Query 改写
        queries = await _rewrite_query(query)
        seen_scores: Dict[int, float] = {}

        for q in queries:
            q_vec = await embed_service.embed_one(q)

            arr = np.array(self._embeddings, dtype=np.float64)
            q_arr = np.array(q_vec, dtype=np.float64)

            vec_scores = (arr @ q_arr).tolist()

            # BM25 分数
            try:
                import jieba
                bm25 = _get_bm25()
                tokenized_q = list(jieba.cut(q))
                bm25_scores = bm25.get_scores(tokenized_q)
            except Exception:
                bm25_scores = [0.0] * len(self._chunks)

            # 融合: 0.6 向量 + 0.4 BM25（各自归一化到 0-1）
            for i in range(len(self._chunks)):
                vs = max(0.0, vec_scores[i])
                bs = float(bm25_scores[i])
                # BM25 归一化（sigmoid 压到 0-1）
                bs_norm = 1.0 / (1.0 + np.exp(-bs / 5.0)) if bs > 0 else 0.0
                fused = 0.6 * vs + 0.4 * bs_norm
                if i not in seen_scores or fused > seen_scores[i]:
                    seen_scores[i] = fused

        # 按融合分数排序取 top-k
        ranked = sorted(seen_scores.items(), key=lambda x: x[1], reverse=True)
        top_k = min(k, len(ranked))

        hits = []
        for i, score in ranked[:top_k]:
            hits.append({
                "content": self._chunks[i]["content"][:800],
                "file_name": self._chunks[i]["file_name"],
                "chunk_idx": self._chunks[i]["chunk_idx"],
                "score": round(float(score), 4),
            })
        return hits

    def list_documents(self) -> List[Dict]:
        seen: Dict[str, Dict] = {}
        for c in self._chunks:
            did = c["doc_id"]
            if did not in seen:
                seen[did] = {"doc_id": did, "file_name": c["file_name"], "chunks": 0}
            seen[did]["chunks"] += 1
        return sorted(seen.values(), key=lambda d: d["file_name"])

    async def delete_document(self, doc_id: str) -> bool:
        before = len(self._chunks)
        new_chunks = [c for c in self._chunks if c["doc_id"] != doc_id]
        if len(new_chunks) == before:
            return False
        removed = before - len(new_chunks)
        self._chunks = new_chunks
        self._embeddings = []
        self._loaded = False

        if self._chunks:
            texts = [c["content"] for c in self._chunks]
            vecs = await embed_service.embed(texts, use_cache=False)
            self._embeddings = vecs
            self._loaded = True

        self._save_index()
        global _bm25, _bm25_corpus
        _bm25 = None
        _bm25_corpus = None
        logger.info(f"Document deleted: {doc_id} ({removed} chunks)")
        return True

    async def format_context(self, query: str, k: int = 3) -> str:
        hits = await self.search(query, k=k)
        if not hits:
            return ""
        lines = ["以下是从知识库中检索到的相关内容："]
        for h in hits:
            lines.append(f"[来自「{h['file_name']}」] {h['content']}")
        return "\n\n".join(lines)


rag_engine = RAGEngine()

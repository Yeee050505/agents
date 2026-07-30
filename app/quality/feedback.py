from __future__ import annotations
import json
import time
import re
import uuid
from pathlib import Path
from typing import Optional
from app.utils.logger import logger
from app.services.llm_pool import llm_pool

FEEDBACK_DIR = Path(__file__).parent.parent.parent / "data" / "quality"
FEEDBACK_FILE = FEEDBACK_DIR / "feedback_log.jsonl"
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

TOXIC_PATTERNS = re.compile(
    r"(毛片|操你|fuck|shit|色情|赌博|毒品|枪支|炸药|杀人|自杀|反动|分裂)", re.IGNORECASE
)
PII_PATTERNS = re.compile(
    r"(1[3-9]\d{9}|\d{17}[\dXx]|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


class FeedbackRecord:
    def __init__(
        self,
        query: str,
        answer: str,
        score: int,
        error_points: str = "",
        correct_answer: str = "",
        request_id: str = "",
        session_id: str = "",
        user_id: str = "",
        ip: str = "",
    ):
        self.id = str(uuid.uuid4())[:12]
        self.query = query
        self.answer = answer
        self.score = score
        self.error_points = error_points
        self.correct_answer = correct_answer
        self.request_id = request_id
        self.session_id = session_id
        self.user_id = user_id
        self.ip = ip
        self.created_at = time.time()
        self.status = "pending"  # pending / filtered / ai_reviewed / human_reviewed / applied / rejected
        self.review_note = ""
        self.filter_reason = ""
        self.ai_review_result: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "query": self.query[:200],
            "answer": self.answer[:200],
            "score": self.score,
            "error_points": self.error_points[:500],
            "correct_answer": self.correct_answer[:500],
            "request_id": self.request_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "status": self.status,
            "review_note": self.review_note,
            "filter_reason": self.filter_reason,
        }


class FeedbackManager:
    MAX_RECORDS = 5000
    DEDUP_WINDOW = 3600  # 1 hour

    def __init__(self):
        self._records: list[FeedbackRecord] = []
        self._load()

    def _load(self):
        if FEEDBACK_FILE.exists():
            try:
                lines = FEEDBACK_FILE.read_text(encoding="utf-8").strip().split("\n")
                for line in lines:
                    if line.strip():
                        data = json.loads(line)
                        r = FeedbackRecord(
                            query=data.get("query", ""),
                            answer=data.get("answer", ""),
                            score=data.get("score", 3),
                            error_points=data.get("error_points", ""),
                            correct_answer=data.get("correct_answer", ""),
                        )
                        r.id = data.get("id", r.id)
                        r.created_at = data.get("created_at", r.created_at)
                        r.status = data.get("status", "pending")
                        r.filter_reason = data.get("filter_reason", "")
                        r.review_note = data.get("review_note", "")
                        self._records.append(r)
                logger.info(f"Feedback: loaded {len(self._records)} records")
            except Exception as e:
                logger.warning(f"Feedback load failed: {e}")

    def _save(self):
        with open(str(FEEDBACK_FILE), "w", encoding="utf-8") as f:
            for r in self._records[-self.MAX_RECORDS:]:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")

    def _check_toxic(self, text: str) -> bool:
        return bool(TOXIC_PATTERNS.search(text))

    def _check_pii(self, text: str) -> bool:
        return bool(PII_PATTERNS.search(text))

    def _check_duplicate(self, query: str) -> bool:
        now = time.time()
        for r in self._records:
            if r.query.strip().lower() == query.strip().lower() and (now - r.created_at) < self.DEDUP_WINDOW:
                return True
        return False

    async def submit(self, record: FeedbackRecord) -> dict:
        # Layer 1: Filter
        combined = f"{record.query} {record.error_points} {record.correct_answer}"
        if self._check_toxic(combined):
            record.status = "filtered"
            record.filter_reason = "toxic_content"
            self._records.append(record)
            self._save()
            return {"id": record.id, "status": "filtered", "reason": "包含敏感内容，已拦截"}

        if self._check_pii(combined):
            record.status = "filtered"
            record.filter_reason = "pii_detected"
            self._records.append(record)
            self._save()
            return {"id": record.id, "status": "filtered", "reason": "包含个人信息，已拦截"}

        if self._check_duplicate(record.query):
            record.status = "filtered"
            record.filter_reason = "duplicate"
            self._records.append(record)
            self._save()
            return {"id": record.id, "status": "filtered", "reason": "重复反馈，已记录"}

        if record.score == 3:
            record.status = "pending"
            record.filter_reason = "neutral"
            self._records.append(record)
            self._save()
            return {"id": record.id, "status": "logged", "reason": "中性反馈，仅记录日志"}

        if record.score >= 4:
            record.status = "applied"
            record.filter_reason = "positive"
            self._records.append(record)
            self._save()
            self._boost_weights(record)
            return {"id": record.id, "status": "applied", "reason": "正面反馈，已提升权重"}

        # Score 1-2: negative feedback, need error_points
        if not record.error_points.strip():
            record.status = "pending"
            record.filter_reason = "missing_details"
            self._records.append(record)
            self._save()
            return {"id": record.id, "status": "pending", "reason": "请补充具体错误点和正确答案"}

        # Layer 2: AI Pre-review
        record.status = "ai_reviewed"
        ai_result = await self._ai_review(record)
        record.ai_review_result = ai_result

        if ai_result.get("risk") == "high":
            record.status = "pending"
            record.review_note = ai_result.get("reason", "高风险内容，需人工审核")
            self._records.append(record)
            self._save()
            return {"id": record.id, "status": "pending", "reason": "已提交人工审核"}

        # Auto-apply for low-risk negative feedback
        record.status = "applied"
        record.review_note = ai_result.get("reason", "AI审核通过")
        self._records.append(record)
        self._save()
        await self._apply_fix(record)
        return {"id": record.id, "status": "applied", "reason": "已根据反馈修正知识库"}

    async def _ai_review(self, record: FeedbackRecord) -> dict:
        prompt = f"""你是一个反馈审核助手。判断以下用户反馈是否存在矛盾、违规或风险。

原始问题：{record.query}
原始回答：{record.answer}
用户评分：{record.score}/5
错误点：{record.error_points}
用户纠正：{record.correct_answer}

请输出 JSON：
{{"risk": "low"|"medium"|"high", "reason": "简要说明", "confidence": 0.0-1.0}}"""
        try:
            messages = [{"role": "user", "content": prompt}]
            text = await llm_pool.call(messages, temperature=0.1, max_tokens=200)
            text = text.strip().removeprefix("```json").removesuffix("```").strip()
            return json.loads(text)
        except Exception as e:
            logger.warning(f"AI review failed: {e}")
            return {"risk": "low", "reason": "AI审核异常，默认通过", "confidence": 0.5}

    def _boost_weights(self, record: FeedbackRecord):
        """Boost weights for positive feedback."""
        from app.quality.weight_manager import weight_manager
        chunks = weight_manager.find_chunks_by_query(record.query)
        for c in chunks:
            weight_manager.adjust_weight(c["doc_id"], c.get("chunk_idx", 0), delta=0.1)
        logger.info(f"Feedback: boosted weights for query '{record.query[:40]}' ({len(chunks)} chunks)")

    async def _apply_fix(self, record: FeedbackRecord):
        """Apply negative feedback correction."""
        from app.quality.weight_manager import weight_manager
        # Reduce weight of original chunks
        chunks = weight_manager.find_chunks_by_query(record.query)
        for c in chunks:
            weight_manager.adjust_weight(c["doc_id"], c.get("chunk_idx", 0), delta=-0.2)
        # Add correct answer as a new chunk if provided
        if record.correct_answer.strip():
            from app.rag import rag_engine
            from app.quality.whitelist import whitelist
            whitelist.add(
                question=record.query,
                answer=record.correct_answer,
                keywords=[record.query],
                source=f"feedback_{record.id}",
            )
            logger.info(f"Feedback: added whitelist entry for '{record.query[:40]}'")

    def list_records(self, limit: int = 50, offset: int = 0, status: str = "") -> list[dict]:
        filtered = [r for r in self._records if not status or r.status == status]
        total = len(filtered)
        start = max(0, total - offset - limit)
        end = total - offset
        return [r.to_dict() for r in filtered[start:end]][::-1]

    def get_record(self, record_id: str) -> Optional[dict]:
        for r in self._records:
            if r.id == record_id:
                return r.to_dict()
        return None

    async def review(self, record_id: str, action: str, note: str = "") -> bool:
        for r in self._records:
            if r.id == record_id:
                if action == "approve":
                    r.status = "applied"
                    r.review_note = note or "人工审核通过"
                    await self._apply_fix(r)
                elif action == "reject":
                    r.status = "rejected"
                    r.review_note = note or "人工驳回"
                else:
                    return False
                self._save()
                return True
        return False

    def stats(self) -> dict:
        total = len(self._records)
        by_status: dict[str, int] = {}
        for r in self._records:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        return {"total": total, "by_status": by_status}


feedback_manager = FeedbackManager()

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional
from app.utils.logger import logger

QUALITY_LOG_DIR = Path(__file__).parent.parent.parent / "data" / "quality"
QUALITY_LOG_DIR.mkdir(parents=True, exist_ok=True)
QUALITY_LOG_FILE = QUALITY_LOG_DIR / "query_log.jsonl"
QUALITY_STATS_FILE = QUALITY_LOG_DIR / "stats.json"


class QueryRecord:
    def __init__(
        self,
        query: str,
        intent: str,
        request_id: str = "",
        session_id: str = "",
    ):
        self.query = query
        self.intent = intent
        self.request_id = request_id
        self.session_id = session_id
        self.timestamp = time.time()
        self.tools_called: list[dict] = []
        self.rag_hits = 0
        self.sports_results = 0
        self.empty_count = 0
        self.loop_count = 0
        self.final_answer = ""
        self.answer_length = 0
        self.latency_ms = 0
        self.quality_score: Optional[float] = None
        self.failure_reason: Optional[str] = None
        self.stale_count = 0

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "intent": self.intent,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "tools_called": self.tools_called,
            "rag_hits": self.rag_hits,
            "sports_results": self.sports_results,
            "empty_count": self.empty_count,
            "loop_count": self.loop_count,
            "final_answer": self.final_answer[:200],
            "answer_length": self.answer_length,
            "latency_ms": self.latency_ms,
            "quality_score": self.quality_score,
            "failure_reason": self.failure_reason,
            "stale_count": self.stale_count,
        }


class QualityTracker:
    MAX_RECORDS = 2000

    def __init__(self):
        self._current: Optional[QueryRecord] = None

    def begin(
        self,
        query: str,
        intent: str,
        request_id: str = "",
        session_id: str = "",
    ) -> "QualityTracker":
        self._current = QueryRecord(query, intent, request_id, session_id)
        self._current.timestamp = time.time()
        return self

    def record_tool_call(self, name: str, args: dict, result: str):
        if self._current is None:
            return
        preview = (result or "")[:100]
        self._current.tools_called.append({
            "name": name,
            "args": args,
            "result_empty": not bool(result) or "未找到" in str(result),
            "result_preview": preview,
        })
        if name == "rag_search":
            self._current.rag_hits = 1 if result and "未找到" not in str(result) else 0
        if name == "sports_search":
            self._current.sports_results = 1 if result and "未找到" not in str(result) else 0

    def record_stale(self):
        if self._current:
            self._current.stale_count += 1

    def record_empty(self):
        if self._current:
            self._current.empty_count += 1

    def skip(self):
        self._current = None

    def finish(self, answer: str, loop_count: int):
        if self._current is None:
            return
        record = self._current
        record.final_answer = answer
        record.answer_length = len(answer)
        record.loop_count = loop_count
        record.latency_ms = int((time.time() - record.timestamp) * 1000)
        record.failure_reason = self._classify_failure(record)
        self._save(record)
        self._current = None

    def _classify_failure(self, record: QueryRecord) -> Optional[str]:
        if record.stale_count > 0:
            return "stale_response"
        if record.empty_count >= 2:
            return "all_tools_empty"
        if len(record.final_answer) < 20:
            return "answer_too_short"
        if not record.final_answer:
            return "no_answer"
        return None

    def _save(self, record: QueryRecord):
        line = json.dumps(record.to_dict(), ensure_ascii=False)
        try:
            with open(str(QUALITY_LOG_FILE), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning(f"Quality log write failed: {e}")

    # ---- read / stats ----

    def read_records(self, limit: int = 100, offset: int = 0) -> list[dict]:
        if not QUALITY_LOG_FILE.exists():
            return []
        try:
            lines = QUALITY_LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
            total = len(lines)
            start = max(0, total - offset - limit)
            end = total - offset
            selected = lines[start:end] if start < end else []
            return [json.loads(l) for l in selected][::-1]
        except Exception:
            return []

    def compute_stats(self) -> dict:
        records = self.read_records(limit=2000)
        total = len(records)
        if total == 0:
            return {"total": 0}

        failures = [r for r in records if r.get("failure_reason")]
        tools_called = sum(len(r.get("tools_called", [])) for r in records)
        rag_hit_rate = sum(r.get("rag_hits", 0) for r in records) / max(total, 1)
        sports_hit_rate = sum(r.get("sports_results", 0) for r in records) / max(total, 1)
        avg_latency = sum(r.get("latency_ms", 0) for r in records) / max(total, 1)
        avg_loops = sum(r.get("loop_count", 0) for r in records) / max(total, 1)

        failure_counts: dict[str, int] = {}
        for r in failures:
            reason = r.get("failure_reason", "unknown")
            failure_counts[reason] = failure_counts.get(reason, 0) + 1

        stale_count = sum(1 for r in records if r.get("stale_count", 0) > 0)

        return {
            "total": total,
            "failures": len(failures),
            "failure_rate": round(len(failures) / max(total, 1) * 100, 1),
            "failure_details": failure_counts,
            "stale_response_count": stale_count,
            "rag_hit_rate": round(rag_hit_rate, 3),
            "sports_hit_rate": round(sports_hit_rate, 3),
            "avg_latency_ms": round(avg_latency, 0),
            "avg_loops": round(avg_loops, 1),
            "total_tools_called": tools_called,
        }


quality_tracker = QualityTracker()
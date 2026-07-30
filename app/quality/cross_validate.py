from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional
from app.utils.logger import logger

CONSISTENCY_FILE = Path(__file__).parent.parent.parent / "data" / "quality" / "consistency_log.jsonl"


class CrossValidator:
    def __init__(self):
        self._log: list[dict] = []

    def validate(self, query: str, bm25_results: list[dict], vector_results: list[dict] | None = None,
                 tool_results: list[dict] | None = None) -> dict:
        """Cross-validate between BM25 (keyword) and vector/tool channels."""
        bm25_texts = set(self._normalize(r.get("content", "")) for r in bm25_results)
        tool_texts = set()
        if tool_results:
            for r in tool_results:
                text = r.get("content", r.get("result", r.get("results", "")))
                tool_texts.add(self._normalize(str(text)[:200]))

        # Content from both BM25 and tool
        common = bm25_texts & tool_texts
        # Content only in one channel
        bm25_only = bm25_texts - tool_texts
        tool_only = tool_texts - bm25_texts

        bm25_score = bm25_results[0].get("score", 0) if bm25_results else 0

        flags = []
        if common:
            flags.append("cross_validated")
        if bm25_only and len(bm25_only) > len(common):
            flags.append("bm25_only")
        if tool_only and len(tool_only) > len(common):
            flags.append("tool_only")

        result = {
            "query": query[:100],
            "bm25_hits": len(bm25_results),
            "tool_hits": len(tool_results or []),
            "common_phrases": len(common),
            "bm25_only_phrases": len(bm25_only),
            "tool_only_phrases": len(tool_only),
            "flags": flags,
            "confidence": self._calc_confidence(bm25_score, len(common), len(bm25_only), len(tool_only)),
        }

        self._log_result(query, result)
        return result

    def _normalize(self, text: str) -> str:
        import re
        text = re.sub(r"[^\u4e00-\u9fff\w]", "", text)
        return text[:200]

    def _calc_confidence(self, bm25_score: float, common: int, bm25_only: int, tool_only: int) -> str:
        if common > 0 and bm25_score > 1.0:
            return "high"
        if common > 0:
            return "medium"
        if bm25_only > 0 and tool_only > 0:
            return "medium"
        return "low"

    def _log_result(self, query: str, result: dict):
        entry = {"timestamp": time.time(), **result}
        CONSISTENCY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(str(CONSISTENCY_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def evaluate_draft(self, draft: str, bm25_results: list[dict], tool_results: list[dict] | None = None) -> list[dict]:
        """Extract claims from draft and check against each channel."""
        claims = self._extract_claims(draft)
        bm25_corpus = " ".join(r.get("content", "") for r in bm25_results)
        tool_corpus = " ".join(r.get("content", r.get("result", "")) for r in (tool_results or []))

        results = []
        for claim in claims:
            in_bm25 = claim in bm25_corpus
            in_tool = claim in tool_corpus
            results.append({
                "claim": claim,
                "in_bm25": in_bm25,
                "in_tool": in_tool,
                "status": "verified" if in_bm25 and in_tool else ("partial" if in_bm25 or in_tool else "unverified"),
            })
        return results

    def _extract_claims(self, text: str) -> list[str]:
        import re
        claims = []
        for match in re.finditer(r"[^。，；\n]{4,50}", text):
            claims.append(match.group().strip())
        return claims[:10]

    def stats(self) -> dict:
        total = 0
        flags_count: dict[str, int] = {}
        if CONSISTENCY_FILE.exists():
            try:
                for line in CONSISTENCY_FILE.read_text(encoding="utf-8").strip().split("\n"):
                    if line.strip():
                        data = json.loads(line)
                        total += 1
                        for f in data.get("flags", []):
                            flags_count[f] = flags_count.get(f, 0) + 1
            except Exception:
                pass
        return {"total_checks": total, "flag_distribution": flags_count}


cross_validator = CrossValidator()

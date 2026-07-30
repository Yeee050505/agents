from __future__ import annotations
import json
import re
import time
from typing import Optional
from app.utils.logger import logger


class FactExtractor:
    def __init__(self):
        self._patterns = {
            "price": re.compile(r"(\d+(?:\.\d+)?)\s*(元|美元|欧元|港币|日元)"),
            "rating": re.compile(r"(\d+(?:\.\d+)?)\s*(分|星|/10)"),
            "year": re.compile(r"(20\d{2})\s*年"),
            "percentage": re.compile(r"(\d+(?:\.\d+)?)\s*%"),
            "number": re.compile(r"(\d{3,})"),
            "name": re.compile(r"《([^》]+)》"),
            "english_name": re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"),
        }

    def extract(self, text: str) -> dict:
        facts = {}
        for label, pattern in self._patterns.items():
            matches = pattern.findall(text)
            if matches:
                facts[label] = list(set(matches))[:5]
        return facts

    def validate(self, draft: str, reference_texts: list[str]) -> list[dict]:
        """Check extracted facts against reference sources."""
        draft_facts = self.extract(draft)
        combined_ref = "\n".join(reference_texts)
        ref_facts = self.extract(combined_ref)

        issues = []
        for label, values in draft_facts.items():
            ref_values = ref_facts.get(label, [])
            for v in values:
                v_str = v if isinstance(v, str) else "".join(v)
                matched = False
                for rv in ref_values:
                    rv_str = rv if isinstance(rv, str) else "".join(rv)
                    if v_str in rv_str or rv_str in v_str:
                        matched = True
                        break
                if not matched:
                    issues.append({
                        "type": label,
                        "value": v_str,
                        "severity": "warning" if label in ("name", "english_name") else "error",
                        "message": f"草稿中的{label}「{v_str}」未在参考素材中找到对应",
                    })

        return issues

    def stats(self) -> dict:
        return {"patterns": list(self._patterns.keys())}


fact_extractor = FactExtractor()

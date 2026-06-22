from __future__ import annotations
import re


def clean_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"￼", "", text)
    return text.strip()


def clean_chunks(chunks: list[str]) -> list[str]:
    result = []
    for c in chunks:
        c = clean_text(c)
        if len(c) < 10:
            continue
        if re.match(r"^[\d\s\-—_*#•·・.。，,、/\\)(]+$", c):
            continue
        result.append(c)
    return result

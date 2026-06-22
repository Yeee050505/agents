from __future__ import annotations
import asyncio
import re
from typing import List, Optional
from urllib.parse import quote
from app.utils.logger import logger


async def search_web(query: str, max_results: int = 5) -> str:
    bing = asyncio.create_task(_search_bing(query, max_results))
    baidu = asyncio.create_task(_search_baidu(query, max_results))

    done, pending = await asyncio.wait(
        [bing, baidu],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in done:
        result = task.result()
        if result:
            for p in pending:
                p.cancel()
            return result

    for task in pending:
        result = await task
        if result:
            return result

    return ""


async def _search_bing(query: str, max_results: int = 5) -> str:
    try:
        import httpx
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        async with httpx.AsyncClient(timeout=5, headers=headers, follow_redirects=True) as client:
            resp = await client.get(f"https://www.bing.com/search?q={quote(query)}&mkt=zh-CN&count={max_results}")
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for item in soup.select("li.b_algo")[:max_results]:
                title_el = item.select_one("h2 a")
                body_el = item.select_one(".b_caption p")
                href = title_el.get("href", "") if title_el else ""
                title = title_el.get_text(strip=True) if title_el else ""
                body = body_el.get_text(strip=True) if body_el else ""
                if title:
                    results.append({"title": title, "body": body[:200], "href": href})
            if results:
                logger.info(f"Bing search: {len(results)} results for '{query[:30]}...'")
            return _format_results(results)
    except Exception as e:
        logger.warning(f"Bing search failed: {e}")
        return ""


async def _search_baidu(query: str, max_results: int = 5) -> str:
    try:
        import httpx
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0",
        }
        async with httpx.AsyncClient(timeout=5, headers=headers, follow_redirects=True) as client:
            resp = await client.get(f"https://www.baidu.com/s?wd={quote(query)}&rn={max_results}&ie=utf-8")
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for item in soup.select(".result, .c-container")[:max_results]:
                title_el = item.select_one("h3 a")
                body_el = item.select_one(".c-abstract, .c-span-last")
                href = title_el.get("href", "") if title_el else ""
                title = title_el.get_text(strip=True) if title_el else ""
                body = body_el.get_text(strip=True) if body_el else ""
                if title:
                    results.append({"title": title, "body": body[:200], "href": href})
            return _format_results(results)
    except Exception as e:
        logger.warning(f"Baidu search failed: {e}")
        return ""


def _format_results(results: list) -> str:
    if not results:
        return ""
    lines = []
    for i, r in enumerate(results, 1):
        body = (r.get("body") or "")[:200]
        href = r.get("href") or ""
        title = r.get("title") or ""
        lines.append(f"[{i}] {title}\n    {body}\n    {href}")
    return "\n\n".join(lines)


def needs_realtime_search(text: str) -> bool:
    keywords = [
        "热点", "实时", "最新", "新闻", "今天", "今日",
        "2025", "2026", "今年", "最近", "当前", "现在",
        "热搜", "榜单", "趋势", "火了", "热门", "六月",
        "发生什么", "刚发生的", "目前",
        "过去", "昨天", "前天", "上周", "本月", "近期",
        "前几天", "这周", "这个月",
    ]
    return any(kw in text for kw in keywords)


def is_stale_response(text: str) -> bool:
    stale_markers = [
        "知识截止", "无法获取", "无法实时", "实时信息",
        "截至", "我的知识", "训练数据", "无法提供当前",
        "无法提供最新", "启用联网搜索", "无法实时搜索",
        "无法提供", "暂不可用", "没有联网", "无法联网",
        "不支持实时", "请自行搜索", "无法搜索",
        "知识库有截止", "直接获取", "没有直接",
    ]
    return any(m in text for m in stale_markers)

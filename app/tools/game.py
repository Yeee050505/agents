from __future__ import annotations
import os
import time
import re
import asyncio
import httpx
from urllib.parse import quote
from collections import OrderedDict
from bs4 import BeautifulSoup
from app.utils.logger import logger

TAP_SEARCH = "https://www.taptap.cn/search/{query}?type=games"
TAP_APP = "https://www.taptap.cn/app/{app_id}"

TIMEOUT = int(os.getenv("TAP_API_TIMEOUT", "8"))
CACHE_TTL = 300
_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_CACHE_MAX = 64

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.taptap.cn/",
}

_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None:
        proxy = os.getenv("TAP_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None
        kwargs: dict = {
            "timeout": TIMEOUT,
            "limits": httpx.Limits(max_keepalive_connections=4, max_connections=8),
            "headers": dict(_BROWSER_HEADERS),
            "follow_redirects": True,
        }
        if proxy:
            kwargs["proxy"] = proxy
            logger.info(f"TapTap client using proxy: {proxy}")
        _shared_client = httpx.AsyncClient(**kwargs)
    return _shared_client


def _cache_get(key: str) -> str | None:
    if key not in _CACHE:
        return None
    ts, val = _CACHE[key]
    if time.time() - ts > CACHE_TTL:
        del _CACHE[key]
        return None
    _CACHE.move_to_end(key)
    return val


def _cache_set(key: str, val: str):
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.popitem(last=False)
    _CACHE[key] = (time.time(), val)


async def search_game(query: str) -> str:
    cached = _cache_get(query)
    if cached is not None:
        return cached

    result = await _tap_search(query)
    if not result:
        match = re.search(r"taptap_id[:\s]*(\d+)", query, re.IGNORECASE)
        if match:
            result = await _tap_app_detail(match.group(1))

    if result:
        _cache_set(query, result)
    return result


# ---------- TapTap 搜索 ----------

async def _tap_search(query: str) -> str:
    try:
        url = TAP_SEARCH.format(query=quote(query))
        client = _get_client()
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning(f"TapTap search returned {resp.status_code}")
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div[class*='search-card'], div[class*='card'], a[class*='search-item']")
        if not cards:
            cards = soup.select("a[href*='/app/']")

        for card in cards[:5]:
            link = card if card.name == "a" else card.find("a", href=re.compile(r"/app/\d+"))
            if not link:
                continue
            href = link.get("href", "")
            m = re.search(r"/app/(\d+)", href)
            if not m:
                continue
            app_id = m.group(1)
            result = await _tap_app_detail(app_id)
            if result:
                return result

        return ""
    except Exception as e:
        logger.warning(f"TapTap search failed: {e}")
        return ""


# ---------- TapTap 详情 ----------

async def _tap_app_detail(app_id: str) -> str:
    cache_key = f"detail:{app_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        url = TAP_APP.format(app_id=app_id)
        client = _get_client()
        resp = await client.get(url)
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        name = _text(soup, "h1") or _text(soup, "[class*='app-name']") or _text(soup, "[class*='game-name']") or ""
        rating = _text(soup, "[class*='rating']") or _text(soup, "[class*='score']") or ""
        desc = _text(soup, "[class*='description']") or _text(soup, "[class*='summary']") or ""
        tags = _text(soup, "[class*='tag']") or _text(soup, "[class*='genre']") or ""
        dev = _text(soup, "[class*='developer']") or _text(soup, "[class*='studio']") or ""
        price = _text(soup, "[class*='price']") or _text(soup, "[class*='pay']") or ""
        download = _text(soup, "[class*='download-count']") or _text(soup, "[class*='install-count']") or ""

        if not name:
            logger.warning(f"TapTap detail: no game name found for app/{app_id}")
            return ""

        lines = [f"[TapTap] {name}"]
        if price:
            lines.append(f"  价格: {price}")
        if rating:
            lines.append(f"  评分: {rating}")
        if tags:
            lines.append(f"  类型: {tags}")
        if dev:
            lines.append(f"  开发商: {dev}")
        if desc:
            lines.append(f"  简介: {desc[:200]}")
        if download:
            lines.append(f"  下载量: {download}")

        result = "\n".join(lines)
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.warning(f"TapTap app detail failed: {e}")
        return ""


def _text(soup: BeautifulSoup, selector: str) -> str:
    el = soup.select_one(selector)
    if el:
        txt = el.get_text(strip=True)
        return re.sub(r"\s+", " ", txt)
    return ""

from __future__ import annotations
import json
import httpx
from urllib.parse import quote
from app.utils.logger import logger

STEAM_STORE_SEARCH = "https://store.steampowered.com/api/storesearch"
STEAM_APP_DETAILS = "https://store.steampowered.com/api/appdetails"


async def search_game(query: str) -> str:
    """多源游戏数据搜索，优先查 Steam API"""
    from app.tools import search_web

    result = await _steam_search(query)
    if result:
        return result

    result = await _steam_app_details(query)
    if result:
        return result

    for site in _GAME_SITES:
        q = f"{query} {site}"
        result = await search_web(q, max_results=3)
        if result:
            return result

    result = await search_web(query, max_results=5)
    if result:
        return result

    return ""


_GAME_SITES = [
    "site:steamcommunity.com",
    "site:ign.com",
    "site:gamersky.com",
    "site:3dmgame.com",
    "site:metacritic.com",
    "site:gamerant.com",
]


async def _steam_search(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(STEAM_STORE_SEARCH, params={"term": query, "l": "zh", "cc": "CN"})
            if resp.status_code != 200:
                return ""
            data = resp.json()
            items = data.get("items", [])
            if not items:
                return ""
            appid = items[0].get("id")
            name = items[0].get("name", "")
            price = items[0].get("price", "")
            platform_str = ""
            platforms = items[0].get("platforms", {})
            if platforms:
                supported = [k for k, v in platforms.items() if v]
                platform_str = f"平台: {', '.join(supported)}"
            score = _get_metascore(items[0])
            result = f"[Steam] {name} (AppID: {appid})"
            if price:
                formatted = items[0].get("price_formatted", "")
                result += f"\n  价格: {formatted}"
            if platform_str:
                result += f"\n  {platform_str}"
            if score:
                result += f"\n  评分: {score}"
            return result
    except Exception as e:
        logger.warning(f"Steam search failed: {e}")
        return ""


async def _steam_app_details(query: str) -> str:
    import re
    match = re.search(r"appid[:\s]*(\d+)", query, re.IGNORECASE)
    if not match:
        return ""
    appid = match.group(1)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(STEAM_APP_DETAILS, params={"appids": appid, "l": "zh", "cc": "CN"})
            if resp.status_code != 200:
                return ""
            data = resp.json()
            app_data = data.get(appid, {})
            if not app_data.get("success"):
                return ""
            d = app_data.get("data", {})
            name = d.get("name", "")
            desc = (d.get("short_description", "") or "")[:300]
            price = ""
            if d.get("is_free"):
                price = "免费"
            elif d.get("price_overview"):
                price = d["price_overview"].get("final_formatted", "")
            genres = ", ".join(g.get("description", "") for g in d.get("genres", []))
            dev = ", ".join(d.get("developers", []))
            pub = ", ".join(d.get("publishers", []))
            date = d.get("release_date", {}).get("date", "") if d.get("release_date") else ""
            metacritic = ""
            if d.get("metacritic"):
                metacritic = f"Metacritic: {d['metacritic'].get('score', '')}"
            lines = [f"[Steam] {name}"]
            if desc:
                lines.append(f"  简介: {desc}")
            if price:
                lines.append(f"  价格: {price}")
            if genres:
                lines.append(f"  类型: {genres}")
            if dev:
                lines.append(f"  开发商: {dev}")
            if pub:
                lines.append(f"  发行商: {pub}")
            if date:
                lines.append(f"  发行日期: {date}")
            if metacritic:
                lines.append(f"  {metacritic}")
            return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Steam app details failed: {e}")
        return ""


def _get_metascore(item: dict) -> str:
    score = item.get("metascore")
    if score:
        return f"Metacritic: {score}"
    rating = item.get("review_score", 0)
    if rating:
        desc = item.get("review_description", "")
        return f"Steam评测: {rating}% ({desc})" if desc else f"Steam评测: {rating}%"
    return ""

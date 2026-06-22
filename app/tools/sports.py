from __future__ import annotations
import re
from app.utils.logger import logger

_FIFA_TEAM_MAP: dict[str, str] = {
    "Japan": "日本", "Netherlands": "荷兰", "Spain": "西班牙",
    "Cape Verde": "佛得角", "Cabo Verde": "佛得角",
    "Brazil": "巴西", "Argentina": "阿根廷",
    "Germany": "德国", "France": "法国", "Italy": "意大利",
    "England": "英格兰", "Portugal": "葡萄牙", "Belgium": "比利时",
    "Croatia": "克罗地亚", "Uruguay": "乌拉圭", "South Korea": "韩国",
    "Saudi Arabia": "沙特阿拉伯", "Iran": "伊朗", "Australia": "澳大利亚",
    "Cameroon": "喀麦隆", "Ghana": "加纳", "Senegal": "塞内加尔",
    "Morocco": "摩洛哥", "Mexico": "墨西哥", "Canada": "加拿大",
    "United States": "美国", "Costa Rica": "哥斯达黎加",
    "Ecuador": "厄瓜多尔", "Peru": "秘鲁", "Chile": "智利",
    "Colombia": "哥伦比亚", "Paraguay": "巴拉圭",
    "Denmark": "丹麦", "Switzerland": "瑞士", "Sweden": "瑞典",
    "Poland": "波兰", "Austria": "奥地利", "Ukraine": "乌克兰",
    "Turkey": "土耳其", "Serbia": "塞尔维亚", "Wales": "威尔士",
}

_CN_TO_EN = {v: k for k, v in _FIFA_TEAM_MAP.items()}

# 体育网站域名，用于限定搜索
_SPORTS_SITES = [
    "site:cctv.cn/2026",
    "site:sohu.com",
    "site:163.com",
    "site:footballant.com",
    "site:msn.cn",
    "site:dongqiudi.com",
    "site:hupu.com",
    "site:qq.com/sports",
    "site:sports.sina.com.cn",
]


async def search_sports(query: str) -> str:
    """多源体育赛事数据搜索，优先查比分/赛程"""
    from app.tools import search_web

    teams = _extract_teams(query)
    teams_en = [_cn_to_en(t) for t in teams]

    # 策略1：FIFA API
    result = await _fetch_fifa_wc2026(teams_en)
    if result:
        return result

    # 策略2：体育网站限定搜索
    if teams:
        for site in _SPORTS_SITES:
            q = f"{' '.join(teams)} 世界杯 比分 {site}"
            result = await search_web(q, max_results=3)
            if result:
                return result

    # 策略3：精确搜索（球队+日期+比分）
    date_str = _extract_date(query)
    if teams and date_str:
        q = f"{date_str} {' '.join(teams)} 比分"
        result = await search_web(q, max_results=5)
        if result:
            return result

    # 策略4：球队搜索
    if teams:
        q = f"{' '.join(teams)} 世界杯 比分"
        result = await search_web(q, max_results=5)
        if result:
            return result

    # 策略5：原始查询
    result = await search_web(query, max_results=5)
    if result:
        return result

    return ""


async def _fetch_fifa_wc2026(teams_en: list[str]) -> str:
    """从 FIFA 官方 API 获取 2026 世界杯比赛数据"""
    if not teams_en or len(teams_en) < 2:
        return ""
    import httpx

    url = "https://api.fifa.com/api/v3/calendar/matches"
    params = {"competitionCode": "FWC", "seasonYear": "2026", "count": 200}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return ""

            data = resp.json()
            matches = data.get("Results", [])

            # 尝试精确匹配 + 别名匹配
            for m in matches:
                home_en = _get_team_name(m, "HomeTeamName")
                away_en = _get_team_name(m, "AwayTeamName")
                if not home_en or not away_en:
                    continue
                t1, t2 = teams_en[0].lower(), teams_en[1].lower()
                home_lower = home_en.lower()
                away_lower = away_en.lower()

                if (home_lower == t1 and away_lower == t2) or \
                   (home_lower == t2 and away_lower == t1) or \
                   (home_lower in (t1, t2) and away_lower in (t1, t2)):
                    return _format_match(m, home_en, away_en)

            # 没有精确匹配 → 返回关联小组完整赛程
            target_group = None
            for m in matches:
                home_en = _get_team_name(m, "HomeTeamName")
                away_en = _get_team_name(m, "AwayTeamName")
                if not home_en or not away_en:
                    continue
                hl = home_en.lower()
                al = away_en.lower()
                if hl in [t.lower() for t in teams_en] or al in [t.lower() for t in teams_en]:
                    target_group = m.get("IdGroup")
                    break

            if target_group:
                lines = []
                for m in matches:
                    if m.get("IdGroup") != target_group:
                        continue
                    h = _get_team_name(m, "HomeTeamName")
                    a = _get_team_name(m, "AwayTeamName")
                    if not h or not a:
                        continue
                    lines.append(_format_match(m, h, a))
                if lines:
                    return "\n".join(lines)

    except Exception as e:
        logger.warning(f"FIFA API fetch failed: {e}")

    return ""


def _get_team_name(match: dict, key: str) -> str:
    names = match.get(key, []) or []
    if names:
        return names[0].get("Description", "")
    return ""


def _format_match(match: dict, home_en: str, away_en: str) -> str:
    hs = match.get("HomeTeamScore")
    a_s = match.get("AwayTeamScore")
    date = (match.get("Date", "") or "")[:10]
    stage = ""
    for s in (match.get("StageName", []) or []):
        stage = s.get("Description", "")
        if stage:
            break
    group = match.get("GroupName", "") or ""
    home_cn = _FIFA_TEAM_MAP.get(home_en, home_en)
    away_cn = _FIFA_TEAM_MAP.get(away_en, away_en)
    if hs is not None and a_s is not None:
        return f"{date} {stage} {group}: {home_cn} {hs}:{a_s} {away_cn}"
    else:
        return f"{date} {stage} {group}: {home_cn} vs {away_cn}（未开始）"


def _extract_teams(text: str) -> list[str]:
    """从查询中提取球队名"""
    separators = [r"\s+vs\.?\s+", r"\s+VS\.?\s+", r"\s*:\s*", r"\s+对\s+", r"\s+战\s+"]
    for sep in separators:
        parts = re.split(sep, text)
        if len(parts) >= 2:
            left = _clean_team(parts[0].split()[-1]) if parts[0].split() else ""
            right = _clean_team(parts[1].split()[0]) if parts[1].split() else ""
            if left and right:
                return [left, right]
    return []


def _clean_team(s: str) -> str:
    return s.strip("\"':：，,。.!！？?")


def _extract_date(text: str) -> str | None:
    """从查询中提取日期"""
    patterns = [
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(\d{1,2})月(\d{1,2})日",
        r"六月十五",
        r"六月\s*\d+",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None


def _cn_to_en(name: str) -> str:
    return _CN_TO_EN.get(name, name)

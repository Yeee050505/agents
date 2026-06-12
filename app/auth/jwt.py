from __future__ import annotations
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Request, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.utils.logger import logger

security = HTTPBearer(auto_error=False)


def create_access_token(user_id: str, role: str = "user") -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
    return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    if credentials is None:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return None
    else:
        token = credentials.credentials

    payload = decode_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")

    from app.auth.blacklist import blacklist
    if blacklist.is_blacklisted(user_id):
        raise HTTPException(status_code=403, detail="用户已被禁用")

    request.state.user_id = user_id
    request.state.user_role = payload.get("role", "user")
    return user_id


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    token = credentials.credentials if credentials else None
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证令牌")
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="无效的认证令牌")
    return payload.get("sub")

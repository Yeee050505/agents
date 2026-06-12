from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.utils.logger import logger


class AppException(Exception):
    def __init__(self, code: int = 400, msg: str = "请求异常"):
        self.code = code
        self.msg = msg


class AuthException(AppException):
    def __init__(self, msg: str = "认证失败"):
        super().__init__(code=401, msg=msg)


class RateLimitException(AppException):
    def __init__(self, msg: str = "请求过于频繁"):
        super().__init__(code=429, msg=msg)


class ModelCallException(AppException):
    def __init__(self, msg: str = "模型调用异常"):
        super().__init__(code=502, msg=msg)


class ParamException(AppException):
    def __init__(self, msg: str = "参数校验失败"):
        super().__init__(code=422, msg=msg)


def register_handlers(app: FastAPI):
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        logger.warning(
            f"业务异常: {exc.msg}",
            extra={"request_id": getattr(request.state, "request_id", "-")},
        )
        return JSONResponse(
            status_code=exc.code,
            content={"code": exc.code, "msg": exc.msg},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            f"系统异常: {exc}",
            exc_info=True,
            extra={"request_id": getattr(request.state, "request_id", "-")},
        )
        return JSONResponse(
            status_code=500,
            content={"code": 500, "msg": "服务器内部错误，请稍后重试"},
        )

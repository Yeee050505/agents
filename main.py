from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.utils.logger import logger
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.rate_limiter import RateLimitMiddleware
from app.exceptions.handlers import register_handlers
from app.api.routes import router
from app.services.cache import cache
from app.database.models import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME}")
    init_db()
    await cache.init()
    logger.info(
        f"Rate limiter: global=({settings.GLOBAL_RATE}/s, burst={settings.GLOBAL_CAPACITY}), "
        f"user=({settings.USER_RATE}/s, burst={settings.USER_CAPACITY})"
    )
    yield
    await cache.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware)

register_handlers(app)
app.include_router(router, prefix="/api/v1")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("templates/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
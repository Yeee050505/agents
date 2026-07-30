from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GameNexus starting")
    yield
    logger.info("Shutdown complete")


app = FastAPI(title="GameNexus 游戏RAG问答系统", version="2.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

from app.api.routes import router
app.include_router(router, prefix="/api/v1")

# --- Frontend static serving ---
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse

    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(str(FRONTEND_DIST / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"code": 404, "message": "Not found"})
        fp = FRONTEND_DIST / full_path
        if fp.is_file():
            return FileResponse(str(fp))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
else:
    from fastapi.responses import JSONResponse

    @app.get("/", include_in_schema=False)
    async def root():
        return JSONResponse(content={"code": 200, "message": "GameNexus v2.0", "api_docs": "/docs"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8080)

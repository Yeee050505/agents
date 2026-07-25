from __future__ import annotations
import os


class Settings:
    APP_NAME: str = "GameNexus 游戏RAG问答系统"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # LLM API Key Pool
    LLM_API_KEYS: list[str] = os.getenv(
        "LLM_API_KEYS",
        "",
    ).split(",") if os.getenv("LLM_API_KEYS") else []
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

    # Embedding
    EMBED_LOCAL_MODEL: str = os.getenv("EMBED_LOCAL_MODEL", "BAAI/bge-base-zh-v1.5")

    # Logging
    LOG_FILE: str = os.getenv("LOG_FILE", "app.log")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()

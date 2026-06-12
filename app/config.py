from __future__ import annotations
import os


class Settings:
    # App
    APP_NAME: str = "Multi-Agent Platform"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # Token Bucket Rate Limiter — Global
    GLOBAL_RATE: float = float(os.getenv("GLOBAL_RATE", "20.0"))
    GLOBAL_CAPACITY: int = int(os.getenv("GLOBAL_CAPACITY", "50"))

    # Token Bucket Rate Limiter — Per-User
    USER_RATE: float = float(os.getenv("USER_RATE", "5.0"))
    USER_CAPACITY: int = int(os.getenv("USER_CAPACITY", "10"))

    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./agent.db",
    )

    # LLM API Key Pool
    LLM_API_KEYS: list[str] = os.getenv(
        "LLM_API_KEYS",
        "",
    ).split(",") if os.getenv("LLM_API_KEYS") else []
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "60"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

    # Sensitive words
    SENSITIVE_WORDS: list[str] = os.getenv(
        "SENSITIVE_WORDS",
        "",
    ).split(",") if os.getenv("SENSITIVE_WORDS") else []

    # Request limits
    MAX_TEXT_LENGTH: int = int(os.getenv("MAX_TEXT_LENGTH", "4096"))

    # Logging
    LOG_FILE: str = os.getenv("LOG_FILE", "app.log")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # LangGraph
    AGENT_TIMEOUT: int = int(os.getenv("AGENT_TIMEOUT", "120"))


settings = Settings()

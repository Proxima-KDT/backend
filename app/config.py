from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str           # anon key (프론트엔드용)
    SUPABASE_SERVICE_KEY: str   # service_role key (백엔드 DB 조회용 — RLS 우회)
    SUPABASE_JWT_SECRET: str

    # OpenAI
    OPENAI_API_KEY: str

    # App
    APP_ENV: str = "development"
    FRONTEND_URL: str = "http://localhost:5173"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()

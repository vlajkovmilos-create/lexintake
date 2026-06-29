from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "LexIntake"
    app_version: str = "1.0.0"
    debug: bool = True

    database_url: str = "sqlite:///./lexintake.db"

    anthropic_api_key: str
    resend_api_key: str
    from_email: str = "noreply@tvojdomen.com"

    secret_key: str

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
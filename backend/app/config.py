from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "LexIntake"
    app_version: str = "1.1.0"
    debug: bool = False

    database_url: str = "sqlite:///./lexintake.db"

    anthropic_api_key: str
    ai_model: str = "claude-sonnet-5-5"

    resend_api_key: str
    from_email: str = "LexIntake <obavestenja@lex.vlajkov.rs>"

    secret_key: str
    lemonsqueezy_webhook_secret: str = ""

    # Adresa frontenda (GitHub Pages) - koristi se za linkove u mejlovima
    frontend_url: str = "https://vlajkovmilos-create.github.io/lexintake"
    # Dozvoljeni CORS origini, razdvojeni zarezom (localhost je uvek dozvoljen)
    cors_origini: str = "https://vlajkovmilos-create.github.io"

    # Zaštita od zloupotrebe upitnika
    max_poruka_po_razgovoru: int = 30
    max_razgovora_po_advokatu_dnevno: int = 100
    max_razgovora_po_ip_na_sat: int = 10
    max_poruka_po_ip_u_minutu: int = 20
    dana_cuvanja_nedovrsenih: int = 30

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

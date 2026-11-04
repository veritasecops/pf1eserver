from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PF_", env_file=ROOT / ".env", extra="ignore")
    database_url: str
    encryption_key: str
    secure_cookies: bool = False
    session_hours: int = 12
    idle_minutes: int = 60
    storage: Path = ROOT / "storage"


@lru_cache
def settings() -> Settings:
    return Settings()

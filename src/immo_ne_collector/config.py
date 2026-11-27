from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Immo NE Collector"
    environment: str = "local"
    database_url: str = "postgresql+asyncpg://immo:immo@localhost:5432/immo_ne"
    inactive_after_days: int = 7
    new_window_hours: int = 24
    updated_window_hours: int = 24
    log_level: str = "INFO"
    # Coordonnées via geo.admin.ch (code postal uniquement). Désactivé dans les tests.
    geocoding_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Clinical Simulation Backend", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    data_dir: Path = Field(default=Path("app/data"), alias="DATA_DIR")
    session_dir: Path = Field(default=Path("app/data/sessions"), alias="SESSION_DIR")
    default_case_id: str = Field(default="htn_enceph_001", alias="DEFAULT_CASE_ID")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    return settings

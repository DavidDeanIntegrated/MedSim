from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="MedSim — Clinical Simulation Platform", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    data_dir: Path = Field(default=Path("app/data"), alias="DATA_DIR")
    session_dir: Path = Field(default=Path("app/data/sessions"), alias="SESSION_DIR")
    default_case_id: str = Field(default="htn_enceph_001", alias="DEFAULT_CASE_ID")

    # Database (SQLite locally, PostgreSQL via Supabase in production)
    database_url: str = Field(default="sqlite:///./medsim.db", alias="DATABASE_URL")

    # JWT Authentication
    jwt_secret: str = Field(default="medsim-dev-secret-change-in-production", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=1440, alias="JWT_EXPIRE_MINUTES")  # 24 hours

    # LLM Parser (optional — leave ANTHROPIC_API_KEY empty to use rule-based only)
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    llm_parser_model: str = Field(default="claude-sonnet-4-20250514", alias="LLM_PARSER_MODEL")
    llm_parser_enabled: bool = Field(default=False, alias="LLM_PARSER_ENABLED")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    return settings

"""应用配置模块。.

负责从环境变量读取数据库连接和应用运行配置。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类，从环境变量加载。."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 数据库配置
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/a3_cases"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/a3_cases"

    # 应用配置
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False

    # Alembic 迁移配置
    alembic_database_url: str = "postgresql://postgres:postgres@localhost:5432/a3_cases"


settings = Settings()
"""应用配置模块。.

负责从环境变量读取数据库连接和应用运行配置。
"""
import os
from functools import lru_cache

from pydantic import BaseModel
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


# ---------------------------------------------------------------------------
# 多模型配置基础设施
# ---------------------------------------------------------------------------
# 四个独立配置类，分别供不同下游规格使用：
#   - EnrichmentLLMConfig: llm-case-enrichment
#   - NormalizerLLMConfig: cbr-retrieval-recommendation
#   - EmbeddingConfig:     case-vector-indexing
#   - RerankerConfig:      cbr-retrieval-recommendation
# ---------------------------------------------------------------------------


class EnrichmentLLMConfig(BaseModel):
    """LLM enrichment 专用配置（本规格使用）。"""

    api_key: str
    model_id: str
    base_url: str
    timeout_ms: int = 30000
    max_retries: int = 2
    privacy_acknowledged: bool = False


class NormalizerLLMConfig(BaseModel):
    """LLM normalizer 专用配置（cbr-retrieval-recommendation 使用）。"""

    api_key: str
    model_id: str
    base_url: str
    timeout_ms: int = 30000
    max_retries: int = 2


class EmbeddingConfig(BaseModel):
    """Embedding 专用配置（case-vector-indexing 使用）。"""

    api_key: str
    model_id: str
    base_url: str
    timeout_ms: int = 60000
    max_retries: int = 3


class RerankerConfig(BaseModel):
    """Reranker 专用配置（cbr-retrieval-recommendation 使用）。"""

    api_key: str
    model_id: str
    base_url: str
    timeout_ms: int = 45000
    max_retries: int = 2


class AppConfig(BaseModel):
    """聚合四个模型配置 + 全局共享配置。"""

    enrichment_llm: EnrichmentLLMConfig
    normalizer_llm: NormalizerLLMConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig
    max_recommendation_candidates: int = 10


def load_app_config() -> AppConfig:
    """从环境变量构造 AppConfig。

    环境变量命名约定：
        ENRICHMENT_LLM_APIKEY, ENRICHMENT_LLM_MODEL_ID, ...
        NORMALIZER_LLM_APIKEY, NORMALIZER_LLM_MODEL_ID, ...
        EMBEDDING_APIKEY, EMBEDDING_MODEL_ID, ...
        RERANKER_APIKEY, RERANKER_MODEL_ID, ...
        MAX_RECOMMENDATION_CANDIDATES
    """

    def _env(name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    def _int_env(name: str, default: int) -> int:
        raw = os.environ.get(name)
        return int(raw) if raw is not None else default

    def _bool_env(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.lower() in ("true", "1", "yes")

    enrichment_llm = EnrichmentLLMConfig(
        api_key=_env("ENRICHMENT_LLM_APIKEY", "sk-8b463750264e4d21b6265279baad9aba"),
        model_id=_env("ENRICHMENT_LLM_MODEL_ID", "deepseek-v4-flash"),
        base_url=_env("ENRICHMENT_LLM_BASE_URL", "https://api.deepseek.com/v2"),
        timeout_ms=_int_env("ENRICHMENT_LLM_TIMEOUT_MS", 30000),
        max_retries=_int_env("ENRICHMENT_LLM_MAX_RETRIES", 2),
        privacy_acknowledged=_bool_env("ENRICHMENT_LLM_PRIVACY_ACKNOWLEDGED", False),
    )

    normalizer_llm = NormalizerLLMConfig(
        api_key=_env("NORMALIZER_LLM_APIKEY", "sk-8b463750264e4d21b6265279baad9aba"),
        model_id=_env("NORMALIZER_LLM_MODEL_ID", "deepseek-v4-flash"),
        base_url=_env("NORMALIZER_LLM_BASE_URL", "https://api.deepseek.com/v2"),
        timeout_ms=_int_env("NORMALIZER_LLM_TIMEOUT_MS", 30000),
        max_retries=_int_env("NORMALIZER_LLM_MAX_RETRIES", 2),
    )

    embedding = EmbeddingConfig(
        api_key=_env("EMBEDDING_APIKEY", "bce-v3/ALTAK-tgcGXYeI49tASPCrdhCto/d0727a02df3238fc4f7c79bab603a1b5fba3dec0"),
        model_id=_env("EMBEDDING_MODEL_ID", "bge-large-zh"),
        base_url=_env("EMBEDDING_BASE_URL", "https://qianfan.baidubce.com/v2"),
        timeout_ms=_int_env("EMBEDDING_TIMEOUT_MS", 60000),
        max_retries=_int_env("EMBEDDING_MAX_RETRIES", 3),
    )

    reranker = RerankerConfig(
        api_key=_env("RERANKER_APIKEY", "bce-v3/ALTAK-tgcGXYeI49tASPCrdhCto/d0727a02df3238fc4f7c79bab603a1b5fba3dec0"),
        model_id=_env("RERANKER_MODEL_ID", "qwen3-reranker-8b"),
        base_url=_env("RERANKER_BASE_URL", "https://qianfan.baidubce.com/v2"),
        timeout_ms=_int_env("RERANKER_TIMEOUT_MS", 45000),
        max_retries=_int_env("RERANKER_MAX_RETRIES", 2),
    )

    return AppConfig(
        enrichment_llm=enrichment_llm,
        normalizer_llm=normalizer_llm,
        embedding=embedding,
        reranker=reranker,
        max_recommendation_candidates=_int_env("MAX_RECOMMENDATION_CANDIDATES", 10),
    )


@lru_cache()
def get_app_config() -> AppConfig:
    """全局单例配置，应用启动时加载一次。"""
    return load_app_config()
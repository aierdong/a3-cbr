"""应用配置模块。.

负责从环境变量读取数据库连接和应用运行配置。
"""
import json
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类，从环境变量与可选的 .env 文件加载。

    数据库与应用基础项在模块导入时实例化 ``settings``；
    ``load_app_config`` 每次调用会再构造 ``Settings()``，
    以便测试与运行时可响应环境变量变化。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 数据库配置
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/a3_cases"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/a3_cases"
    test_database_url: str = ""

    # 应用配置
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False

    # Alembic 迁移配置
    alembic_database_url: str = "postgresql://postgres:postgres@localhost:5432/a3_cases"

    # --- 案例富化 LLM ---
    enrichment_llm_apikey: str = ""
    enrichment_llm_model_id: str = "deepseek-v4-flash"
    enrichment_llm_base_url: str = "https://api.deepseek.com/v2"
    enrichment_llm_timeout_ms: int = 30000
    enrichment_llm_max_retries: int = 2
    enrichment_llm_privacy_acknowledged: bool = False
    # 可选：JSON 对象，合并为 chat.completions.create 的顶层参数（禁止覆盖 model/messages）
    enrichment_llm_chat_completions_extra_json: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ENRICHMENT_LLM_CHAT_COMPLETIONS_EXTRA",
            "enrichment_llm_chat_completions_extra_json",
        ),
    )
    # 可选：JSON 对象，单独作为 extra_body 传入 create（后于上一项应用，可覆盖其中的 extra_body）
    enrichment_llm_extra_body_json: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ENRICHMENT_LLM_EXTRA_BODY",
            "enrichment_llm_extra_body_json",
        ),
    )

    # --- 查询规范化 LLM ---
    normalizer_llm_apikey: str = ""
    normalizer_llm_model_id: str = "deepseek-v4-flash"
    normalizer_llm_base_url: str = "https://api.deepseek.com/v2"
    normalizer_llm_timeout_ms: int = 30000
    normalizer_llm_max_retries: int = 2
    normalizer_llm_chat_completions_extra_json: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NORMALIZER_LLM_CHAT_COMPLETIONS_EXTRA",
            "normalizer_llm_chat_completions_extra_json",
        ),
    )
    normalizer_llm_extra_body_json: str = Field(
        default="",
        validation_alias=AliasChoices(
            "NORMALIZER_LLM_EXTRA_BODY",
            "normalizer_llm_extra_body_json",
        ),
    )

    # --- 向量嵌入 ---
    embedding_apikey: str = ""
    embedding_model_id: str = "bge-large-zh"
    embedding_base_url: str = "https://qianfan.baidubce.com/v2"
    embedding_timeout_ms: int = 60000
    embedding_max_retries: int = 3
    embedding_vector_dimension: int = 1024
    embedding_pgvector_min_version: str = "0.8.2"
    embedding_privacy_acknowledged: bool = False
    embedding_index_timeout_ms: int = 30000
    embedding_index_max_retries: int = 2
    embedding_search_timeout_ms: int = 5000
    embedding_search_max_retries: int = 0
    vector_cleanup_interval_seconds: int = 86400

    # --- Reranker ---
    reranker_apikey: str = ""
    reranker_model_id: str = "qwen3-reranker-8b"
    reranker_base_url: str = "https://qianfan.baidubce.com/v2"
    reranker_timeout_ms: int = 45000
    reranker_max_retries: int = 2

    # --- 检索推荐与推荐反馈 ---
    max_recommendation_candidates: int = 10
    retrieval_enabled: bool = True
    retrieval_max_top_k: int = 20
    retrieval_max_vector_candidates: int = 50
    feedback_enabled: bool = True
    feedback_comment_max_length: int = 2000
    feedback_stats_default_range_days: int = 30

    @field_validator(
        "enrichment_llm_privacy_acknowledged",
        "embedding_privacy_acknowledged",
        "retrieval_enabled",
        "feedback_enabled",
        "app_debug",
        mode="before",
    )
    @classmethod
    def _coerce_env_bool(cls, value: object) -> object:
        """与历史 os.environ 布尔解析一致：true / 1 / yes（大小写不敏感）。"""
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return value


settings = Settings()


def _parse_json_object_env(raw: str, *, label: str) -> dict[str, Any]:
    """解析可选环境变量中的 JSON 对象（空字符串视为空对象）。"""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        val = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"{label} 必须为合法 JSON 对象: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(val, dict):
        msg = f"{label} 必须为 JSON 对象（顶层为键值对），实际类型: {type(val).__name__}"
        raise ValueError(msg)
    return val


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
    #: 合并到 ``chat.completions.create`` 的额外顶层参数
    #: （如 ``reasoning_effort``、``extra_body`` 等）
    chat_completions_extra: dict[str, Any] = Field(default_factory=dict)
    #: 若设置则始终作为 ``extra_body=...`` 传入，覆盖 ``chat_completions_extra`` 中的同名键
    extra_body: dict[str, Any] | None = None


class NormalizerLLMConfig(BaseModel):
    """LLM normalizer 专用配置（cbr-retrieval-recommendation 使用）。"""

    api_key: str
    model_id: str
    base_url: str
    timeout_ms: int = 30000
    max_retries: int = 2
    #: 合并到 ``chat.completions.create`` 的额外顶层参数
    #: （如 ``reasoning_effort``、``extra_body`` 等）
    chat_completions_extra: dict[str, Any] = Field(default_factory=dict)
    #: 若设置则始终作为 ``extra_body=...`` 传入，覆盖 ``chat_completions_extra`` 中的同名键
    extra_body: dict[str, Any] | None = None


class EmbeddingConfig(BaseModel):
    """Embedding 专用配置（case-vector-indexing 使用）。"""

    api_key: str
    model_id: str
    base_url: str
    timeout_ms: int = 60000
    max_retries: int = 3
    vector_dimension: int = 1024  # BGE-large 默认维度
    pgvector_min_version: str = "0.8.2"
    privacy_acknowledged: bool = False
    # 索引刷新路径（延迟容忍较高）：默认 30s、最多 2 次重试
    index_timeout_ms: int = 30000
    index_max_retries: int = 2
    # 候选搜索路径（延迟敏感）：默认 5s、不重试，失败映射 503 语义
    search_timeout_ms: int = 5000
    search_max_retries: int = 0
    vector_cleanup_interval_seconds: int = 86400


class RerankerConfig(BaseModel):
    """Reranker 专用配置（cbr-retrieval-recommendation 使用）。"""

    api_key: str
    model_id: str
    base_url: str
    timeout_ms: int = 45000
    max_retries: int = 2


class RetrievalConfig(BaseModel):
    """检索推荐专用配置（cbr-retrieval-recommendation 使用）。

    包装 AppConfig 中与检索推荐相关的配置字段，
    提供统一的 config.reranker_model_id 访问方式。
    """

    retrieval_enabled: bool = True
    max_top_k: int = 20
    max_vector_candidates: int = 50
    default_score_weights: dict[str, float] = {
        "vector": 0.3,
        "semantic": 0.3,
        "structured": 0.2,
        "business": 0.2,
    }
    max_business_weight: float = 1.0
    contract_version: str = "mvp-1"
    reranker_model_id: str = "qwen3-reranker-8b"


class FeedbackConfig(BaseModel):
    """推荐反馈专用配置（recommendation-feedback 使用）。"""

    enabled: bool = True
    comment_max_length: int = 2000
    stats_default_range_days: int = 30


def get_retrieval_config(config: "AppConfig") -> RetrievalConfig:
    """从 AppConfig 构造检索推荐配置。

    Args:
        config: 应用配置。

    Returns:
        检索推荐配置。
    """
    return RetrievalConfig(
        retrieval_enabled=config.retrieval_enabled,
        max_top_k=config.max_top_k,
        max_vector_candidates=config.max_vector_candidates,
        default_score_weights=config.default_score_weights,
        max_business_weight=config.max_business_weight,
        contract_version=config.contract_version,
        reranker_model_id=config.reranker.model_id,
    )


class AppConfig(BaseModel):
    """聚合四个模型配置 + 全局共享配置。

    检索推荐相关配置通过 `retrieval` 属性访问。
    """

    enrichment_llm: EnrichmentLLMConfig
    normalizer_llm: NormalizerLLMConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig
    max_recommendation_candidates: int = 10
    # --- cbr-retrieval-recommendation 配置 ---
    retrieval_enabled: bool = True
    max_top_k: int = 20
    max_vector_candidates: int = 50
    default_score_weights: dict[str, float] = {
        "vector": 0.3,
        "semantic": 0.3,
        "structured": 0.2,
        "business": 0.2,
    }
    max_business_weight: float = 1.0
    contract_version: str = "mvp-1"
    # --- recommendation-feedback 配置 ---
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)

    @property
    def retrieval(self) -> RetrievalConfig:
        """返回检索推荐配置。"""
        return get_retrieval_config(self)


def load_app_config() -> AppConfig:
    """从环境变量与 .env 构造 AppConfig（与 ``Settings`` 同源）。

    每次调用新建 ``Settings()``，以便在测试中通过 ``monkeypatch`` 修改环境变量后
    与 ``get_app_config.cache_clear()`` 组合可得到最新配置。

    环境变量命名约定（与字段名对应，不区分大小写）：
        ENRICHMENT_LLM_APIKEY, ENRICHMENT_LLM_MODEL_ID, ...
        ENRICHMENT_LLM_CHAT_COMPLETIONS_EXTRA（JSON 对象）, ENRICHMENT_LLM_EXTRA_BODY（JSON 对象）
        NORMALIZER_LLM_APIKEY, NORMALIZER_LLM_MODEL_ID, ...
        NORMALIZER_LLM_CHAT_COMPLETIONS_EXTRA（JSON 对象）, NORMALIZER_LLM_EXTRA_BODY（JSON 对象）
        EMBEDDING_APIKEY, EMBEDDING_MODEL_ID, ...
        RERANKER_APIKEY, RERANKER_MODEL_ID, ...
        MAX_RECOMMENDATION_CANDIDATES
        FEEDBACK_ENABLED, FEEDBACK_COMMENT_MAX_LENGTH, FEEDBACK_STATS_DEFAULT_RANGE_DAYS
    """
    s = Settings()

    chat_extra = _parse_json_object_env(
        s.enrichment_llm_chat_completions_extra_json,
        label="ENRICHMENT_LLM_CHAT_COMPLETIONS_EXTRA",
    )
    extra_body: dict[str, Any] | None = None
    if (s.enrichment_llm_extra_body_json or "").strip():
        extra_body = _parse_json_object_env(
            s.enrichment_llm_extra_body_json,
            label="ENRICHMENT_LLM_EXTRA_BODY",
        )

    enrichment_llm = EnrichmentLLMConfig(
        api_key=s.enrichment_llm_apikey,
        model_id=s.enrichment_llm_model_id,
        base_url=s.enrichment_llm_base_url,
        timeout_ms=s.enrichment_llm_timeout_ms,
        max_retries=s.enrichment_llm_max_retries,
        privacy_acknowledged=s.enrichment_llm_privacy_acknowledged,
        chat_completions_extra=chat_extra,
        extra_body=extra_body,
    )

    norm_chat_extra = _parse_json_object_env(
        s.normalizer_llm_chat_completions_extra_json,
        label="NORMALIZER_LLM_CHAT_COMPLETIONS_EXTRA",
    )
    norm_extra_body: dict[str, Any] | None = None
    if (s.normalizer_llm_extra_body_json or "").strip():
        norm_extra_body = _parse_json_object_env(
            s.normalizer_llm_extra_body_json,
            label="NORMALIZER_LLM_EXTRA_BODY",
        )

    normalizer_llm = NormalizerLLMConfig(
        api_key=s.normalizer_llm_apikey,
        model_id=s.normalizer_llm_model_id,
        base_url=s.normalizer_llm_base_url,
        timeout_ms=s.normalizer_llm_timeout_ms,
        max_retries=s.normalizer_llm_max_retries,
        chat_completions_extra=norm_chat_extra,
        extra_body=norm_extra_body,
    )

    embedding = EmbeddingConfig(
        api_key=s.embedding_apikey,
        model_id=s.embedding_model_id,
        base_url=s.embedding_base_url,
        timeout_ms=s.embedding_timeout_ms,
        max_retries=s.embedding_max_retries,
        vector_dimension=s.embedding_vector_dimension,
        pgvector_min_version=s.embedding_pgvector_min_version,
        privacy_acknowledged=s.embedding_privacy_acknowledged,
        index_timeout_ms=s.embedding_index_timeout_ms,
        index_max_retries=s.embedding_index_max_retries,
        search_timeout_ms=s.embedding_search_timeout_ms,
        search_max_retries=s.embedding_search_max_retries,
        vector_cleanup_interval_seconds=s.vector_cleanup_interval_seconds,
    )

    reranker = RerankerConfig(
        api_key=s.reranker_apikey,
        model_id=s.reranker_model_id,
        base_url=s.reranker_base_url,
        timeout_ms=s.reranker_timeout_ms,
        max_retries=s.reranker_max_retries,
    )

    return AppConfig(
        enrichment_llm=enrichment_llm,
        normalizer_llm=normalizer_llm,
        embedding=embedding,
        reranker=reranker,
        max_recommendation_candidates=s.max_recommendation_candidates,
        retrieval_enabled=s.retrieval_enabled,
        max_top_k=s.retrieval_max_top_k,
        max_vector_candidates=s.retrieval_max_vector_candidates,
        default_score_weights={
            "vector": 0.3,
            "semantic": 0.3,
            "structured": 0.2,
            "business": 0.2,
        },
        max_business_weight=1.0,
        contract_version="mvp-1",
        feedback=FeedbackConfig(
            enabled=s.feedback_enabled,
            comment_max_length=s.feedback_comment_max_length,
            stats_default_range_days=s.feedback_stats_default_range_days,
        ),
    )


@lru_cache()
def get_app_config() -> AppConfig:
    """全局单例配置，应用启动时加载一次。"""
    return load_app_config()


# ---------------------------------------------------------------------------
# 向量索引配置校验（case-vector-indexing 1.1）
# ---------------------------------------------------------------------------
# 三类状态：
#   - dev_fake: api_key 为空或 "fake"，使用本地 fake embedding（开发/测试）
#   - production_remote: api_key 有效，model_id 为 bge-large-zh，privacy_acknowledged=True
#   - config_missing: 生产环境缺少必要配置，fail-closed
# ---------------------------------------------------------------------------


class EmbeddingConfigStatus:
    """Embedding 配置状态（区分三类配置场景）。"""

    DEVMODE_FAKE = "dev_fake"  # 开发 fake embedding
    PRODUCTION_REMOTE = "production_remote"  # 生产远程 embedding
    CONFIG_MISSING = "config_missing"  # 配置缺失，fail-closed


def get_embedding_config_status(config: EmbeddingConfig) -> EmbeddingConfigStatus:
    """判断 EmbeddingConfig 所处状态，用于启用门控。

    Args:
        config: EmbeddingConfig 实例。

    Returns:
        EmbeddingConfigStatus: 配置状态枚举值。
    """
    api_key = config.api_key or ""
    is_fake_key = api_key.lower() in ("", "fake", "test")

    if is_fake_key:
        return EmbeddingConfigStatus.DEVMODE_FAKE

    # 生产环境：api_key 有效，必须确认隐私政策
    if not config.privacy_acknowledged:
        return EmbeddingConfigStatus.CONFIG_MISSING

    # api_key 有效 + privacy_acknowledged=True -> 生产远程 embedding
    return EmbeddingConfigStatus.PRODUCTION_REMOTE
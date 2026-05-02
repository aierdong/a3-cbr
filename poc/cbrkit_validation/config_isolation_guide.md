# 多模型配置隔离实施指南

## 问题背景

设计文档要求 LLM normalizer、embedding、reranker 三类模型使用**彼此独立**的配置，避免配置串用导致的隐式影响。例如：
- 修改 reranker 超时不应影响 LLM normalizer
- 更换 embedding 供应商不应改变推荐文案模型
- 三类模型的配置变更应该是显式且可追溯的

## 实施方案

### 1. 定义独立配置类

在 `backend/app/core/config.py` 中定义三个独立的 Pydantic 配置类：

```python
# backend/app/core/config.py

from pydantic import BaseModel, Field
from typing import Optional


class NormalizerLLMConfig(BaseModel):
    """LLM normalizer 配置（查询标准化专用）"""
    provider: str = Field(..., description="供应商，如 'deepseek'")
    model_id: str = Field(..., description="模型 ID，如 'deepseek-v4-pro'")
    base_url: str = Field(..., description="API 基础 URL")
    timeout: int = Field(30, description="超时时间（秒）")
    max_retries: int = Field(3, description="最大重试次数")
    privacy_acknowledged: bool = Field(False, description="隐私策略确认")


class EmbeddingConfig(BaseModel):
    """Embedding 配置（向量生成专用）"""
    provider: str = Field(..., description="供应商")
    model_id: str = Field(..., description="模型 ID，如 'bge-large-zh'")
    base_url: str = Field(..., description="API 基础 URL")
    timeout: int = Field(60, description="超时时间（秒）")
    max_retries: int = Field(3, description="最大重试次数")
    batch_size: int = Field(32, description="批处理大小")
    privacy_acknowledged: bool = Field(False, description="隐私策略确认")


class RerankerConfig(BaseModel):
    """Reranker 配置（语义精排专用）"""
    provider: str = Field(..., description="供应商")
    model_id: str = Field("qwen3-reranker-8b", description="模型 ID")
    base_url: str = Field(..., description="API 基础 URL")
    timeout: int = Field(45, description="超时时间（秒）")
    max_retries: int = Field(2, description="最大重试次数")
    max_candidates: int = Field(100, description="最大候选数")
    privacy_acknowledged: bool = Field(False, description="隐私策略确认")


class RetrievalConfig(BaseModel):
    """检索推荐配置"""
    enabled: bool = Field(True, description="检索推荐开关")
    top_k_limit: int = Field(50, description="Top-K 上限")
    default_weights: dict = Field(
        default={
            "vector": 0.3,
            "semantic": 0.4,
            "structured": 0.1,
            "business": 0.2
        },
        description="默认聚合权重"
    )
    
    # 三类模型的独立配置
    normalizer_llm: NormalizerLLMConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig


class Settings(BaseModel):
    """应用全局配置"""
    # ... 其他配置 ...
    
    retrieval: RetrievalConfig
    
    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"


# 全局配置实例
settings = Settings()
```

### 2. 环境变量配置示例

`.env` 文件示例：

```bash
# LLM Normalizer 配置
RETRIEVAL__NORMALIZER_LLM__PROVIDER=deepseek
RETRIEVAL__NORMALIZER_LLM__MODEL_ID=deepseek-v4-pro
RETRIEVAL__NORMALIZER_LLM__BASE_URL=https://api.deepseek.com/v1
RETRIEVAL__NORMALIZER_LLM__TIMEOUT=30
RETRIEVAL__NORMALIZER_LLM__MAX_RETRIES=3
RETRIEVAL__NORMALIZER_LLM__PRIVACY_ACKNOWLEDGED=true

# Embedding 配置
RETRIEVAL__EMBEDDING__PROVIDER=aliyun
RETRIEVAL__EMBEDDING__MODEL_ID=bge-large-zh
RETRIEVAL__EMBEDDING__BASE_URL=https://dashscope.aliyuncs.com/api/v1
RETRIEVAL__EMBEDDING__TIMEOUT=60
RETRIEVAL__EMBEDDING__MAX_RETRIES=3
RETRIEVAL__EMBEDDING__BATCH_SIZE=32
RETRIEVAL__EMBEDDING__PRIVACY_ACKNOWLEDGED=true

# Reranker 配置
RETRIEVAL__RERANKER__PROVIDER=aliyun
RETRIEVAL__RERANKER__MODEL_ID=qwen3-reranker-8b
RETRIEVAL__RERANKER__BASE_URL=https://dashscope.aliyuncs.com/api/v1
RETRIEVAL__RERANKER__TIMEOUT=45
RETRIEVAL__RERANKER__MAX_RETRIES=2
RETRIEVAL__RERANKER__MAX_CANDIDATES=100
RETRIEVAL__RERANKER__PRIVACY_ACKNOWLEDGED=true
```

### 3. 依赖注入示例

在服务初始化时显式传递配置：

```python
# backend/app/retrieval/service.py

from app.core.config import settings
from app.common.llm_client import LLMClient


class RecommendationService:
    def __init__(self):
        # 显式传递 normalizer 配置
        self.normalizer = QueryNormalizer(
            llm_client=LLMClient(settings.retrieval.normalizer_llm)
        )
        
        # 显式传递 reranker 配置
        self.reranker = RerankerClient(
            config=settings.retrieval.reranker
        )
        
        # 显式传递聚合权重
        self.aggregator = ScoreAggregator(
            default_weights=settings.retrieval.default_weights
        )
```

### 4. 共享 LLM 客户端的配置隔离

`backend/app/common/llm_client.py` 应支持配置命名空间：

```python
# backend/app/common/llm_client.py

from typing import Union
from app.core.config import NormalizerLLMConfig, EmbeddingConfig, RerankerConfig


class LLMClient:
    """
    共享 LLM 客户端基础设施
    
    职责：
    - HTTP 调用
    - 重试逻辑
    - 超时处理
    - 错误映射
    
    通过配置对象实现命名空间隔离
    """
    
    def __init__(self, config: Union[NormalizerLLMConfig, EmbeddingConfig, RerankerConfig]):
        """
        Args:
            config: 独立的配置对象（NormalizerLLMConfig/EmbeddingConfig/RerankerConfig）
        """
        self.config = config
        self.provider = config.provider
        self.model_id = config.model_id
        self.base_url = config.base_url
        self.timeout = config.timeout
        self.max_retries = config.max_retries
        
        # 初始化 HTTP 客户端
        self._init_http_client()
    
    def call(self, prompt: str, **kwargs):
        """执行 LLM 调用"""
        # 实现略
        pass
```

## 验证方法

### 单元测试

```python
# tests/retrieval/test_config_isolation.py

def test_normalizer_config_isolation():
    """验证修改 normalizer 配置不影响其他模型"""
    # 修改 normalizer 超时
    settings.retrieval.normalizer_llm.timeout = 60
    
    # 验证其他配置未变
    assert settings.retrieval.embedding.timeout == 60  # 原值
    assert settings.retrieval.reranker.timeout == 45   # 原值


def test_config_objects_are_independent():
    """验证三个配置对象是独立实例"""
    normalizer_config = settings.retrieval.normalizer_llm
    embedding_config = settings.retrieval.embedding
    reranker_config = settings.retrieval.reranker
    
    # 验证不是同一对象
    assert normalizer_config is not embedding_config
    assert embedding_config is not reranker_config
    assert normalizer_config is not reranker_config
```

### 契约测试

```python
# tests/retrieval/test_config_contract.py

def test_llm_client_receives_correct_config():
    """验证 LLMClient 接收到正确的配置命名空间"""
    normalizer_client = LLMClient(settings.retrieval.normalizer_llm)
    
    assert normalizer_client.model_id == "deepseek-v4-pro"
    assert normalizer_client.timeout == 30
    
    # 修改 reranker 配置不应影响已创建的 normalizer 客户端
    settings.retrieval.reranker.timeout = 100
    assert normalizer_client.timeout == 30  # 未变
```

## 实施检查清单

- [ ] 在 `config.py` 中定义三个独立配置类
- [ ] 配置类包含所有必需字段（provider/model_id/base_url/timeout/retry）
- [ ] 环境变量使用嵌套分隔符（`__`）区分命名空间
- [ ] 依赖注入时显式传递配置对象
- [ ] 共享 `LLMClient` 通过配置对象实现隔离
- [ ] 单元测试覆盖配置隔离验证
- [ ] 契约测试覆盖配置串用回归检测

## 常见陷阱

❌ **错误做法**：三者共享同一配置对象

```python
# 错误示例
class AIConfig(BaseModel):
    provider: str
    model_id: str
    # ...

settings.ai_config = AIConfig(...)  # 所有模型共享

# 问题：修改一处影响全局
settings.ai_config.timeout = 100  # 影响所有模型！
```

✅ **正确做法**：每类模型独立配置对象

```python
# 正确示例
settings.retrieval.normalizer_llm = NormalizerLLMConfig(...)
settings.retrieval.embedding = EmbeddingConfig(...)
settings.retrieval.reranker = RerankerConfig(...)

# 修改互不影响
settings.retrieval.reranker.timeout = 100  # 只影响 reranker
```

## 参考资料

- Pydantic Settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- 依赖注入模式: https://fastapi.tiangolo.com/tutorial/dependencies/

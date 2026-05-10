"""Embedding 生产路径运行时守卫（Req 6.4）。

与 ``pgvector_checks`` 并列：在启动或启用远程嵌入前调用，避免配置不全仍走生产外发。
"""

from __future__ import annotations

from app.core.config import EmbeddingConfig, EmbeddingConfigStatus, get_embedding_config_status
from app.core.errors import ErrorCode


class EmbeddingConfigMissingError(Exception):
    """远程嵌入配置不足以安全启用生产向量化。"""

    def __init__(self, *, error_code: str) -> None:
        """保存对外稳定错误码。"""
        self.error_code = error_code
        super().__init__(error_code)


def assert_embedding_production_config_or_fail(cfg: EmbeddingConfig) -> None:
    """非 fake/test 密钥视为拟启用生产路径：必须能通过 ``get_embedding_config_status`` 校验。

    空密钥或 ``fake``/``test`` 约定为本地开发桩，不在此抛错。

    Args:
        cfg: Embedding 运行时配置。

    Returns:
        ``None``。

    Raises:
        EmbeddingConfigMissingError: 有效密钥但隐私未确认等导致 ``config_missing``。
    """
    key = (cfg.api_key or "").strip()
    if not key or key.lower() in ("fake", "test"):
        return
    if get_embedding_config_status(cfg) == EmbeddingConfigStatus.CONFIG_MISSING:
        raise EmbeddingConfigMissingError(error_code=ErrorCode.EMBEDDING_CONFIG_MISSING)

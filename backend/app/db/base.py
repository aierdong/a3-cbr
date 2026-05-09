"""ORM 基类模块。.

汇总所有 ORM 模型使用的基类，并导入所有 ORM 模型
以确保 Base.metadata 包含全部表定义。
"""
from app.db.session import Base

# 导入增强 ORM 模型，使其注册到 Base.metadata
from app.enrichment import models as enrichment_models  # noqa: F401

# 导出 Base 供其他模块使用
__all__ = ["Base"]
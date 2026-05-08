"""ORM 基类模块。.

汇总所有 ORM 模型使用的基类。
"""
from app.db.session import Base

# 导出 Base 供其他模块使用
__all__ = ["Base"]
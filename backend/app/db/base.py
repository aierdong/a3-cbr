"""ORM 基类模块。.

汇总所有 ORM 模型使用的基类，并导入所有 ORM 模型
以确保 Base.metadata 包含全部表定义。
"""
from app.db.session import Base

# 导入案例 ORM，使其注册到 Base.metadata（测试夹具 create_all / drop_all 依赖完整元数据）
from app.cases import models as cases_models  # noqa: F401

# 导入增强 ORM 模型，使其注册到 Base.metadata
from app.enrichment import models as enrichment_models  # noqa: F401

# 导入向量索引 ORM 模型，使其注册到 Base.metadata
from app.vector_indexing import models as vector_indexing_models  # noqa: F401

# 导入检索推荐 ORM 模型，使其注册到 Base.metadata
from app.retrieval import models as retrieval_models  # noqa: F401

# 导入推荐反馈 ORM 模型，使其注册到 Base.metadata
from app.feedback import models as feedback_models  # noqa: F401

# 导出 Base 供其他模块使用
__all__ = ["Base"]

"""A3 案例和门店信息 ORM 模型。

本模块定义门店信息只读镜像表和 A3 案例基础表的 SQLAlchemy 模型。
"""
import enum

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class CaseStatus(str, enum.Enum):
    """案例状态枚举。"""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ProblemType(str, enum.Enum):
    """问题类型枚举（MVP 受控枚举）。"""

    CUSTOMER_COMPLAINT = "customer_complaint"
    SERVICE_QUALITY = "service_quality"
    OPERATIONS = "operations"
    ENVIRONMENT = "environment"
    PRODUCT_QUALITY = "product_quality"
    SAFETY_HYGIENE = "safety_hygiene"
    STAFF_TRAINING = "staff_training"
    EQUIPMENT_MAINTENANCE = "equipment_maintenance"
    OTHER = "other"


class OutcomeResult(str, enum.Enum):
    """效果结果枚举。"""

    IMPROVED = "improved"
    NO_CHANGE = "no_change"
    UNKNOWN = "unknown"


class StoreInfo(Base):
    """门店信息只读镜像表。

    该表为外部门店主数据在本库的只读镜像，业务数据由外部同步写入。
    本规格的案例模块不负责该表的写入操作。
    """

    __tablename__ = "store_infos"

    store_id = Column(String(64), primary_key=True)
    store_name = Column(String(255), nullable=False)
    brand_id = Column(String(64), nullable=False)
    brand_name = Column(String(255), nullable=False)
    business_type = Column(String(64), nullable=False)
    store_scale = Column(String(64), nullable=False)
    franchise_type = Column(String(32), nullable=False)
    city = Column(String(128), nullable=False)
    city_tier = Column(String(32), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_store_infos_brand_id", "brand_id"),
        Index("ix_store_infos_business_type", "business_type"),
        Index("ix_store_infos_store_scale", "store_scale"),
        Index("ix_store_infos_franchise_type", "franchise_type"),
        Index("ix_store_infos_city", "city"),
        Index("ix_store_infos_city_tier", "city_tier"),
    )


class A3Case(Base):
    """A3 案例基础表。

    包含案例标识、A3 基础字段、状态、时间戳和门店信息关联。
    不包含 AI、标签、向量、推荐或反馈字段。
    """

    __tablename__ = "a3_cases"

    case_id = Column(String(64), primary_key=True)
    problem_description = Column(Text, nullable=False)
    store_id = Column(
        String(64),
        ForeignKey("store_infos.store_id", ondelete="RESTRICT"),
        nullable=False,
    )
    problem_type = Column(String(64), nullable=False)
    context = Column(Text, nullable=False)  # JSONB stored as text
    root_cause = Column(Text, nullable=False)
    solution_steps = Column(Text, nullable=False)  # JSONB stored as text
    outcome = Column(Text, nullable=False)  # JSONB stored as text
    status = Column(String(32), nullable=False, default=CaseStatus.DRAFT.value)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 关联门店信息（只读，不执行写入）
    store = relationship("StoreInfo", lazy="joined")

    __table_args__ = (
        Index("ix_a3_cases_store_id", "store_id"),
        Index("ix_a3_cases_problem_type", "problem_type"),
        Index("ix_a3_cases_status", "status"),
        Index("ix_a3_cases_created_at", "created_at"),
        Index("ix_a3_cases_created_at_case_id", "created_at", "case_id"),
    )

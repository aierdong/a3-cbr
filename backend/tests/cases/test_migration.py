"""数据库迁移和表结构测试。

验证 store_infos 和 a3_cases 表结构、索引和约束是否符合设计规范。
"""
from app.cases.models import A3Case, CaseStatus, ProblemType, StoreInfo


class TestStoreInfoModel:
    """验证 StoreInfo 模型定义。"""

    def test_tablename_is_store_infos(self):
        """表名应为 store_infos。"""
        assert StoreInfo.__tablename__ == "store_infos"

    def test_columns_match_design(self):
        """字段应与 Physical Data Model 一致。"""
        columns = {c.name for c in StoreInfo.__table__.columns}
        expected = {
            "store_id",
            "store_name",
            "brand_id",
            "brand_name",
            "business_type",
            "store_scale",
            "franchise_type",
            "city",
            "city_tier",
            "updated_at",
        }
        assert columns == expected

    def test_store_id_is_primary_key(self):
        """store_id 是主键。"""
        pk = StoreInfo.__table__.primary_key
        assert pk is not None
        assert len(pk.columns) == 1
        assert list(pk.columns)[0].name == "store_id"

    def test_all_columns_not_nullable(self):
        """除 updated_at 外所有字段均不可为空。"""
        for col in StoreInfo.__table__.columns:
            if col.name != "updated_at":
                assert not col.nullable, f"{col.name} should not be nullable"


class TestA3CaseModel:
    """验证 A3Case 模型定义。"""

    def test_tablename_is_a3_cases(self):
        """表名应为 a3_cases。"""
        assert A3Case.__tablename__ == "a3_cases"

    def test_columns_match_design(self):
        """字段应与 Physical Data Model 一致。"""
        columns = {c.name for c in A3Case.__table__.columns}
        expected = {
            "case_id",
            "problem_description",
            "store_id",
            "problem_type",
            "context",
            "root_cause",
            "solution_steps",
            "outcome",
            "status",
            "created_at",
            "updated_at",
        }
        assert columns == expected

    def test_case_id_is_primary_key(self):
        """case_id 是主键。"""
        pk = A3Case.__table__.primary_key
        assert pk is not None
        assert len(pk.columns) == 1
        assert list(pk.columns)[0].name == "case_id"

    def test_store_id_is_foreign_key(self):
        """store_id 是指向 store_infos.store_id 的外键。"""
        fk = A3Case.__table__.foreign_keys
        assert len(fk) == 1
        assert list(fk)[0].target_fullname == "store_infos.store_id"

    def test_all_columns_not_nullable(self):
        """所有字段均不可为空。"""
        for col in A3Case.__table__.columns:
            assert not col.nullable, f"{col.name} should not be nullable"


class TestStoreInfoIndexes:
    """验证 store_infos 表索引。"""

    def test_brand_id_index_exists(self):
        """brand_id 索引应存在。"""
        indexes = {idx.name for idx in StoreInfo.__table__.indexes}
        assert "ix_store_infos_brand_id" in indexes

    def test_business_type_index_exists(self):
        """business_type 索引应存在。"""
        indexes = {idx.name for idx in StoreInfo.__table__.indexes}
        assert "ix_store_infos_business_type" in indexes

    def test_store_scale_index_exists(self):
        """store_scale 索引应存在。"""
        indexes = {idx.name for idx in StoreInfo.__table__.indexes}
        assert "ix_store_infos_store_scale" in indexes

    def test_franchise_type_index_exists(self):
        """franchise_type 索引应存在。"""
        indexes = {idx.name for idx in StoreInfo.__table__.indexes}
        assert "ix_store_infos_franchise_type" in indexes

    def test_city_index_exists(self):
        """city 索引应存在。"""
        indexes = {idx.name for idx in StoreInfo.__table__.indexes}
        assert "ix_store_infos_city" in indexes

    def test_city_tier_index_exists(self):
        """city_tier 索引应存在。"""
        indexes = {idx.name for idx in StoreInfo.__table__.indexes}
        assert "ix_store_infos_city_tier" in indexes

    def test_index_count(self):
        """store_infos 应有 6 个索引。"""
        # 6 single-column indexes (primary key index not included in __table__.indexes)
        assert len(StoreInfo.__table__.indexes) == 6


class TestA3CaseIndexes:
    """验证 a3_cases 表索引。"""

    def test_store_id_index_exists(self):
        """store_id 索引应存在。"""
        indexes = {idx.name for idx in A3Case.__table__.indexes}
        assert "ix_a3_cases_store_id" in indexes

    def test_problem_type_index_exists(self):
        """problem_type 索引应存在。"""
        indexes = {idx.name for idx in A3Case.__table__.indexes}
        assert "ix_a3_cases_problem_type" in indexes

    def test_status_index_exists(self):
        """status 索引应存在。"""
        indexes = {idx.name for idx in A3Case.__table__.indexes}
        assert "ix_a3_cases_status" in indexes

    def test_created_at_index_exists(self):
        """created_at 索引应存在。"""
        indexes = {idx.name for idx in A3Case.__table__.indexes}
        assert "ix_a3_cases_created_at" in indexes

    def test_composite_created_at_case_id_index_exists(self):
        """(created_at, case_id) 复合索引应存在。"""
        indexes = {idx.name for idx in A3Case.__table__.indexes}
        assert "ix_a3_cases_created_at_case_id" in indexes

    def test_index_count(self):
        """a3_cases 应有 5 个索引。"""
        # 4 single + 1 composite (PK index excluded)
        assert len(A3Case.__table__.indexes) == 5


class TestCaseStatusEnum:
    """验证 CaseStatus 枚举定义。"""

    def test_draft_status_exists(self):
        """Draft 状态应存在。"""
        assert CaseStatus.DRAFT.value == "draft"

    def test_active_status_exists(self):
        """Active 状态应存在。"""
        assert CaseStatus.ACTIVE.value == "active"

    def test_archived_status_exists(self):
        """Archived 状态应存在。"""
        assert CaseStatus.ARCHIVED.value == "archived"

    def test_status_count(self):
        """应有 3 个状态。"""
        assert len(CaseStatus) == 3


class TestProblemTypeEnum:
    """验证 ProblemType 枚举定义。"""

    def test_problem_types_exist(self):
        """问题类型枚举应包含预期值。"""
        expected_types = {
            "customer_complaint",
            "service_quality",
            "operations",
            "environment",
            "product_quality",
            "safety_hygiene",
            "staff_training",
            "equipment_maintenance",
            "other",
        }
        actual_types = {pt.value for pt in ProblemType}
        assert actual_types == expected_types

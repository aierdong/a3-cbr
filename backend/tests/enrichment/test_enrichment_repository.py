"""EnrichmentRepository 持久化测试。

使用真实数据库会话验证仓储层的原子性和正确性：
- create_run: 创建运行记录
- complete_run: 完成运行（原子性删除旧结果 + 写入新结果）
- fail_run: 标记运行失败
- mark_retryable: 标记可重试
- get_current_result: 查询当前有效结果
- get_run: 查询运行记录
- delete_enrichment_data: 删除派生数据（原子性 + 幂等性）

Requirements: 1.3, 2.4, 4.3, 4.4, 4.5, 4.6, 7.2, 7.3
Boundary: EnrichmentRepository
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.enrichment.models import CaseEnrichmentResult
from app.enrichment.repository import EnrichmentRepository
from app.enrichment.schemas import (
    CaseEnrichmentResultCreate,
    EnrichmentErrorData,
    EnrichmentRunCreate,
    EnrichmentStatus,
    ErrorStage,
    RequestPurpose,
    RunStatus,
    SourceField,
    TaskType,
)


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_run_create(
    run_id: str = "run_001",
    case_id: str = "case_001",
    status: RunStatus = RunStatus.RUNNING,
) -> EnrichmentRunCreate:
    return EnrichmentRunCreate(
        run_id=run_id,
        case_id=case_id,
        task_type=TaskType.CASE_ENRICHMENT,
        status=status,
        model_id="deepseek-v4-flash",
        request_purpose=RequestPurpose.CASE_ENRICHMENT,
        case_updated_at=_utc_now(),
    )


def _make_result_create(
    enrichment_id: str = "enrich_001",
    case_id: str = "case_001",
    problem_summary: str = "问题摘要",
    solution_summary: str = "方案摘要",
) -> CaseEnrichmentResultCreate:
    return CaseEnrichmentResultCreate(
        enrichment_id=enrichment_id,
        case_id=case_id,
        case_updated_at=_utc_now(),
        status=EnrichmentStatus.VALID,
        problem_summary=problem_summary,
        solution_summary=solution_summary,
        structured_suggestions={
            "problem_type_suggestion": "客户投诉",
            "root_cause_category": "服务流程",
            "applicable_scenarios": ["门店运营"],
            "confidence_notes": "基于案例内容分析",
        },
        tag_suggestions=["服务", "投诉"],
        source_references=[
            SourceField.PROBLEM_DESCRIPTION,
            SourceField.ROOT_CAUSE,
        ],
        output_version="1.0",
    )


# ===========================================================================
# create_run 测试
# ===========================================================================


class TestCreateRun:
    """测试 create_run 创建运行记录。"""

    @pytest.mark.asyncio
    async def test_create_run_persists_record(self, db_session):
        """创建运行记录应正确持久化到数据库。"""
        repo = EnrichmentRepository(db_session)
        run_create = _make_run_create()

        record = await repo.create_run(run_create)
        await db_session.commit()

        assert record.run_id == "run_001"
        assert record.case_id == "case_001"
        assert record.task_type == TaskType.CASE_ENRICHMENT
        assert record.status == RunStatus.RUNNING
        assert record.model_id == "deepseek-v4-flash"
        assert record.request_purpose == RequestPurpose.CASE_ENRICHMENT

        # 验证可从数据库重新查询
        fetched = await repo.get_run("run_001")
        assert fetched is not None
        assert fetched.run_id == "run_001"
        assert fetched.case_id == "case_001"


# ===========================================================================
# fail_run 测试
# ===========================================================================


class TestFailRun:
    """测试 fail_run 标记运行失败。"""

    @pytest.mark.asyncio
    async def test_fail_run_updates_status_and_error(self, db_session):
        """标记运行失败应更新状态、错误码和错误阶段。"""
        repo = EnrichmentRepository(db_session)
        await repo.create_run(_make_run_create())
        await db_session.commit()

        error = EnrichmentErrorData(
            error_code="LLM_TIMEOUT",
            error_stage=ErrorStage.LLM_CALL,
        )
        record = await repo.fail_run("run_001", error)
        await db_session.commit()

        assert record.status == RunStatus.FAILED
        assert record.error_code == "LLM_TIMEOUT"
        assert record.error_stage == ErrorStage.LLM_CALL
        assert record.finished_at is not None

        # 验证持久化
        fetched = await repo.get_run("run_001")
        assert fetched.status == RunStatus.FAILED
        assert fetched.error_code == "LLM_TIMEOUT"

    @pytest.mark.asyncio
    async def test_fail_run_nonexistent_raises(self, db_session):
        """标记不存在的运行失败应抛出 ValueError。"""
        repo = EnrichmentRepository(db_session)

        error = EnrichmentErrorData(
            error_code="INTERNAL_ERROR",
            error_stage=ErrorStage.PERSIST,
        )
        with pytest.raises(ValueError, match="运行记录不存在"):
            await repo.fail_run("nonexistent_run", error)


# ===========================================================================
# mark_retryable 测试
# ===========================================================================


class TestMarkRetryable:
    """测试 mark_retryable 标记可重试。"""

    @pytest.mark.asyncio
    async def test_mark_retryable_updates_status(self, db_session):
        """标记可重试应更新状态为 retryable。"""
        repo = EnrichmentRepository(db_session)
        await repo.create_run(_make_run_create())
        await db_session.commit()

        error = EnrichmentErrorData(
            error_code="LLM_RATE_LIMITED",
            error_stage=ErrorStage.LLM_CALL,
        )
        record = await repo.mark_retryable("run_001", error)
        await db_session.commit()

        assert record.status == RunStatus.RETRYABLE
        assert record.error_code == "LLM_RATE_LIMITED"
        assert record.error_stage == ErrorStage.LLM_CALL
        assert record.finished_at is not None


# ===========================================================================
# complete_run 测试
# ===========================================================================


class TestCompleteRun:
    """测试 complete_run 完成增强运行。

    验证事务原子性：删除旧结果 + 写入新结果 + 更新运行状态。
    Requirements: 4.3, 4.6
    """

    @pytest.mark.asyncio
    async def test_complete_run_stores_valid_result(self, db_session):
        """完成运行应存储 valid 派生结果并更新运行状态为 succeeded。"""
        repo = EnrichmentRepository(db_session)
        await repo.create_run(_make_run_create())
        await db_session.commit()

        result_create = _make_result_create()
        run_record = await repo.complete_run("run_001", result_create)
        await db_session.commit()

        # 运行记录应为 succeeded
        assert run_record.status == RunStatus.SUCCEEDED
        assert run_record.finished_at is not None

        # 应可查询到有效结果
        result = await repo.get_current_result("case_001")
        assert result is not None
        assert result.enrichment_id == "enrich_001"
        assert result.case_id == "case_001"
        assert result.status == EnrichmentStatus.VALID
        assert result.problem_summary == "问题摘要"
        assert result.solution_summary == "方案摘要"
        assert result.output_version == "1.0"

    @pytest.mark.asyncio
    async def test_re_enrichment_deletes_old_result_before_writing_new(
        self,
        db_session,
    ):
        """同一 case_id 重复增强时，新 valid 结果写入前旧记录应被删除。

        验证事务原子性：complete_run 在同一事务内删除旧结果再写入新结果。
        Requirement: 4.6
        """
        repo = EnrichmentRepository(db_session)

        # 第一次增强
        await repo.create_run(_make_run_create(run_id="run_001"))
        await db_session.commit()
        result_1 = _make_result_create(
            enrichment_id="enrich_001",
            problem_summary="第一次问题摘要",
        )
        await repo.complete_run("run_001", result_1)
        await db_session.commit()

        # 验证第一次结果存在
        first_result = await repo.get_current_result("case_001")
        assert first_result is not None
        assert first_result.enrichment_id == "enrich_001"
        assert first_result.problem_summary == "第一次问题摘要"

        # 第二次增强（同一 case_id）
        await repo.create_run(_make_run_create(run_id="run_002"))
        await db_session.commit()
        result_2 = _make_result_create(
            enrichment_id="enrich_002",
            problem_summary="第二次问题摘要",
        )
        await repo.complete_run("run_002", result_2)
        await db_session.commit()

        # 验证旧结果已被删除，只有新结果存在
        second_result = await repo.get_current_result("case_001")
        assert second_result is not None
        assert second_result.enrichment_id == "enrich_002"
        assert second_result.problem_summary == "第二次问题摘要"

        # 旧 enrichment_id 不应存在于数据库中
        old_result_stmt = select(CaseEnrichmentResult).where(
            CaseEnrichmentResult.enrichment_id == "enrich_001",
        )
        old_result = await db_session.execute(old_result_stmt)
        assert old_result.scalar_one_or_none() is None

        # 运行记录应都存在（只删除派生结果，不删除运行记录）
        run_001 = await repo.get_run("run_001")
        run_002 = await repo.get_run("run_002")
        assert run_001 is not None
        assert run_002 is not None
        assert run_001.status == RunStatus.SUCCEEDED
        assert run_002.status == RunStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_complete_run_nonexistent_run_raises(self, db_session):
        """完成不存在的运行记录应抛出 ValueError。"""
        repo = EnrichmentRepository(db_session)

        result_create = _make_result_create()
        with pytest.raises(ValueError, match="运行记录不存在"):
            await repo.complete_run("nonexistent_run", result_create)


# ===========================================================================
# get_current_result 测试
# ===========================================================================


class TestGetCurrentResult:
    """测试 get_current_result 查询当前有效结果。"""

    @pytest.mark.asyncio
    async def test_get_current_result_returns_valid(self, db_session):
        """应返回 status=valid 的派生结果。"""
        repo = EnrichmentRepository(db_session)
        await repo.create_run(_make_run_create())
        await db_session.commit()
        await repo.complete_run("run_001", _make_result_create())
        await db_session.commit()

        result = await repo.get_current_result("case_001")
        assert result is not None
        assert result.case_id == "case_001"
        assert result.status == EnrichmentStatus.VALID

    @pytest.mark.asyncio
    async def test_get_current_result_returns_none_when_no_result(self, db_session):
        """无派生结果时应返回 None。"""
        repo = EnrichmentRepository(db_session)

        result = await repo.get_current_result("nonexistent_case")
        assert result is None


# ===========================================================================
# delete_enrichment_data 测试
# ===========================================================================


class TestDeleteEnrichmentData:
    """测试 delete_enrichment_data 删除派生数据。

    验证事务原子性：在同一事务内删除派生结果和运行记录。
    验证幂等性：删除不存在的数据返回 deleted_count=0。
    Requirements: 7.2, 7.3
    """

    @pytest.mark.asyncio
    async def test_delete_by_case_id_removes_results_and_runs(self, db_session):
        """按 case_id 删除应删除该案例的所有派生结果和运行记录。"""
        repo = EnrichmentRepository(db_session)

        # 创建运行记录和派生结果
        await repo.create_run(_make_run_create(run_id="run_001"))
        await db_session.commit()
        await repo.complete_run("run_001", _make_result_create())
        await db_session.commit()

        # 创建第二个运行记录（模拟重试后的新运行）
        await repo.create_run(_make_run_create(run_id="run_002"))
        await db_session.commit()

        # 删除
        result = await repo.delete_enrichment_data(case_id="case_001")
        await db_session.commit()

        assert result.success is True
        # 应删除 1 个派生结果 + 2 个运行记录 = 3
        assert result.deleted_count == 3

        # 验证派生结果已删除
        enrichment = await repo.get_current_result("case_001")
        assert enrichment is None

        # 验证运行记录已删除
        run_001 = await repo.get_run("run_001")
        run_002 = await repo.get_run("run_002")
        assert run_001 is None
        assert run_002 is None

    @pytest.mark.asyncio
    async def test_delete_by_enrichment_id_removes_specific_record(self, db_session):
        """按 enrichment_id 删除应删除特定派生结果及其关联运行记录。"""
        repo = EnrichmentRepository(db_session)

        await repo.create_run(_make_run_create(run_id="run_001"))
        await db_session.commit()
        await repo.complete_run(
            "run_001",
            _make_result_create(enrichment_id="enrich_001"),
        )
        await db_session.commit()

        result = await repo.delete_enrichment_data(enrichment_id="enrich_001")
        await db_session.commit()

        assert result.success is True
        # 应删除 1 个派生结果 + 1 个运行记录 = 2
        assert result.deleted_count == 2

        enrichment = await repo.get_current_result("case_001")
        assert enrichment is None

    @pytest.mark.asyncio
    async def test_delete_idempotent_for_nonexistent_case(self, db_session):
        """删除不存在的案例派生数据应返回 deleted_count=0（幂等性）。"""
        repo = EnrichmentRepository(db_session)

        result = await repo.delete_enrichment_data(case_id="nonexistent_case")
        await db_session.commit()

        assert result.success is True
        assert result.deleted_count == 0
        assert result.deleted_at is not None

    @pytest.mark.asyncio
    async def test_delete_idempotent_for_nonexistent_enrichment_id(self, db_session):
        """删除不存在的 enrichment_id 应返回 deleted_count=0（幂等性）。"""
        repo = EnrichmentRepository(db_session)

        result = await repo.delete_enrichment_data(
            enrichment_id="nonexistent_enrich",
        )
        await db_session.commit()

        assert result.success is True
        assert result.deleted_count == 0

    @pytest.mark.asyncio
    async def test_delete_twice_returns_zero_second_time(self, db_session):
        """已删除的案例再次删除应返回 deleted_count=0（幂等性）。"""
        repo = EnrichmentRepository(db_session)

        # 创建并删除
        await repo.create_run(_make_run_create())
        await db_session.commit()
        await repo.complete_run("run_001", _make_result_create())
        await db_session.commit()

        first_delete = await repo.delete_enrichment_data(case_id="case_001")
        await db_session.commit()
        assert first_delete.deleted_count > 0

        # 第二次删除
        second_delete = await repo.delete_enrichment_data(case_id="case_001")
        await db_session.commit()
        assert second_delete.success is True
        assert second_delete.deleted_count == 0

    @pytest.mark.asyncio
    async def test_delete_no_ids_raises_value_error(self, db_session):
        """未提供 case_id 或 enrichment_id 应抛出 ValueError。"""
        repo = EnrichmentRepository(db_session)

        with pytest.raises(ValueError, match="至少提供"):
            await repo.delete_enrichment_data()

    @pytest.mark.asyncio
    async def test_delete_atomicity_removes_all_or_nothing(self, db_session):
        """删除操作应原子性地删除派生结果和运行记录。

        验证：删除后派生结果和运行记录都不存在。
        Requirement: 7.2
        """
        repo = EnrichmentRepository(db_session)

        # 创建带完整数据的案例
        await repo.create_run(_make_run_create(run_id="run_001"))
        await db_session.commit()
        await repo.complete_run("run_001", _make_result_create())
        await db_session.commit()

        # 验证数据存在
        assert await repo.get_current_result("case_001") is not None
        assert await repo.get_run("run_001") is not None

        # 删除
        result = await repo.delete_enrichment_data(case_id="case_001")
        await db_session.commit()

        # 验证派生结果和运行记录都被删除（原子性）
        assert await repo.get_current_result("case_001") is None
        assert await repo.get_run("run_001") is None
        assert result.success is True
        assert result.deleted_count == 2  # 1 result + 1 run


# ===========================================================================
# 派生内容独立性测试
# ===========================================================================


class TestDerivedContentIsolation:
    """验证派生内容保存在独立结构中，不反写案例基础字段。

    Requirements: 2.5, 3.4
    """

    @pytest.mark.asyncio
    async def test_derived_content_stored_in_enrichment_tables_only(self, db_session):
        """派生内容应仅存储在 case_enrichment_results 表中。"""
        repo = EnrichmentRepository(db_session)

        await repo.create_run(_make_run_create())
        await db_session.commit()
        result_create = _make_result_create()
        await repo.complete_run("run_001", result_create)
        await db_session.commit()

        # 查询派生结果
        result = await repo.get_current_result("case_001")
        assert result is not None

        # 验证派生内容字段都存在于派生结果中
        assert result.problem_summary == "问题摘要"
        assert result.solution_summary == "方案摘要"
        assert result.structured_suggestions is not None
        assert result.tag_suggestions == ["服务", "投诉"]
        assert result.source_references is not None
        assert result.output_version == "1.0"

        # 验证派生结果表不包含案例基础字段（如 store_id、brand_id 等）
        # 这是通过 ORM 模型定义保证的：CaseEnrichmentResult 只有派生字段
        result_columns = {
            col.name for col in CaseEnrichmentResult.__table__.columns
        }
        # 派生结果表不应包含案例基础管理字段
        assert "store_id" not in result_columns
        assert "brand_id" not in result_columns
        assert "store_name" not in result_columns
        # 应包含 case_id 作为外键引用（不是基础字段本身）
        assert "case_id" in result_columns
        # 应包含派生内容字段
        assert "problem_summary" in result_columns
        assert "solution_summary" in result_columns
        assert "structured_suggestions" in result_columns
        assert "tag_suggestions" in result_columns

    @pytest.mark.asyncio
    async def test_enrichment_result_has_no_write_back_to_case(self, db_session):
        """增强结果保存时不应修改 a3_cases 表。

        验证 complete_run 只操作 enrichment 相关表。
        """
        repo = EnrichmentRepository(db_session)

        await repo.create_run(_make_run_create())
        await db_session.commit()
        await repo.complete_run("run_001", _make_result_create())
        await db_session.commit()

        # 查询 a3_cases 表，验证没有被插入任何记录
        from app.cases.models import A3Case

        stmt = select(func.count()).select_from(A3Case)
        result = await db_session.execute(stmt)
        case_count = result.scalar()

        # 案例表中不应有记录（增强操作不创建或修改案例）
        assert case_count == 0

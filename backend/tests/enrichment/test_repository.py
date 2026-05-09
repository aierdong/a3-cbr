"""EnrichmentRepository 测试。

测试增强运行生命周期管理（创建、成功、失败）、
派生结果查询和删除能力。
Requirements: 1.3, 2.4, 3.4, 4.2, 4.3, 4.4, 4.5, 4.6, 6.3, 7.2, 7.3
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.enrichment.models import CaseEnrichmentResult, CaseEnrichmentRun
from app.enrichment.repository import EnrichmentRepository
from app.enrichment.schemas import (
    CaseEnrichmentResultCreate,
    EnrichmentErrorData,
    EnrichmentRunCreate,
    EnrichmentStatus,
    ErrorStage,
    RunStatus,
    TaskType,
    RequestPurpose,
)


# ---------------------------------------------------------------------------
# 测试辅助函数
# ---------------------------------------------------------------------------


def _make_utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _make_run_create(
    run_id: str = "run_001",
    case_id: str = "case_001",
    status: RunStatus = RunStatus.RUNNING,
) -> EnrichmentRunCreate:
    """创建测试用运行创建数据。"""
    return EnrichmentRunCreate(
        run_id=run_id,
        case_id=case_id,
        task_type=TaskType.CASE_ENRICHMENT,
        status=status,
        model_id="deepseek-v4-flash",
        request_purpose=RequestPurpose.CASE_ENRICHMENT,
        case_updated_at=_make_utc_now(),
    )


def _make_result_create(
    enrichment_id: str = "enrich_001",
    case_id: str = "case_001",
    status: EnrichmentStatus = EnrichmentStatus.VALID,
) -> CaseEnrichmentResultCreate:
    """创建测试用派生结果创建数据。"""
    return CaseEnrichmentResultCreate(
        enrichment_id=enrichment_id,
        case_id=case_id,
        case_updated_at=_make_utc_now(),
        status=status,
        problem_summary="问题摘要",
        solution_summary="方案摘要",
        structured_suggestions={
            "problem_type_suggestion": "客户投诉",
            "root_cause_category": "服务流程",
            "applicable_scenarios": ["门店运营"],
            "confidence_notes": "基于案例内容分析",
        },
        tag_suggestions=["服务", "投诉"],
        source_references=["problem_description", "root_cause"],
        output_version="1.0.0",
    )


# ---------------------------------------------------------------------------
# create_run 测试
# ---------------------------------------------------------------------------


class TestCreateRun:
    """测试创建增强运行记录。"""

    @pytest.mark.asyncio
    async def test_create_run_returns_record(self, db_session: AsyncSession):
        """创建运行记录应返回 ORM 对象。"""
        repo = EnrichmentRepository(db_session)
        run_data = _make_run_create()

        record = await repo.create_run(run_data)

        assert isinstance(record, CaseEnrichmentRun)
        assert record.run_id == "run_001"
        assert record.case_id == "case_001"
        assert record.status == RunStatus.RUNNING
        assert record.model_id == "deepseek-v4-flash"
        assert record.request_purpose == RequestPurpose.CASE_ENRICHMENT

    @pytest.mark.asyncio
    async def test_create_run_persists_to_db(self, db_session: AsyncSession):
        """创建的运行记录应可从数据库查询。"""
        repo = EnrichmentRepository(db_session)
        run_data = _make_run_create(run_id="run_002", case_id="case_002")

        await repo.create_run(run_data)
        await db_session.flush()

        record = await repo.get_run("run_002")
        assert record is not None
        assert record.run_id == "run_002"
        assert record.case_id == "case_002"


# ---------------------------------------------------------------------------
# complete_run 测试
# ---------------------------------------------------------------------------


class TestCompleteRun:
    """测试完成增强运行。"""

    @pytest.mark.asyncio
    async def test_complete_run_updates_status(self, db_session: AsyncSession):
        """完成运行应将状态更新为 succeeded。"""
        repo = EnrichmentRepository(db_session)
        run_data = _make_run_create(run_id="run_003")
        await repo.create_run(run_data)

        result_data = _make_result_create(
            enrichment_id="enrich_003",
            case_id="case_001",
        )
        record = await repo.complete_run("run_003", result_data)

        assert record.status == RunStatus.SUCCEEDED
        assert record.finished_at is not None

    @pytest.mark.asyncio
    async def test_complete_run_creates_result(self, db_session: AsyncSession):
        """完成运行应创建派生结果。"""
        repo = EnrichmentRepository(db_session)
        run_data = _make_run_create(run_id="run_004", case_id="case_004")
        await repo.create_run(run_data)

        result_data = _make_result_create(
            enrichment_id="enrich_004",
            case_id="case_004",
        )
        await repo.complete_run("run_004", result_data)
        await db_session.flush()

        result = await repo.get_current_result("case_004")
        assert result is not None
        assert result.enrichment_id == "enrich_004"
        assert result.status == EnrichmentStatus.VALID

    @pytest.mark.asyncio
    async def test_complete_run_deletes_old_result(self, db_session: AsyncSession):
        """完成运行应删除旧的派生结果（Requirement 4.6）。"""
        repo = EnrichmentRepository(db_session)

        # 创建第一次运行和结果
        run_data_1 = _make_run_create(run_id="run_005a", case_id="case_005")
        await repo.create_run(run_data_1)
        result_data_1 = _make_result_create(
            enrichment_id="enrich_005a",
            case_id="case_005",
        )
        await repo.complete_run("run_005a", result_data_1)
        await db_session.flush()

        # 创建第二次运行
        run_data_2 = _make_run_create(run_id="run_005b", case_id="case_005")
        await repo.create_run(run_data_2)
        result_data_2 = _make_result_create(
            enrichment_id="enrich_005b",
            case_id="case_005",
        )
        await repo.complete_run("run_005b", result_data_2)
        await db_session.flush()

        # 验证只有新结果存在
        result = await repo.get_current_result("case_005")
        assert result is not None
        assert result.enrichment_id == "enrich_005b"

        # 验证旧结果已删除
        from sqlalchemy import select

        stmt = select(CaseEnrichmentResult).where(
            CaseEnrichmentResult.enrichment_id == "enrich_005a",
        )
        old_result = await db_session.execute(stmt)
        assert old_result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_complete_run_raises_on_missing_run(self, db_session: AsyncSession):
        """完成不存在的运行应抛出 ValueError。"""
        repo = EnrichmentRepository(db_session)
        result_data = _make_result_create()

        with pytest.raises(ValueError, match="运行记录不存在"):
            await repo.complete_run("nonexistent_run", result_data)


# ---------------------------------------------------------------------------
# fail_run 测试
# ---------------------------------------------------------------------------


class TestFailRun:
    """测试标记增强运行失败。"""

    @pytest.mark.asyncio
    async def test_fail_run_updates_status(self, db_session: AsyncSession):
        """失败运行应将状态更新为 failed。"""
        repo = EnrichmentRepository(db_session)
        run_data = _make_run_create(run_id="run_006")
        await repo.create_run(run_data)

        error = EnrichmentErrorData(
            error_code="LLM_TIMEOUT",
            error_stage=ErrorStage.LLM_CALL,
        )
        record = await repo.fail_run("run_006", error)

        assert record.status == RunStatus.FAILED
        assert record.error_code == "LLM_TIMEOUT"
        assert record.error_stage == ErrorStage.LLM_CALL
        assert record.finished_at is not None

    @pytest.mark.asyncio
    async def test_fail_run_raises_on_missing_run(self, db_session: AsyncSession):
        """标记不存在的运行为失败应抛出 ValueError。"""
        repo = EnrichmentRepository(db_session)
        error = EnrichmentErrorData(
            error_code="LLM_TIMEOUT",
            error_stage=ErrorStage.LLM_CALL,
        )

        with pytest.raises(ValueError, match="运行记录不存在"):
            await repo.fail_run("nonexistent_run", error)


# ---------------------------------------------------------------------------
# get_current_result 测试
# ---------------------------------------------------------------------------


class TestGetCurrentResult:
    """测试查询当前有效派生结果。"""

    @pytest.mark.asyncio
    async def test_returns_valid_result(self, db_session: AsyncSession):
        """应返回 status=valid 的派生结果。"""
        repo = EnrichmentRepository(db_session)
        run_data = _make_run_create(run_id="run_007", case_id="case_007")
        await repo.create_run(run_data)
        result_data = _make_result_create(
            enrichment_id="enrich_007",
            case_id="case_007",
            status=EnrichmentStatus.VALID,
        )
        await repo.complete_run("run_007", result_data)
        await db_session.flush()

        result = await repo.get_current_result("case_007")
        assert result is not None
        assert result.enrichment_id == "enrich_007"
        assert result.status == EnrichmentStatus.VALID

    @pytest.mark.asyncio
    async def test_returns_none_for_no_result(self, db_session: AsyncSession):
        """不存在派生结果时应返回 None。"""
        repo = EnrichmentRepository(db_session)

        result = await repo.get_current_result("nonexistent_case")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_failed_result(self, db_session: AsyncSession):
        """status=failed 的结果不应被返回（Requirement 4.5）。"""
        repo = EnrichmentRepository(db_session)

        # 直接插入 failed 状态的结果
        result = CaseEnrichmentResult(
            enrichment_id="enrich_008",
            case_id="case_008",
            case_updated_at=_make_utc_now(),
            status=EnrichmentStatus.FAILED,
            problem_summary=None,
            solution_summary=None,
            structured_suggestions={},
            tag_suggestions=[],
            source_references=[],
            output_version="1.0.0",
        )
        db_session.add(result)
        await db_session.flush()

        current = await repo.get_current_result("case_008")
        assert current is None


# ---------------------------------------------------------------------------
# get_run 测试
# ---------------------------------------------------------------------------


class TestGetRun:
    """测试按 run_id 查询运行记录。"""

    @pytest.mark.asyncio
    async def test_returns_run_record(self, db_session: AsyncSession):
        """应返回指定 run_id 的运行记录。"""
        repo = EnrichmentRepository(db_session)
        run_data = _make_run_create(run_id="run_009")
        await repo.create_run(run_data)
        await db_session.flush()

        record = await repo.get_run("run_009")
        assert record is not None
        assert record.run_id == "run_009"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_run(self, db_session: AsyncSession):
        """不存在的 run_id 应返回 None。"""
        repo = EnrichmentRepository(db_session)

        record = await repo.get_run("nonexistent_run")
        assert record is None


# ---------------------------------------------------------------------------
# delete_enrichment_data 测试
# ---------------------------------------------------------------------------


class TestDeleteEnrichmentData:
    """测试删除增强数据（Requirement 7.2, 7.3）。"""

    @pytest.mark.asyncio
    async def test_delete_by_case_id(self, db_session: AsyncSession):
        """按 case_id 删除应删除所有派生结果和运行记录。"""
        repo = EnrichmentRepository(db_session)

        # 创建运行和结果
        run_data = _make_run_create(run_id="run_010", case_id="case_010")
        await repo.create_run(run_data)
        result_data = _make_result_create(
            enrichment_id="enrich_010",
            case_id="case_010",
        )
        await repo.complete_run("run_010", result_data)
        await db_session.flush()

        # 删除
        delete_result = await repo.delete_enrichment_data(case_id="case_010")

        assert delete_result.success is True
        assert delete_result.deleted_count == 2  # 1 result + 1 run
        assert delete_result.deleted_at is not None

        # 验证已删除
        result = await repo.get_current_result("case_010")
        assert result is None
        run = await repo.get_run("run_010")
        assert run is None

    @pytest.mark.asyncio
    async def test_delete_by_enrichment_id(self, db_session: AsyncSession):
        """按 enrichment_id 删除应删除派生结果和关联的运行记录。"""
        repo = EnrichmentRepository(db_session)

        # 创建运行和结果
        run_data = _make_run_create(run_id="run_011", case_id="case_011")
        await repo.create_run(run_data)
        result_data = _make_result_create(
            enrichment_id="enrich_011",
            case_id="case_011",
        )
        await repo.complete_run("run_011", result_data)
        await db_session.flush()

        # 删除
        delete_result = await repo.delete_enrichment_data(
            enrichment_id="enrich_011",
        )

        assert delete_result.success is True
        assert delete_result.deleted_count == 2  # 1 result + 1 run

        # 验证已删除
        result = await repo.get_current_result("case_011")
        assert result is None
        run = await repo.get_run("run_011")
        assert run is None

    @pytest.mark.asyncio
    async def test_delete_idempotent(self, db_session: AsyncSession):
        """删除不存在的数据应返回 deleted_count=0（Requirement 7.3）。"""
        repo = EnrichmentRepository(db_session)

        delete_result = await repo.delete_enrichment_data(case_id="nonexistent")

        assert delete_result.success is True
        assert delete_result.deleted_count == 0

    @pytest.mark.asyncio
    async def test_delete_raises_on_no_ids(self, db_session: AsyncSession):
        """未提供 case_id 或 enrichment_id 应抛出 ValueError。"""
        repo = EnrichmentRepository(db_session)

        with pytest.raises(ValueError, match="至少提供"):
            await repo.delete_enrichment_data()

    @pytest.mark.asyncio
    async def test_delete_multiple_runs(self, db_session: AsyncSession):
        """删除应同时删除同一 case_id 的所有运行记录。"""
        repo = EnrichmentRepository(db_session)

        # 创建多个运行记录
        for i in range(3):
            run_data = _make_run_create(
                run_id=f"run_012_{i}",
                case_id="case_012",
            )
            await repo.create_run(run_data)
        await db_session.flush()

        # 删除
        delete_result = await repo.delete_enrichment_data(case_id="case_012")

        assert delete_result.success is True
        assert delete_result.deleted_count == 3  # 3 runs

    @pytest.mark.asyncio
    async def test_delete_enrichment_id_not_found(self, db_session: AsyncSession):
        """删除不存在的 enrichment_id 应返回 deleted_count=0。"""
        repo = EnrichmentRepository(db_session)

        delete_result = await repo.delete_enrichment_data(
            enrichment_id="nonexistent_enrich",
        )

        assert delete_result.success is True
        assert delete_result.deleted_count == 0

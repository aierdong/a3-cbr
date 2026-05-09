"""CaseSnapshotProvider 测试。

测试上游案例快照读取的状态门控、错误映射和字段裁剪行为。
Requirements: 1.1, 1.2, 6.1
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.cases.schemas import (
    CaseDetailResponse,
    CaseStatus,
    ContextSchema,
    OutcomeSchema,
    ProblemType,
    SolutionStepSchema,
    StoreInfoSummary,
)
from app.cases.service import CaseNotFoundError
from app.enrichment.case_snapshot import (
    CaseSnapshotProvider,
    EnrichmentCaseNotFoundError,
    EnrichmentStateConflictError,
)
from app.enrichment.schemas import CaseInputSnapshot


# ---------------------------------------------------------------------------
# 测试辅助函数
# ---------------------------------------------------------------------------


def _make_utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _make_store_summary(
    store_id: str = "store_001",
) -> StoreInfoSummary:
    """创建测试用门店摘要。"""
    return StoreInfoSummary(
        store_id=store_id,
        store_name="测试门店",
        brand_id="brand_001",
        brand_name="测试品牌",
        business_type="火锅",
        store_scale="large",
        franchise_type="加盟",
        city="北京",
        city_tier="一线",
        updated_at=_make_utc_now(),
    )


def _make_case_detail(
    case_id: str = "case_001",
    status: CaseStatus = CaseStatus.ACTIVE,
    store_id: str = "store_001",
    problem_type: ProblemType = ProblemType.CUSTOMER_COMPLAINT,
    updated_at: datetime | None = None,
) -> CaseDetailResponse:
    """创建测试用案例详情响应。"""
    if updated_at is None:
        updated_at = _make_utc_now()
    return CaseDetailResponse(
        case_id=case_id,
        problem_description="客户投诉：上菜速度慢",
        store_id=store_id,
        problem_type=problem_type,
        context=ContextSchema(scene="晚高峰时段"),
        root_cause="厨房出菜流程不合理",
        solution_steps=[
            SolutionStepSchema(order=1, content="优化出菜顺序"),
            SolutionStepSchema(order=2, content="增加配菜人员"),
        ],
        outcome=OutcomeSchema(result="improved", notes="出菜时间缩短30%"),
        status=status,
        created_at=_make_utc_now(),
        updated_at=updated_at,
        store=_make_store_summary(store_id=store_id),
    )


# ---------------------------------------------------------------------------
# CaseSnapshotProvider.load_snapshot 测试
# ---------------------------------------------------------------------------


class TestLoadSnapshotHappyPath:
    """测试正常路径：active / archived 案例可成功加载快照。"""

    @pytest.mark.asyncio
    async def test_active_case_returns_snapshot(self):
        """active 状态的案例应成功返回 CaseInputSnapshot。"""
        mock_service = AsyncMock()
        detail = _make_case_detail(status=CaseStatus.ACTIVE)
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        assert isinstance(snapshot, CaseInputSnapshot)
        assert snapshot.case_id == "case_001"
        assert snapshot.status == "active"
        mock_service.get_case.assert_awaited_once_with("case_001")

    @pytest.mark.asyncio
    async def test_archived_case_returns_snapshot(self):
        """archived 状态的案例应成功返回 CaseInputSnapshot。"""
        mock_service = AsyncMock()
        detail = _make_case_detail(case_id="case_002", status=CaseStatus.ARCHIVED)
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_002")

        assert isinstance(snapshot, CaseInputSnapshot)
        assert snapshot.case_id == "case_002"
        assert snapshot.status == "archived"


class TestLoadSnapshotStatusGate:
    """测试状态门控：draft 案例被拒绝。"""

    @pytest.mark.asyncio
    async def test_draft_case_raises_state_conflict(self):
        """draft 状态的案例应被拒绝并抛出 EnrichmentStateConflictError。"""
        mock_service = AsyncMock()
        detail = _make_case_detail(case_id="case_003", status=CaseStatus.DRAFT)
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)

        with pytest.raises(EnrichmentStateConflictError) as exc_info:
            await provider.load_snapshot("case_003")

        assert exc_info.value.case_id == "case_003"
        assert exc_info.value.current_status == "draft"


class TestLoadSnapshotNotFound:
    """测试案例不存在时的错误处理。"""

    @pytest.mark.asyncio
    async def test_not_found_raises_enrichment_error(self):
        """案例不存在时应抛出 EnrichmentCaseNotFoundError。"""
        mock_service = AsyncMock()
        mock_service.get_case.side_effect = CaseNotFoundError("case_999")

        provider = CaseSnapshotProvider(case_service=mock_service)

        with pytest.raises(EnrichmentCaseNotFoundError) as exc_info:
            await provider.load_snapshot("case_999")

        assert exc_info.value.case_id == "case_999"


class TestSnapshotFieldMapping:
    """测试 CaseDetailResponse -> CaseInputSnapshot 的字段映射。"""

    @pytest.mark.asyncio
    async def test_includes_required_fields(self):
        """快照应包含所有 LLM 增强所需的字段。"""
        mock_service = AsyncMock()
        now = _make_utc_now()
        detail = _make_case_detail(
            case_id="case_100",
            status=CaseStatus.ACTIVE,
            store_id="store_100",
            problem_type=ProblemType.SERVICE_QUALITY,
            updated_at=now,
        )
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_100")

        assert snapshot.case_id == "case_100"
        assert snapshot.problem_description == "客户投诉：上菜速度慢"
        assert snapshot.problem_type == "service_quality"
        assert snapshot.root_cause == "厨房出菜流程不合理"
        assert snapshot.status == "active"
        assert snapshot.updated_at == now
        assert snapshot.store_id == "store_100"

    @pytest.mark.asyncio
    async def test_context_converted_to_dict(self):
        """context 字段应从 Pydantic 模型转换为 dict。"""
        mock_service = AsyncMock()
        detail = _make_case_detail()
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        assert isinstance(snapshot.context, dict)
        assert snapshot.context["scene"] == "晚高峰时段"

    @pytest.mark.asyncio
    async def test_solution_steps_converted_to_list_of_dicts(self):
        """solution_steps 应从 Pydantic 模型列表转换为 list[dict]。"""
        mock_service = AsyncMock()
        detail = _make_case_detail()
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        assert isinstance(snapshot.solution_steps, list)
        assert len(snapshot.solution_steps) == 2
        assert isinstance(snapshot.solution_steps[0], dict)
        assert snapshot.solution_steps[0]["order"] == 1
        assert snapshot.solution_steps[0]["content"] == "优化出菜顺序"
        assert snapshot.solution_steps[1]["order"] == 2
        assert snapshot.solution_steps[1]["content"] == "增加配菜人员"

    @pytest.mark.asyncio
    async def test_outcome_converted_to_dict(self):
        """outcome 字段应从 Pydantic 模型转换为 dict。"""
        mock_service = AsyncMock()
        detail = _make_case_detail()
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        assert isinstance(snapshot.outcome, dict)
        assert snapshot.outcome["result"] == "improved"
        assert snapshot.outcome["notes"] == "出菜时间缩短30%"

    @pytest.mark.asyncio
    async def test_includes_store_mirror_fields(self):
        """快照应包含门店镜像过滤维度字段。"""
        mock_service = AsyncMock()
        detail = _make_case_detail()
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        assert snapshot.store_id == "store_001"
        assert snapshot.store_name == "测试门店"
        assert snapshot.brand_id == "brand_001"
        assert snapshot.brand_name == "测试品牌"
        assert snapshot.business_type == "火锅"
        assert snapshot.store_scale == "large"
        assert snapshot.franchise_type == "加盟"
        assert snapshot.city == "北京"
        assert snapshot.city_tier == "一线"

    @pytest.mark.asyncio
    async def test_excludes_created_at(self):
        """快照不应包含 created_at，仅包含 updated_at。"""
        mock_service = AsyncMock()
        detail = _make_case_detail()
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        snapshot_dict = snapshot.model_dump()
        assert "created_at" not in snapshot_dict
        assert "updated_at" in snapshot_dict

    @pytest.mark.asyncio
    async def test_problem_type_as_string(self):
        """problem_type 应以字符串形式存储，而非枚举对象。"""
        mock_service = AsyncMock()
        detail = _make_case_detail(problem_type=ProblemType.PRODUCT_QUALITY)
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        assert snapshot.problem_type == "product_quality"
        assert isinstance(snapshot.problem_type, str)

    @pytest.mark.asyncio
    async def test_status_as_string(self):
        """status 应以字符串形式存储，而非枚举对象。"""
        mock_service = AsyncMock()
        detail = _make_case_detail(status=CaseStatus.ACTIVE)
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        assert snapshot.status == "active"
        assert isinstance(snapshot.status, str)


class TestSnapshotExcludesSensitiveFields:
    """测试快照排除敏感/无关字段（Requirement 6.1）。"""

    @pytest.mark.asyncio
    async def test_snapshot_has_no_extra_fields(self):
        """快照不应包含 schema 定义之外的任何字段。"""
        mock_service = AsyncMock()
        detail = _make_case_detail()
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_001")

        # CaseInputSnapshot 使用 extra="forbid"，验证不会多出字段
        snapshot_dict = snapshot.model_dump()
        expected_keys = {
            "case_id",
            "problem_description",
            "problem_type",
            "context",
            "root_cause",
            "solution_steps",
            "outcome",
            "status",
            "updated_at",
            "store_id",
            "store_name",
            "brand_id",
            "brand_name",
            "business_type",
            "store_scale",
            "franchise_type",
            "city",
            "city_tier",
        }
        assert set(snapshot_dict.keys()) == expected_keys


class TestSnapshotProviderInit:
    """测试 CaseSnapshotProvider 初始化。"""

    def test_accepts_case_service_dependency(self):
        """应通过构造函数接受 CaseService 依赖。"""
        mock_service = AsyncMock()
        provider = CaseSnapshotProvider(case_service=mock_service)
        assert provider._case_service is mock_service

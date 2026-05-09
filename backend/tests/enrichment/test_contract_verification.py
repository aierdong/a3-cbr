"""上游详情契约兼容验证测试。

验证 CaseSnapshotProvider、CaseInputSnapshot 与上游详情契约文档
(docs/contract-a3-case-detail-for-enrichment.md) 的一致性。

覆盖内容：
- §3.1 标识与时间字段在 CaseDetailResponse 中存在且被正确映射
- §3.2 A3 核心内容字段在 CaseDetailResponse 中存在且被正确映射
- §3.3 门店镜像字段在 CaseInputSnapshot 中全部存在
- §3.4 明确排除字段不在 CaseInputSnapshot 中
- §4.1 映射规则：所有上游字段一一映射到快照
- §5.1 状态门控：仅 active / archived 允许进入增强流程

Requirements: 1.1, 1.2, 6.1
Boundary: CaseSnapshotProvider, EnrichmentSchemas_
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
from app.enrichment.case_snapshot import (
    CaseSnapshotProvider,
    EnrichmentStateConflictError,
    _ENRICHABLE_STATUSES,
)
from app.enrichment.schemas import CaseInputSnapshot


# ---------------------------------------------------------------------------
# 契约常量定义（来自 docs/contract-a3-case-detail-for-enrichment.md）
# ---------------------------------------------------------------------------

# §3.1 标识与时间
CONTRACT_IDENTITY_FIELDS = {"case_id", "status", "created_at", "updated_at"}

# §3.2 A3 核心内容字段
CONTRACT_CORE_CONTENT_FIELDS = {
    "problem_description",
    "problem_type",
    "context",
    "root_cause",
    "solution_steps",
    "outcome",
}

# §3.3 门店镜像字段（对外 JSON 属性名）
CONTRACT_STORE_MIRROR_FIELDS = {
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

# §3.4 明确排除字段（不应出现在详情中的依赖）
CONTRACT_EXCLUDED_FIELD_KEYWORDS = [
    "vector",
    "embedding",
    "similarity",
    "recommendation_reason",
    "feedback",
    "adoption",
    "summary",
    "tag_suggestion",
]

# §5.1 允许进入增强流程的状态
CONTRACT_ENRICHABLE_STATUSES = {"active", "archived"}


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _make_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_store_summary(store_id: str = "store_001") -> StoreInfoSummary:
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
    status: CaseStatus = CaseStatus.ACTIVE,
) -> CaseDetailResponse:
    return CaseDetailResponse(
        case_id="case_contract_001",
        problem_description="契约验证测试问题描述",
        store_id="store_001",
        problem_type=ProblemType.CUSTOMER_COMPLAINT,
        context=ContextSchema(scene="契约验证场景"),
        root_cause="契约验证根因",
        solution_steps=[
            SolutionStepSchema(order=1, content="步骤一"),
            SolutionStepSchema(order=2, content="步骤二"),
        ],
        outcome=OutcomeSchema(result="improved", notes="验证改善"),
        status=status,
        created_at=_make_utc_now(),
        updated_at=_make_utc_now(),
        store=_make_store_summary(),
    )


# ---------------------------------------------------------------------------
# §3.1 + §3.2 + §3.3: 上游字段完整性验证
# ---------------------------------------------------------------------------


class TestContractFieldPresence:
    """验证 CaseDetailResponse 包含契约 §3 所有必需字段。"""

    def test_case_detail_response_has_identity_fields(self):
        """§3.1: CaseDetailResponse 应包含标识与时间字段。"""
        detail = _make_case_detail()
        detail_dict = detail.model_dump()
        for field in CONTRACT_IDENTITY_FIELDS:
            assert field in detail_dict, (
                f"§3.1 字段 '{field}' 未在 CaseDetailResponse 中找到"
            )

    def test_case_detail_response_has_core_content_fields(self):
        """§3.2: CaseDetailResponse 应包含 A3 核心内容字段。"""
        detail = _make_case_detail()
        detail_dict = detail.model_dump()
        for field in CONTRACT_CORE_CONTENT_FIELDS:
            assert field in detail_dict, (
                f"§3.2 字段 '{field}' 未在 CaseDetailResponse 中找到"
            )

    def test_case_detail_response_has_store_mirror_fields(self):
        """§3.3: CaseDetailResponse.store 应包含所有门店镜像字段。"""
        detail = _make_case_detail()
        store_dict = detail.store.model_dump()
        for field in CONTRACT_STORE_MIRROR_FIELDS:
            assert field in store_dict, (
                f"§3.3 门店镜像字段 '{field}' 未在 StoreInfoSummary 中找到"
            )


# ---------------------------------------------------------------------------
# §4.1: CaseSnapshotProvider 字段映射验证
# ---------------------------------------------------------------------------


class TestContractFieldMapping:
    """验证 CaseSnapshotProvider 正确映射契约字段到 CaseInputSnapshot。"""

    @pytest.mark.asyncio
    async def test_snapshot_has_identity_and_core_fields(self):
        """§4.1: 快照应包含契约 §3.1 + §3.2 的所有映射字段（created_at 除外）。"""
        mock_service = AsyncMock()
        mock_service.get_case.return_value = _make_case_detail()

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_contract_001")
        snapshot_dict = snapshot.model_dump()

        # §3.1 映射：case_id, status, updated_at（created_at 不在快照中，见 §4.1 映射表）
        expected_from_identity = {"case_id", "status", "updated_at"}
        for field in expected_from_identity:
            assert field in snapshot_dict, (
                f"§4.1 映射: '{field}' 未在 CaseInputSnapshot 中找到"
            )

        # §3.2 映射：所有核心内容字段
        for field in CONTRACT_CORE_CONTENT_FIELDS:
            assert field in snapshot_dict, (
                f"§4.1 映射: '{field}' 未在 CaseInputSnapshot 中找到"
            )

    @pytest.mark.asyncio
    async def test_snapshot_has_all_store_mirror_fields(self):
        """§4.1: 快照应包含 §3.3 所有门店镜像字段（扁平化）。"""
        mock_service = AsyncMock()
        mock_service.get_case.return_value = _make_case_detail()

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_contract_001")
        snapshot_dict = snapshot.model_dump()

        for field in CONTRACT_STORE_MIRROR_FIELDS:
            assert field in snapshot_dict, (
                f"§4.1 映射: 门店镜像字段 '{field}' 未在 CaseInputSnapshot 中找到"
            )

    @pytest.mark.asyncio
    async def test_created_at_not_in_snapshot(self):
        """§4.1: created_at 不应出现在 CaseInputSnapshot 中（快照仅含 updated_at）。"""
        mock_service = AsyncMock()
        mock_service.get_case.return_value = _make_case_detail()

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_contract_001")
        snapshot_dict = snapshot.model_dump()

        assert "created_at" not in snapshot_dict, (
            "created_at 不应出现在 CaseInputSnapshot 中"
        )

    @pytest.mark.asyncio
    async def test_store_mirror_values_match_upstream(self):
        """§4.1: 门店镜像字段值应与上游详情一致。"""
        mock_service = AsyncMock()
        detail = _make_case_detail()
        mock_service.get_case.return_value = detail

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_contract_001")

        assert snapshot.store_id == detail.store_id
        assert snapshot.store_name == detail.store.store_name
        assert snapshot.brand_id == detail.store.brand_id
        assert snapshot.brand_name == detail.store.brand_name
        assert snapshot.business_type == detail.store.business_type
        assert snapshot.store_scale == detail.store.store_scale
        assert snapshot.franchise_type == detail.store.franchise_type
        assert snapshot.city == detail.store.city
        assert snapshot.city_tier == detail.store.city_tier

    @pytest.mark.asyncio
    async def test_enums_are_strings_not_enum_objects(self):
        """§4.1: status 和 problem_type 应以字符串形式存储。"""
        mock_service = AsyncMock()
        mock_service.get_case.return_value = _make_case_detail()

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_contract_001")

        assert isinstance(snapshot.status, str)
        assert isinstance(snapshot.problem_type, str)


# ---------------------------------------------------------------------------
# §3.4: 排除字段验证
# ---------------------------------------------------------------------------


class TestContractExcludedFields:
    """验证 CaseInputSnapshot 不包含 §3.4 明确排除的字段。"""

    def test_snapshot_has_no_excluded_keywords(self):
        """§3.4: CaseInputSnapshot 的字段名不应包含排除关键词。"""
        snapshot_fields = set(CaseInputSnapshot.model_fields.keys())

        for keyword in CONTRACT_EXCLUDED_FIELD_KEYWORDS:
            matches = [f for f in snapshot_fields if keyword in f.lower()]
            assert not matches, (
                f"§3.4: CaseInputSnapshot 包含排除关键词 '{keyword}' "
                f"的字段: {matches}"
            )

    def test_snapshot_schema_forbids_extra_fields(self):
        """§3.4: CaseInputSnapshot 应禁止额外字段（extra='forbid'）。"""
        assert CaseInputSnapshot.model_config.get("extra") == "forbid", (
            "CaseInputSnapshot 应配置 extra='forbid' 以防止意外字段注入"
        )

    def test_snapshot_field_count_is_bounded(self):
        """§3.4: CaseInputSnapshot 字段数量应在契约预期范围内。"""
        snapshot_fields = set(CaseInputSnapshot.model_fields.keys())

        # 契约预期字段：§3.1(3) + §3.2(6) + §3.3(9) = 18
        expected_max = (
            len(CONTRACT_IDENTITY_FIELDS)
            - 1  # created_at 不在快照中
            + len(CONTRACT_CORE_CONTENT_FIELDS)
            + len(CONTRACT_STORE_MIRROR_FIELDS)
        )

        assert len(snapshot_fields) <= expected_max, (
            f"CaseInputSnapshot 字段数 {len(snapshot_fields)} "
            f"超过契约预期上限 {expected_max}，可能存在不应包含的字段"
        )


# ---------------------------------------------------------------------------
# §5.1: 状态门控验证
# ---------------------------------------------------------------------------


class TestContractStatusGate:
    """验证状态门控与契约 §5.1 一致：仅 active / archived 可进入增强流程。"""

    def test_enrichable_statuses_match_contract(self):
        """§5.1: 允许进入增强流程的状态集合应与契约一致。"""
        enrichable_values = {s.value for s in _ENRICHABLE_STATUSES}
        assert enrichable_values == CONTRACT_ENRICHABLE_STATUSES, (
            f"§5.1: 实际可增强状态 {enrichable_values} "
            f"与契约预期 {CONTRACT_ENRICHABLE_STATUSES} 不一致"
        )

    @pytest.mark.asyncio
    async def test_draft_case_is_rejected(self):
        """§5.1: draft 状态的案例应被拒绝进入增强流程。"""
        mock_service = AsyncMock()
        mock_service.get_case.return_value = _make_case_detail(
            status=CaseStatus.DRAFT,
        )

        provider = CaseSnapshotProvider(case_service=mock_service)

        with pytest.raises(EnrichmentStateConflictError):
            await provider.load_snapshot("case_draft")

    @pytest.mark.asyncio
    async def test_active_case_is_accepted(self):
        """§5.1: active 状态的案例应被允许进入增强流程。"""
        mock_service = AsyncMock()
        mock_service.get_case.return_value = _make_case_detail(
            status=CaseStatus.ACTIVE,
        )

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_active")
        assert snapshot.status == "active"

    @pytest.mark.asyncio
    async def test_archived_case_is_accepted(self):
        """§5.1: archived 状态的案例应被允许进入增强流程。"""
        mock_case = _make_case_detail(status=CaseStatus.ARCHIVED)
        mock_service = AsyncMock()
        mock_service.get_case.return_value = mock_case

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_archived")
        assert snapshot.status == "archived"

    def test_case_status_enum_values_match_contract(self):
        """§5.1: CaseStatus 枚举值应与契约 §5.1 定义一致。"""
        status_values = {s.value for s in CaseStatus}
        expected = {"draft", "active", "archived"}
        assert status_values == expected, (
            f"§5.1: CaseStatus 枚举值 {status_values} "
            f"与契约预期 {expected} 不一致"
        )


# ---------------------------------------------------------------------------
# 端到端契约一致性
# ---------------------------------------------------------------------------


class TestContractEndToEnd:
    """端到端验证：从 CaseDetailResponse 到 CaseInputSnapshot 的完整契约一致性。"""

    def test_all_upstream_fields_exist_in_schemas(self):
        """§4.1: 上游详情的每个被映射字段都应在上游 schema 中存在。"""
        detail = _make_case_detail()
        detail_fields = set(detail.model_fields.keys())
        store_fields = set(StoreInfoSummary.model_fields.keys())

        # 已映射字段（根级）
        mapped_root_fields = {"case_id", "problem_description", "store_id",
                              "problem_type", "context", "root_cause",
                              "solution_steps", "outcome", "status", "updated_at"}

        # 已映射字段（门店镜像，store_id 已在根级映射）
        mapped_store_fields = CONTRACT_STORE_MIRROR_FIELDS - {"store_id"}

        for field in mapped_root_fields:
            assert field in detail_fields, (
                f"字段 '{field}' 不在上游详情中"
            )

        for field in mapped_store_fields:
            assert field in store_fields, (
                f"门店字段 '{field}' 不在 StoreInfoSummary 中"
            )

    @pytest.mark.asyncio
    async def test_snapshot_field_types_are_compatible(self):
        """§4.1: 快照字段类型应与契约兼容（string/dict/list/datetime）。"""
        mock_service = AsyncMock()
        mock_service.get_case.return_value = _make_case_detail()

        provider = CaseSnapshotProvider(case_service=mock_service)
        snapshot = await provider.load_snapshot("case_types")

        # 字符串字段
        assert isinstance(snapshot.case_id, str)
        assert isinstance(snapshot.problem_description, str)
        assert isinstance(snapshot.problem_type, str)
        assert isinstance(snapshot.root_cause, str)
        assert isinstance(snapshot.status, str)

        # dict 字段
        assert isinstance(snapshot.context, dict)
        assert isinstance(snapshot.outcome, dict)

        # list[dict] 字段
        assert isinstance(snapshot.solution_steps, list)
        assert all(isinstance(s, dict) for s in snapshot.solution_steps)

        # datetime 字段
        assert isinstance(snapshot.updated_at, datetime)

        # 门店镜像字符串字段
        for field in CONTRACT_STORE_MIRROR_FIELDS:
            value = getattr(snapshot, field)
            assert isinstance(value, str), (
                f"门店镜像字段 '{field}' 类型应为 str，实际为 {type(value)}"
            )

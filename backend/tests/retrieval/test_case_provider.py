"""RecommendationCaseProvider 单元测试。

测试 RecommendationCaseProvider 的：
1. Feature Flag gate
2. 成功路径：正常调用案例服务和增强结果、返回候选快照
3. not_found 与 forbidden 可区分
4. 单候选失败仅标记缺失而非整批失败
5. 缺失字段标记（missing_fields）
6. 空候选返回空列表（非失败）
7. 向量候选转换为候选快照

Boundary: RecommendationCaseProvider_
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cases.schemas import (
    CaseDetailResponse,
    CaseStatus,
    ProblemType,
    StoreInfoSummary,
)
from app.cases.service import CaseNotFoundError
from app.enrichment.schemas import EnrichmentStatus
from app.enrichment.models import CaseEnrichmentResult
from app.retrieval.case_provider import (
    RECOMMENDATION_CASE_PROVIDER_ENABLED,
    CaseForbiddenError,
    CandidateSnapshot,
    RecommendationCaseProvider,
    is_case_provider_enabled,
)


# ---------------------------------------------------------------------------
# Feature Flag
# ---------------------------------------------------------------------------


def _is_case_provider_enabled() -> bool:
    """检查 RecommendationCaseProvider 功能是否启用。"""
    return RECOMMENDATION_CASE_PROVIDER_ENABLED


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vector_candidates(
    case_ids: list[str] | None = None,
) -> list[dict]:
    """构造向量候选列表（模拟 VectorCandidate）。"""
    if case_ids is None:
        case_ids = ["case-001", "case-002", "case-003"]

    candidates = []
    for idx, case_id in enumerate(case_ids):
        candidates.append(
            {
                "case_id": case_id,
                "vector_id": f"vec-{case_id}",
                "similarity_score": 0.95 - idx * 0.02,
                "distance": 0.05 + idx * 0.02,
                "case_updated_at": datetime(2025, 1, 1),
                "input_content_hash": f"hash{case_id}",
                "index_status": "searchable",
                "filter_metadata": {
                    "brand_id": "brand-001",
                    "store_id": "store-001",
                    "problem_type": "customer_complaint",
                    "tags": ["投诉", "服务"],
                },
            }
        )
    return candidates


def _make_case_detail_response(case_id: str) -> CaseDetailResponse:
    """构造 CaseDetailResponse。"""
    return CaseDetailResponse(
        case_id=case_id,
        problem_description=f"问题描述 for {case_id}",
        store_id="store-001",
        problem_type=ProblemType.CUSTOMER_COMPLAINT,
        context={"scene": f"场景 for {case_id}"},
        root_cause=f"根因 for {case_id}",
        solution_steps=[
            {"order": 1, "content": f"步骤1 for {case_id}"},
            {"order": 2, "content": f"步骤2 for {case_id}"},
        ],
        outcome={"result": "improved", "notes": f"效果备注 for {case_id}"},
        status=CaseStatus.ACTIVE,
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2025, 1, 1),
        store=StoreInfoSummary(
            store_id="store-001",
            store_name="上海旗舰店",
            brand_id="brand-001",
            brand_name="品牌A",
            business_type="零售",
            store_scale="大型",
            franchise_type="直营",
            city="上海",
            city_tier="一线",
            updated_at=datetime(2025, 1, 1),
        ),
    )


def _make_enrichment_result(
    case_id: str,
    has_structured_suggestions: bool = True,
) -> CaseEnrichmentResult:
    """构造 CaseEnrichmentResult（Mock ORM 对象）。"""
    mock_result = MagicMock(spec=CaseEnrichmentResult)
    mock_result.case_id = case_id
    mock_result.enrichment_id = f"enrich-{case_id}"
    mock_result.case_updated_at = datetime(2025, 1, 1)
    mock_result.status = EnrichmentStatus.VALID
    mock_result.problem_summary = f"问题摘要 for {case_id}"
    mock_result.solution_summary = f"方案摘要 for {case_id}"

    if has_structured_suggestions:
        mock_result.structured_suggestions = {
            "problem_type_suggestion": "客户投诉",
            "root_cause_category": "服务态度",
            "applicable_scenarios": ["零售", "餐饮"],
            "confidence_notes": "高置信度",
        }
    else:
        mock_result.structured_suggestions = None

    mock_result.tag_suggestions = ["投诉", "服务"]
    mock_result.missing_information = []
    mock_result.output_version = "v1"
    mock_result.created_at = datetime(2024, 12, 1)
    mock_result.updated_at = datetime(2025, 1, 1)

    return mock_result


# ---------------------------------------------------------------------------
# Tests: 成功路径
# ---------------------------------------------------------------------------


class TestCaseProviderSuccess:
    """推荐候选案例快照读取成功场景。"""

    @pytest.mark.asyncio
    async def test_load_candidates_returns_snapshot_list(self):
        """成功调用案例服务和增强结果，返回候选快照列表。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001")
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])

        result = await provider.load_candidates(vector_candidates)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], CandidateSnapshot)
        assert result[0].case_id == "case-001"
        assert result[0].problem_summary == "问题摘要 for case-001"
        assert result[0].structured_suggestions is not None

    @pytest.mark.asyncio
    async def test_load_candidates_merges_case_and_enrichment(self):
        """候选快照正确合并案例详情和增强结果。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001")
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        # 案例基础字段
        assert snapshot.case_id == "case-001"
        assert snapshot.problem_description == "问题描述 for case-001"
        assert snapshot.brand_id == "brand-001"
        assert snapshot.store_id == "store-001"
        assert snapshot.case_status == CaseStatus.ACTIVE
        # 增强字段
        assert snapshot.problem_summary == "问题摘要 for case-001"
        assert snapshot.structured_suggestions is not None
        # 向量候选字段
        assert snapshot.vector_id == "vec-case-001"
        assert abs(snapshot.vector_similarity_score - 0.95) < 0.001

    @pytest.mark.asyncio
    async def test_load_candidates_preserves_vector_fields(self):
        """候选快照保留向量候选原语：vector_id、similarity_score。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001")
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        assert snapshot.vector_id == "vec-case-001"
        assert abs(snapshot.vector_similarity_score - 0.95) < 0.001
        assert snapshot.case_updated_at == datetime(2025, 1, 1)

    @pytest.mark.asyncio
    async def test_load_candidates_multiple_candidates(self):
        """多个候选均成功返回快照。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            return _make_case_detail_response(case_id)

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()

        async def mock_get_result(case_id: str):
            return _make_enrichment_result(case_id)

        mock_enrichment_repo.get_current_result = AsyncMock(
            side_effect=mock_get_result
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(
            ["case-001", "case-002", "case-003"]
        )
        result = await provider.load_candidates(vector_candidates)

        assert len(result) == 3
        assert [s.case_id for s in result] == [
            "case-001",
            "case-002",
            "case-003",
        ]


# ---------------------------------------------------------------------------
# Tests: 错误契约 - not_found 与 forbidden 可区分
# ---------------------------------------------------------------------------


class TestCaseProviderErrorContract:
    """错误契约：not_found 与 forbidden 可区分，单候选失败不导致整批崩溃。"""

    @pytest.mark.asyncio
    async def test_case_not_found_distinguished_from_forbidden(self):
        """CaseNotFoundError 与 forbidden 响应必须可区分。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            if case_id == "forbidden-case":
                raise PermissionError("Access denied")
            raise CaseNotFoundError(case_id)

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        # CaseNotFoundError 必须能区分
        vector_candidates = _make_vector_candidates(["not-found-case"])
        result = await provider.load_candidates(vector_candidates)

        # not_found 的候选应标记 missing_fields，不抛异常
        assert len(result) == 1
        assert "problem_description" in result[0].missing_fields

    @pytest.mark.asyncio
    async def test_single_candidate_failure_marks_missing_not_batch_failure(self):
        """单候选失败仅标记缺失字段，不导致整批失败。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            if case_id == "case-002":
                raise CaseNotFoundError(case_id)
            return _make_case_detail_response(case_id)

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()

        async def mock_get_result(case_id: str):
            if case_id == "case-002":
                return None
            return _make_enrichment_result(case_id)

        mock_enrichment_repo.get_current_result = AsyncMock(
            side_effect=mock_get_result
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(
            ["case-001", "case-002", "case-003"]
        )
        result = await provider.load_candidates(vector_candidates)

        # 3 个候选都返回了，只是 case-002 有 missing_fields
        assert len(result) == 3

        # case-001 和 case-003 成功
        assert result[0].case_id == "case-001"
        assert result[2].case_id == "case-003"

        # case-002 标记了缺失字段
        assert result[1].case_id == "case-002"
        assert len(result[1].missing_fields) > 0

    @pytest.mark.asyncio
    async def test_permission_error_raises_case_forbidden_error(self):
        """权限错误（forbidden）应抛出 CaseForbiddenError。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()

        async def mock_get_case(case_id: str):
            raise PermissionError("Access denied")

        mock_case_service.get_case = AsyncMock(side_effect=mock_get_case)

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["forbidden-case"])

        # 必须能区分 forbidden 和 not_found
        with pytest.raises(CaseForbiddenError):
            await provider.load_candidates(vector_candidates)


# ---------------------------------------------------------------------------
# Tests: 缺失字段标记
# ---------------------------------------------------------------------------


class TestCaseProviderMissingFields:
    """缺失字段标记：缺失摘要、结构化建议、解决步骤或效果信息的候选标记 missing_fields。"""

    @pytest.mark.asyncio
    async def test_missing_enrichment_marks_problem_summary_missing(self):
        """缺失 CaseEnrichmentResult 时，problem_summary 标记为缺失。

        仅当 problem_description 也不存在时才标记为缺失。
        """
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()

        # 创建一个没有 problem_description 的案例
        detail = _make_case_detail_response("case-001")
        detail.problem_description = ""

        mock_case_service.get_case = AsyncMock(return_value=detail)

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        # 当 enrichment 和 problem_description 都缺失时，problem_summary 标记为缺失
        assert "problem_summary" in snapshot.missing_fields
        assert snapshot.problem_summary is None

    @pytest.mark.asyncio
    async def test_missing_structured_suggestions_marks_field_missing(self):
        """缺失 structured_suggestions 时标记为缺失。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001", has_structured_suggestions=False)
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        assert "structured_suggestions" in snapshot.missing_fields
        assert snapshot.structured_suggestions is None

    @pytest.mark.asyncio
    async def test_missing_solution_steps_marks_field_missing(self):
        """缺失 solution_steps 时标记为缺失。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()

        # 创建一个缺少 solution_steps 的案例
        detail = _make_case_detail_response("case-001")
        detail.solution_steps = []

        mock_case_service.get_case = AsyncMock(return_value=detail)

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001")
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        assert "core_solution_steps" in snapshot.missing_fields

    @pytest.mark.asyncio
    async def test_missing_outcome_marks_field_missing(self):
        """缺失 outcome 时标记为缺失（当 enrichment 也没有 solution_summary 时）。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()

        # 创建一个没有 outcome 的案例
        detail = _make_case_detail_response("case-001")
        detail.outcome = None

        mock_case_service.get_case = AsyncMock(return_value=detail)

        mock_enrichment_repo = MagicMock()
        # 没有 enrichment，且没有 solution_summary
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        # outcome 和 enrichment.solution_summary 都缺失时，outcome_summary 标记为缺失
        assert "outcome_summary" in snapshot.missing_fields


# ---------------------------------------------------------------------------
# Tests: 空候选返回空列表
# ---------------------------------------------------------------------------


class TestCaseProviderEmptyCandidates:
    """空候选列表返回空列表（非失败）。"""

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty_list(self):
        """空候选列表返回空列表，不抛异常。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock()

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock()

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        result = await provider.load_candidates([])

        assert isinstance(result, list)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: 向量候选转换为候选快照
# ---------------------------------------------------------------------------


class TestCaseProviderCandidateMapping:
    """向量候选转换为候选快照的映射逻辑。"""

    @pytest.mark.asyncio
    async def test_problem_description_used_when_no_problem_summary(self):
        """当 enrichment 没有 problem_summary 时，使用案例的 problem_description。

        注意：当案例有 problem_description 时，missing_fields 不会标记 problem_summary，
        因为设计允许使用 problem_description 作为后备。
        """
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(return_value=None)

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        # problem_description 应该有值（来自案例）
        assert snapshot.problem_description is not None
        # no enrichment -> problem_summary is None
        assert snapshot.problem_summary is None
        # problem_description exists, so problem_summary not marked missing
        assert "problem_summary" not in snapshot.missing_fields

    @pytest.mark.asyncio
    async def test_outcome_summary_derived_from_outcome(self):
        """outcome_summary 从案例 outcome 字段派生。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001")
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        # outcome_summary 应该有值（来自 enrichment solution_summary 或案例 outcome）
        assert snapshot.outcome_summary is not None

    @pytest.mark.asyncio
    async def test_core_solution_steps_from_case(self):
        """core_solution_steps 从案例 solution_steps 字段派生。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001")
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        # core_solution_steps 应该有值（来自案例）
        assert snapshot.core_solution_steps is not None

    @pytest.mark.asyncio
    async def test_filter_fields_from_case_store(self):
        """brand_id、store_id、problem_type、tags 从案例的 store 和 case 字段获取。"""
        if not _is_case_provider_enabled():
            pytest.skip("RecommendationCaseProvider 功能未启用")

        mock_case_service = MagicMock()
        mock_case_service.get_case = AsyncMock(
            return_value=_make_case_detail_response("case-001")
        )

        mock_enrichment_repo = MagicMock()
        mock_enrichment_repo.get_current_result = AsyncMock(
            return_value=_make_enrichment_result("case-001")
        )

        provider = RecommendationCaseProvider(
            case_service=mock_case_service,
            enrichment_repository=mock_enrichment_repo,
        )

        vector_candidates = _make_vector_candidates(["case-001"])
        result = await provider.load_candidates(vector_candidates)

        snapshot = result[0]
        assert snapshot.brand_id == "brand-001"
        assert snapshot.store_id == "store-001"
        assert snapshot.problem_type == ProblemType.CUSTOMER_COMPLAINT
        assert snapshot.tags is not None
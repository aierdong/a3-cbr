"""RecommendationExplainer 单元测试。

测试 RecommendationExplainer 的：
1. Feature Flag gate
2. 成功路径：正常调用 RecommendationCopyService、返回生成的解释
3. 降级路径：文案服务失败、返回结构化降级解释
4. 候选顺序保持：输入输出顺序一致
5. 解释状态正确：generated/fallback/unavailable

Feature Flag 协议：
- RED 阶段：flag=False，测试应跳过或失败
- GREEN 阶段：flag=True，测试执行
- 测试文件从 explainer.py 导入 flag，保持同步
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.enrichment.schemas import (
    EnrichmentStatus,
    RecommendationCopyItem,
    RecommendationCopyResponse,
    SourceField,
)
from app.enrichment.validators import OutputValidationException
from app.retrieval.explainer import (
    ExplanationItem,
    ExplanationResult,
    ExplanationStatus,
    RecommendationExplainer,
    RETRIEVAL_EXPLAINER_ENABLED,
    is_explainer_enabled,
)
from app.retrieval.schemas import (
    CandidateSnapshot,
    NormalizedRetrievalQuery,
    QueryStructuredSuggestions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_normalized_query(
    normalized_query_text: str = "门店客户投诉处理",
) -> NormalizedRetrievalQuery:
    """构造标准化检索查询。"""
    return NormalizedRetrievalQuery(
        normalized_query_text=normalized_query_text,
        query_structured_suggestions=QueryStructuredSuggestions(
            suggested_problem_type="客户投诉",
            suggested_root_cause_category="服务态度",
            suggested_applicable_scenes=["零售", "餐饮"],
            suggested_tags=["投诉", "服务"],
        ),
        applied_filters={"brand_id": "brand-001"},
        effective_weights={
            "business_type": 0.2,
            "store_tier": 0.15,
            "brand_affinity": 0.1,
            "recency": 0.05,
        },
        top_k=10,
    )


def _make_candidate_snapshot(
    case_id: str = "case-001",
    problem_summary: str | None = "客户对服务态度不满",
    core_solution_steps: str | None = "1. 倾听客户诉求 2. 道歉并提供补偿 3. 改进服务流程",
    outcome_summary: str | None = "客户满意度提升至 95%",
    structured_suggestions: dict | None = None,
    missing_fields: list = None,
) -> CandidateSnapshot:
    """构造候选快照。"""
    return CandidateSnapshot(
        case_id=case_id,
        vector_id=f"vec-{case_id}",
        vector_similarity_score=0.85,
        problem_summary=problem_summary,
        problem_description=f"问题描述 for {case_id}",
        core_solution_steps=core_solution_steps,
        outcome_summary=outcome_summary,
        structured_suggestions=structured_suggestions,
        brand_id="brand-001",
        store_id="store-001",
        problem_type="客户投诉",
        tags=["投诉", "服务"],
        case_status="resolved",
        case_updated_at=datetime.now(),
        missing_fields=missing_fields or [],
    )


def _make_mock_copy_service() -> MagicMock:
    """构造模拟的 RecommendationCopyService。"""
    mock_service = MagicMock()
    mock_service.generate_copy = AsyncMock()
    return mock_service


def _make_success_copy_response(
    case_ids: list[str],
) -> RecommendationCopyResponse:
    """构造成功的文案响应。"""
    items = []
    for case_id in case_ids:
        items.append(
            RecommendationCopyItem(
                case_id=case_id,
                reason=f"推荐理由 for {case_id}",
                reference_points=[f"解决步骤 for {case_id}"],
                cautions=[f"注意事项 for {case_id}"],
                source_references=[SourceField.SOLUTION_STEPS],
            )
        )

    return RecommendationCopyResponse(
        copy_run_id="copy-run-001",
        status=EnrichmentStatus.VALID,
        items=items,
        schema_validation_status=EnrichmentStatus.VALID,
        model_id="gpt-4o",
        request_purpose=None,
        token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        created_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Tests: Feature Flag Gate
# ---------------------------------------------------------------------------


class TestExplainerFeatureFlag:
    """Feature Flag Protocol: flag=OFF 时测试应失败或跳过。"""

    def test_feature_flag_reflects_implementation_state(self):
        """GREEN 阶段：flag=True（实现已完成）。"""
        # 实现文件中 flag=True 表示功能已完成
        assert RETRIEVAL_EXPLAINER_ENABLED is True

    def test_is_explainer_enabled_returns_correct_value(self):
        """is_explainer_enabled 返回 flag 当前值。"""
        assert is_explainer_enabled() == RETRIEVAL_EXPLAINER_ENABLED


# ---------------------------------------------------------------------------
# Tests: 成功路径
# ---------------------------------------------------------------------------


class TestExplainerSuccess:
    """RecommendationExplainer 成功场景。"""

    @pytest.mark.asyncio
    async def test_explain_returns_generated_explanations(self):
        """成功调用文案服务并返回生成的解释。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        # 准备测试数据
        query = _make_normalized_query()
        candidates = [
            _make_candidate_snapshot("case-001"),
            _make_candidate_snapshot("case-002"),
            _make_candidate_snapshot("case-003"),
        ]

        # 模拟文案服务返回成功响应
        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.return_value = _make_success_copy_response(
            ["case-001", "case-002", "case-003"]
        )

        # 执行
        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        # 验证
        assert isinstance(result, ExplanationResult)
        assert result.status == ExplanationStatus.GENERATED
        assert len(result.items) == 3
        assert result.copy_run_id == "copy-run-001"

        # 验证候选顺序保持
        assert result.items[0].case_id == "case-001"
        assert result.items[1].case_id == "case-002"
        assert result.items[2].case_id == "case-003"

        # 验证解释内容
        assert result.items[0].recommendation_reason == "推荐理由 for case-001"
        assert result.items[0].status == ExplanationStatus.GENERATED
        assert result.items[0].reference_points == ["解决步骤 for case-001"]
        assert result.items[0].cautions == ["注意事项 for case-001"]
        assert result.items[0].source_references == ["solution_steps"]

    @pytest.mark.asyncio
    async def test_explain_preserves_candidate_order(self):
        """解释不改变候选顺序。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        # 故意使用乱序的 case_id
        candidates = [
            _make_candidate_snapshot("case-003"),
            _make_candidate_snapshot("case-001"),
            _make_candidate_snapshot("case-002"),
        ]

        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.return_value = _make_success_copy_response(
            ["case-003", "case-001", "case-002"]
        )

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        # 验证顺序保持
        assert [item.case_id for item in result.items] == ["case-003", "case-001", "case-002"]

    @pytest.mark.asyncio
    async def test_explain_returns_metadata_on_success(self):
        """成功时返回模型标识和 token 使用量。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        candidates = [_make_candidate_snapshot("case-001")]

        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.return_value = _make_success_copy_response(["case-001"])

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        assert result.metadata["model_id"] == "gpt-4o"
        assert result.metadata["token_usage"]["total_tokens"] == 150


# ---------------------------------------------------------------------------
# Tests: 降级路径
# ---------------------------------------------------------------------------


class TestExplainerFallback:
    """RecommendationExplainer 降级场景。"""

    @pytest.mark.asyncio
    async def test_explain_fallback_on_validation_error(self):
        """文案校验失败时返回降级解释。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        candidates = [
            _make_candidate_snapshot("case-001"),
            _make_candidate_snapshot("case-002"),
        ]

        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.side_effect = OutputValidationException(
            error_code="INJECTION_SUSPECTED",
            message="检测到潜在注入风险",
        )

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        # 验证降级状态
        assert result.status == ExplanationStatus.FALLBACK
        assert len(result.items) == 2

        # 验证降级解释内容
        assert result.items[0].case_id == "case-001"
        assert result.items[0].status == ExplanationStatus.FALLBACK
        # 降级时使用候选快照中的 problem_summary 作为推荐理由
        assert result.items[0].recommendation_reason == "客户对服务态度不满"
        # 降级时使用 core_solution_steps 作为 reference_points
        assert result.items[0].reference_points is not None

    @pytest.mark.asyncio
    async def test_explain_fallback_on_llm_error(self):
        """LLM 调用失败时返回降级解释。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        candidates = [_make_candidate_snapshot("case-001")]

        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.side_effect = Exception("LLM 调用失败")

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        assert result.status == ExplanationStatus.FALLBACK
        assert result.items[0].status == ExplanationStatus.FALLBACK
        assert "LLM 调用失败" in result.metadata.get("reason", "")

    @pytest.mark.asyncio
    async def test_explain_fallback_uses_snapshot_fields(self):
        """降级解释使用候选快照中的可用字段。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        candidates = [
            _make_candidate_snapshot(
                case_id="case-001",
                problem_summary="服务投诉问题",
                core_solution_steps="1. 道歉 2. 补偿 3. 回访",
                outcome_summary="客户满意",
            )
        ]

        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.side_effect = Exception("服务不可用")

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        # 验证降级使用快照字段
        assert result.items[0].recommendation_reason == "服务投诉问题"
        assert result.items[0].reference_points == ["1. 道歉 2. 补偿 3. 回访"]
        assert "参考效果: 客户满意" in result.items[0].cautions

    @pytest.mark.asyncio
    async def test_explain_empty_candidates_returns_unavailable(self):
        """空候选列表返回 unavailable 状态。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        candidates = []

        mock_service = _make_mock_copy_service()
        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        assert result.status == ExplanationStatus.UNAVAILABLE
        assert result.items == []
        assert result.metadata["reason"] == "empty_candidates"

    @pytest.mark.asyncio
    async def test_explain_missing_fields_in_fallback(self):
        """降级解释标记实际缺失的字段。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        # 只有 problem_summary，没有 core_solution_steps 和 outcome_summary
        candidates = [
            _make_candidate_snapshot(
                case_id="case-001",
                problem_summary="服务投诉",
                core_solution_steps=None,
                outcome_summary=None,
            )
        ]

        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.side_effect = Exception("失败")

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        # reference_points 和 cautions 应该为 None（没有可用字段）
        assert result.items[0].reference_points is None
        assert result.items[0].cautions is None
        # missing_fields 应包含未提供的字段
        assert "reference_points" in result.items[0].missing_fields
        assert "cautions" in result.items[0].missing_fields


# ---------------------------------------------------------------------------
# Tests: 边界条件
# ---------------------------------------------------------------------------


class TestExplainerBoundary:
    """边界条件测试。"""

    @pytest.mark.asyncio
    async def test_explain_with_none_source_fields(self):
        """候选快照 source_fields 为 None 时处理。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        # structured_suggestions 为 None
        candidates = [
            _make_candidate_snapshot(
                case_id="case-001",
                structured_suggestions=None,
            )
        ]

        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.side_effect = Exception("失败")

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        # 降级处理不应报错
        assert result.status == ExplanationStatus.FALLBACK
        assert result.items[0].case_id == "case-001"

    @pytest.mark.asyncio
    async def test_explain_with_copy_response_missing_case(self):
        """文案响应缺少某个候选时（防御性处理）。"""
        if not is_explainer_enabled():
            pytest.skip("RecommendationExplainer 功能未启用")

        query = _make_normalized_query()
        candidates = [
            _make_candidate_snapshot("case-001"),
            _make_candidate_snapshot("case-002"),
        ]

        # 故意只返回一个候选的文案
        mock_service = _make_mock_copy_service()
        mock_service.generate_copy.return_value = _make_success_copy_response(["case-001"])

        explainer = RecommendationExplainer(copy_service=mock_service)
        result = await explainer.explain(query, candidates)

        # case-001 应该有生成的解释
        assert result.items[0].status == ExplanationStatus.GENERATED
        # case-002 应该被降级（防御性处理）
        assert result.items[1].status == ExplanationStatus.FALLBACK

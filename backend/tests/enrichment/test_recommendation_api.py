"""推荐文案 API 端点测试。

测试 POST /api/recommendations/copy 端点：
- 成功生成推荐文案
- 响应按输入候选顺序返回解释文案
- 响应不包含排序或相似度修改字段
- LLM 失败时返回 HTTP 503
- 校验失败时返回 HTTP 503
- 注入风险时返回 HTTP 503

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
Boundary: EnrichmentRouter
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.common.llm_client import LLMClientError
from app.core.errors import ErrorCode
from app.enrichment.schemas import (
    EnrichmentStatus,
    RecommendationCopyItem,
    RequestPurpose,
    SourceField,
)
from app.enrichment.validators import OutputValidationException, ValidationErrorCode
from app.main import app


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_recommendation_request(**overrides):
    """构造推荐文案请求体。"""
    data = {
        "query_text": "门店销售下降如何改善？",
        "candidates": [
            {
                "case_id": "case_001",
                "case_summary": "某门店通过优化出餐流程改善销售",
                "source_fields": {"problem_description": "销售下降"},
            },
            {
                "case_id": "case_002",
                "case_summary": "某门店通过增加人手提升服务效率",
            },
        ],
    }
    data.update(overrides)
    return data


def _make_validated_items():
    """构造校验后的文案项列表。"""
    return [
        RecommendationCopyItem(
            case_id="case_001",
            reason="该案例与当前问题场景相似",
            reference_points=["优化出餐流程"],
            cautions=["注意季节性因素"],
            source_references=[SourceField.PROBLEM_DESCRIPTION],
        ),
        RecommendationCopyItem(
            case_id="case_002",
            reason="该案例提供了人员配置方案",
            reference_points=["增加高峰期人手"],
            cautions=[],
            source_references=[SourceField.SOLUTION_STEPS],
        ),
    ]


def _make_copy_response(**overrides):
    """构造推荐文案响应。"""
    from app.enrichment.schemas import RecommendationCopyResponse

    data = dict(
        copy_run_id="copy_run_001",
        status=EnrichmentStatus.VALID,
        items=_make_validated_items(),
        schema_validation_status=EnrichmentStatus.VALID,
        model_id="deepseek-v4-flash",
        request_purpose=RequestPurpose.RECOMMENDATION_COPY,
        token_usage={
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700,
        },
        created_at=datetime.now(timezone.utc),
    )
    data.update(overrides)
    return RecommendationCopyResponse(**data)


def _make_mock_service() -> AsyncMock:
    """提供 mock RecommendationCopyService。"""
    mock = AsyncMock()
    mock.generate_copy.return_value = _make_copy_response()
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_service():
    """提供 mock RecommendationCopyService。"""
    return _make_mock_service()


@pytest.fixture
def client(mock_service):
    """测试客户端，注入 mock 依赖。"""
    from app.enrichment.router import get_recommendation_copy_service

    app.dependency_overrides[get_recommendation_copy_service] = (
        lambda: mock_service
    )

    yield AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )

    app.dependency_overrides.clear()


# ===========================================================================
# 成功场景
# ===========================================================================


class TestRecommendationCopySuccess:
    """测试推荐文案 API 成功场景。"""

    @pytest.mark.asyncio
    async def test_successful_copy_returns_200(self, client, mock_service):
        """成功生成推荐文案应返回 HTTP 200。"""
        mock_service.generate_copy.return_value = _make_copy_response()

        response = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "valid"
        assert data["copy_run_id"] == "copy_run_001"

    @pytest.mark.asyncio
    async def test_response_preserves_candidate_order(
        self, client, mock_service,
    ):
        """响应应按输入候选顺序返回解释文案。"""
        # 按特定顺序排列的文案项
        ordered_items = [
            RecommendationCopyItem(
                case_id="case_B",
                reason="理由B",
                reference_points=["点B"],
                cautions=[],
                source_references=[SourceField.CONTEXT],
            ),
            RecommendationCopyItem(
                case_id="case_A",
                reason="理由A",
                reference_points=["点A"],
                cautions=["注意"],
                source_references=[SourceField.PROBLEM_DESCRIPTION],
            ),
            RecommendationCopyItem(
                case_id="case_C",
                reason="理由C",
                reference_points=["点C"],
                cautions=[],
                source_references=[SourceField.OUTCOME],
            ),
        ]
        mock_service.generate_copy.return_value = _make_copy_response(
            items=ordered_items,
        )

        request_data = {
            "query_text": "问题",
            "candidates": [
                {"case_id": "case_B"},
                {"case_id": "case_A"},
                {"case_id": "case_C"},
            ],
        }
        resp = await client.post(
            "/api/recommendations/copy",
            json=request_data,
        )

        assert resp.status_code == 200
        data = resp.json()
        item_ids = [item["case_id"] for item in data["items"]]
        assert item_ids == ["case_B", "case_A", "case_C"]

    @pytest.mark.asyncio
    async def test_response_does_not_contain_sorting_fields(
        self, client, mock_service,
    ):
        """响应不包含排序或相似度修改字段。"""
        mock_service.generate_copy.return_value = _make_copy_response()

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 200
        data = resp.json()

        # 响应顶层不应包含排序或相似度字段
        forbidden_top_level = {
            "sort_order",
            "similarity_score",
            "reranked",
            "filtered",
            "ranking",
        }
        for field in forbidden_top_level:
            assert field not in data, f"响应不应包含字段: {field}"

        # 每个 item 也不应包含排序或相似度字段
        for item in data["items"]:
            forbidden_item_fields = {
                "sort_order",
                "similarity_score",
                "reranked",
                "ranking_score",
            }
            for field in forbidden_item_fields:
                assert field not in item, f"item 不应包含字段: {field}"

    @pytest.mark.asyncio
    async def test_response_contains_expected_fields(
        self, client, mock_service,
    ):
        """响应应包含所有预期字段。"""
        mock_service.generate_copy.return_value = _make_copy_response()

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 200
        data = resp.json()

        # 验证响应包含必要字段
        assert "copy_run_id" in data
        assert "status" in data
        assert "items" in data
        assert "schema_validation_status" in data
        assert "model_id" in data
        assert "request_purpose" in data
        assert "token_usage" in data
        assert "created_at" in data

        # 验证 item 包含必要字段
        for item in data["items"]:
            assert "case_id" in item
            assert "reason" in item
            assert "reference_points" in item
            assert "cautions" in item
            assert "source_references" in item

    @pytest.mark.asyncio
    async def test_delegates_to_service(self, client, mock_service):
        """应委托给 RecommendationCopyService.generate_copy。"""
        await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        mock_service.generate_copy.assert_called_once()
        call_args = mock_service.generate_copy.call_args
        request = call_args[0][0]
        assert request.query_text == "门店销售下降如何改善？"
        assert len(request.candidates) == 2


# ===========================================================================
# 失败场景
# ===========================================================================


class TestRecommendationCopyFailure:
    """测试推荐文案 API 失败场景。"""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_503(self, client, mock_service):
        """LLM 调用失败应返回 HTTP 503。"""
        mock_service.generate_copy.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="LLM 调用超时",
            retryable=True,
        )

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 503
        data = resp.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_llm_rate_limited_returns_503(self, client, mock_service):
        """LLM 限流应返回 HTTP 503。"""
        mock_service.generate_copy.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_RATE_LIMITED,
            message="LLM 限流",
            retryable=True,
        )

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_llm_provider_error_returns_503(self, client, mock_service):
        """LLM 供应商故障应返回 HTTP 503。"""
        mock_service.generate_copy.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_PROVIDER_ERROR,
            message="供应商故障",
            retryable=False,
        )

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_validation_failure_returns_503(self, client, mock_service):
        """输出校验失败应返回 HTTP 503。"""
        mock_service.generate_copy.side_effect = OutputValidationException(
            error_code=ValidationErrorCode.CANDIDATE_MISMATCH,
            message="候选数量不匹配",
        )

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_injection_risk_returns_503(self, client, mock_service):
        """注入风险应返回 HTTP 503。"""
        mock_service.generate_copy.side_effect = OutputValidationException(
            error_code=ValidationErrorCode.INJECTION_SUSPECTED,
            message="检测到高风险注入模式",
        )

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_error_response_structure(self, client, mock_service):
        """错误响应应包含统一错误结构。"""
        mock_service.generate_copy.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="LLM 调用超时",
            retryable=True,
        )

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "code" in detail
        assert "message" in detail

    @pytest.mark.asyncio
    async def test_llm_failure_with_many_candidates_returns_503(
        self, client, mock_service,
    ):
        """LLM 失败时即使有多个候选也应返回 503（单次调用策略：全部失败）。"""
        mock_service.generate_copy.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="LLM 调用超时",
            retryable=True,
        )

        request_data = {
            "query_text": "门店管理问题",
            "candidates": [
                {"case_id": "case_001"},
                {"case_id": "case_002"},
                {"case_id": "case_003"},
            ],
        }

        resp = await client.post(
            "/api/recommendations/copy",
            json=request_data,
        )

        assert resp.status_code == 503


# ===========================================================================
# 候选完整性场景
# ===========================================================================


class TestRecommendationCopyCompleteness:
    """测试推荐文案 API 候选完整性。"""

    @pytest.mark.asyncio
    async def test_response_items_count_matches_candidates(
        self, client, mock_service,
    ):
        """响应中 items 数量应与请求中 candidates 数量一致。"""
        mock_service.generate_copy.return_value = _make_copy_response()

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == len(
            _make_recommendation_request()["candidates"],
        )

    @pytest.mark.asyncio
    async def test_response_preserves_all_candidate_ids(
        self, client, mock_service,
    ):
        """响应 items 应包含全部候选的 case_id，不遗漏。"""
        ordered_items = [
            RecommendationCopyItem(
                case_id="case_X",
                reason="理由X",
                reference_points=["点X"],
                cautions=[],
                source_references=[SourceField.CONTEXT],
            ),
            RecommendationCopyItem(
                case_id="case_Y",
                reason="理由Y",
                reference_points=["点Y"],
                cautions=["注意Y"],
                source_references=[SourceField.OUTCOME],
            ),
            RecommendationCopyItem(
                case_id="case_Z",
                reason="理由Z",
                reference_points=["点Z"],
                cautions=[],
                source_references=[SourceField.ROOT_CAUSE],
            ),
        ]
        mock_service.generate_copy.return_value = _make_copy_response(
            items=ordered_items,
        )

        request_data = {
            "query_text": "问题",
            "candidates": [
                {"case_id": "case_X"},
                {"case_id": "case_Y"},
                {"case_id": "case_Z"},
            ],
        }

        resp = await client.post(
            "/api/recommendations/copy",
            json=request_data,
        )

        assert resp.status_code == 200
        data = resp.json()
        item_ids = [item["case_id"] for item in data["items"]]
        assert item_ids == ["case_X", "case_Y", "case_Z"]

    @pytest.mark.asyncio
    async def test_response_never_contains_new_candidates(
        self, client, mock_service,
    ):
        """响应不应包含请求中没有的候选 case_id。"""
        mock_service.generate_copy.return_value = _make_copy_response()

        resp = await client.post(
            "/api/recommendations/copy",
            json=_make_recommendation_request(),
        )

        assert resp.status_code == 200
        data = resp.json()
        request_ids = {
            c["case_id"]
            for c in _make_recommendation_request()["candidates"]
        }
        response_ids = {item["case_id"] for item in data["items"]}
        # 响应中的 case_id 应是请求中 case_id 的子集（不应新增）
        assert response_ids.issubset(request_ids)

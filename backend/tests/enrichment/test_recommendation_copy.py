"""RecommendationCopyService 测试。

测试推荐候选文案服务编排逻辑：
- 单次 LLM 调用生成全部候选文案
- 保留输入候选顺序和 case_id 引用
- LLM 失败时抛出异常
- 校验失败时抛出异常
- Token 用量记录在响应中
- RecommendationCopyRun 正确持久化

Requirements: 5.1, 5.2, 5.3, 5.4
Boundary: RecommendationCopyService
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.common.llm_client import LLMClientError
from app.core.config import EnrichmentLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.recommendation_copy import RecommendationCopyService
from app.enrichment.schemas import (
    EnrichmentStatus,
    LLMCompletionResult,
    LLMTokenUsage,
    RecommendationCandidate,
    RecommendationCopyItem,
    RecommendationCopyRequest,
    RequestPurpose,
    SourceField,
    TaskType,
)
from app.enrichment.validators import OutputValidationException, ValidationErrorCode


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> EnrichmentLLMConfig:
    data = dict(
        provider="deepseek",
        model_id="deepseek-v4-pro",
        base_url="https://api.deepseek.com/v1",
        timeout_ms=30000,
        max_retries=2,
        privacy_acknowledged=True,
    )
    data.update(overrides)
    return EnrichmentLLMConfig(**data)


def _make_request(**overrides) -> RecommendationCopyRequest:
    data = dict(
        query_text="门店销售下降如何改善？",
        candidates=[
            RecommendationCandidate(
                case_id="case_001",
                case_summary="某门店通过优化出餐流程改善销售",
                source_fields={"problem_description": "销售下降"},
            ),
            RecommendationCandidate(
                case_id="case_002",
                case_summary="某门店通过增加人手提升服务效率",
            ),
        ],
    )
    data.update(overrides)
    return RecommendationCopyRequest(**data)


def _make_llm_result(
    content: str | None = None,
    **overrides,
) -> LLMCompletionResult:
    if content is None:
        content = (
            '{"items": ['
            '{"case_id": "case_001", "reason": "该案例与当前问题场景相似",'
            ' "reference_points": ["优化出餐流程"],'
            ' "cautions": ["注意季节性因素"],'
            ' "source_references": ["problem_description"]},'
            '{"case_id": "case_002", "reason": "该案例提供了人员配置方案",'
            ' "reference_points": ["增加高峰期人手"],'
            ' "cautions": [],'
            ' "source_references": ["solution_steps"]}'
            ']}'
        )
    data = dict(
        content=content,
        model_id="deepseek-v4-pro",
        usage=LLMTokenUsage(
            prompt_tokens=500,
            completion_tokens=200,
            total_tokens=700,
        ),
        finish_reason="stop",
    )
    data.update(overrides)
    return LLMCompletionResult(**data)


def _make_validated_items() -> list[RecommendationCopyItem]:
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


def _make_copy_run_orm(**overrides) -> MagicMock:
    """创建 mock RecommendationCopyRun ORM 对象。"""
    defaults = dict(
        copy_run_id="copy_run_001",
        query_text_hash="abc123hash",
        status=EnrichmentStatus.VALID,
        candidate_case_ids=["case_001", "case_002"],
        items=[
            {
                "case_id": "case_001",
                "reason": "该案例与当前问题场景相似",
                "reference_points": ["优化出餐流程"],
                "cautions": ["注意季节性因素"],
                "source_references": ["problem_description"],
            },
            {
                "case_id": "case_002",
                "reason": "该案例提供了人员配置方案",
                "reference_points": ["增加高峰期人手"],
                "cautions": [],
                "source_references": ["solution_steps"],
            },
        ],
        model_id="deepseek-v4-pro",
        request_purpose=RequestPurpose.RECOMMENDATION_COPY,
        token_usage={
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700,
        },
        schema_validation_status=EnrichmentStatus.VALID,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    orm = MagicMock()
    for key, value in defaults.items():
        setattr(orm, key, value)
    return orm


def _create_service(
    llm_client=None,
    prompt_catalog=None,
    validator=None,
    repository=None,
    config=None,
) -> RecommendationCopyService:
    """创建带有 mock 依赖的 RecommendationCopyService 实例。"""
    if llm_client is None:
        llm_client = AsyncMock()
    if prompt_catalog is None:
        prompt_catalog = MagicMock()
    if validator is None:
        validator = MagicMock()
    if repository is None:
        repository = AsyncMock()
    if config is None:
        config = _make_config()

    return RecommendationCopyService(
        llm_client=llm_client,
        prompt_catalog=prompt_catalog,
        validator=validator,
        repository=repository,
        config=config,
    )


# ===========================================================================
# generate_copy 测试
# ===========================================================================


class TestGenerateCopy:
    """测试 generate_copy 编排逻辑。"""

    @pytest.mark.asyncio
    async def test_successful_copy_generation(self):
        """成功生成应返回包含全部候选文案的响应。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "test prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = _make_validated_items()

        repository = AsyncMock()
        repository.create_recommendation_copy_run.return_value = _make_copy_run_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )
        request = _make_request()

        response = await service.generate_copy(request)

        assert response.status == EnrichmentStatus.VALID
        assert len(response.items) == 2
        assert response.items[0].case_id == "case_001"
        assert response.items[1].case_id == "case_002"
        assert response.model_id == "deepseek-v4-pro"
        assert response.request_purpose == RequestPurpose.RECOMMENDATION_COPY
        assert response.token_usage is not None

    @pytest.mark.asyncio
    async def test_single_llm_call_generates_all_candidates(self):
        """单次 LLM 调用应生成全部候选文案，不存在部分成功。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = _make_validated_items()

        repository = AsyncMock()
        repository.create_recommendation_copy_run.return_value = _make_copy_run_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )
        request = _make_request()

        await service.generate_copy(request)

        # 确认只调用了一次 LLM
        llm_client.complete_json.assert_called_once()
        # 确认校验传入了全部候选 case_id
        validator.validate_recommendation_copy.assert_called_once()
        call_args = validator.validate_recommendation_copy.call_args
        assert call_args[0][1] == ["case_001", "case_002"]

    @pytest.mark.asyncio
    async def test_preserves_input_candidate_order(self):
        """响应应保持输入候选顺序和 case_id 引用。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        # 返回按输入顺序排列的校验结果
        ordered_items = [
            RecommendationCopyItem(
                case_id="case_003",
                reason="第三个候选的理由",
                reference_points=["参考点A"],
                cautions=[],
                source_references=[SourceField.CONTEXT],
            ),
            RecommendationCopyItem(
                case_id="case_001",
                reason="第一个候选的理由",
                reference_points=["参考点B"],
                cautions=["注意A"],
                source_references=[SourceField.ROOT_CAUSE],
            ),
            RecommendationCopyItem(
                case_id="case_002",
                reason="第二个候选的理由",
                reference_points=["参考点C"],
                cautions=[],
                source_references=[SourceField.OUTCOME],
            ),
        ]
        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = ordered_items

        repository = AsyncMock()
        copy_run_orm = _make_copy_run_orm(
            candidate_case_ids=["case_003", "case_001", "case_002"],
        )
        repository.create_recommendation_copy_run.return_value = copy_run_orm

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        request = RecommendationCopyRequest(
            query_text="问题文本",
            candidates=[
                RecommendationCandidate(case_id="case_003"),
                RecommendationCandidate(case_id="case_001"),
                RecommendationCandidate(case_id="case_002"),
            ],
        )

        response = await service.generate_copy(request)

        # 验证顺序与输入一致
        assert [item.case_id for item in response.items] == [
            "case_003",
            "case_001",
            "case_002",
        ]

    @pytest.mark.asyncio
    async def test_llm_failure_raises_exception(self):
        """LLM 调用失败时应抛出 LLMClientError。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_TIMEOUT,
            message="LLM 调用超时",
            retryable=True,
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(LLMClientError) as exc_info:
            await service.generate_copy(_make_request())

        assert exc_info.value.error_code == ErrorCode.LLM_TIMEOUT

    @pytest.mark.asyncio
    async def test_llm_failure_persists_failed_run(self):
        """LLM 调用失败时应持久化失败的 RecommendationCopyRun。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_PROVIDER_ERROR,
            message="供应商故障",
            retryable=False,
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(LLMClientError):
            await service.generate_copy(_make_request())

        repository.create_recommendation_copy_run.assert_called_once()
        call_kwargs = repository.create_recommendation_copy_run.call_args
        # 验证持久化了失败状态
        run_data = call_kwargs[1] if call_kwargs[1] else call_kwargs[0][0]
        assert run_data.status == EnrichmentStatus.FAILED

    @pytest.mark.asyncio
    async def test_validation_failure_raises_exception(self):
        """输出校验失败时应抛出 OutputValidationException。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_recommendation_copy.side_effect = (
            OutputValidationException(
                error_code=ValidationErrorCode.CANDIDATE_MISMATCH,
                message="候选数量不匹配",
            )
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        with pytest.raises(OutputValidationException) as exc_info:
            await service.generate_copy(_make_request())

        assert exc_info.value.error_code == ValidationErrorCode.CANDIDATE_MISMATCH

    @pytest.mark.asyncio
    async def test_validation_failure_persists_failed_run(self):
        """校验失败时应持久化失败的 RecommendationCopyRun。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_recommendation_copy.side_effect = (
            OutputValidationException(
                error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
                message="schema 校验失败",
            )
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        with pytest.raises(OutputValidationException):
            await service.generate_copy(_make_request())

        repository.create_recommendation_copy_run.assert_called_once()
        call_kwargs = repository.create_recommendation_copy_run.call_args
        run_data = call_kwargs[1] if call_kwargs[1] else call_kwargs[0][0]
        assert run_data.status == EnrichmentStatus.FAILED
        assert run_data.schema_validation_status == EnrichmentStatus.FAILED

    @pytest.mark.asyncio
    async def test_token_usage_recorded_in_response(self):
        """Token 用量应记录在响应中。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_result = _make_llm_result()
        llm_result.usage = LLMTokenUsage(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
        )
        llm_client.complete_json.return_value = llm_result

        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = _make_validated_items()

        repository = AsyncMock()
        repository.create_recommendation_copy_run.return_value = _make_copy_run_orm(
            token_usage={
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
            },
        )

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        response = await service.generate_copy(_make_request())

        assert response.token_usage is not None
        assert response.token_usage["total_tokens"] == 1500

    @pytest.mark.asyncio
    async def test_copy_run_persisted_correctly(self):
        """RecommendationCopyRun 应正确持久化。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = _make_validated_items()

        repository = AsyncMock()
        repository.create_recommendation_copy_run.return_value = _make_copy_run_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        response = await service.generate_copy(_make_request())

        # 验证持久化调用
        repository.create_recommendation_copy_run.assert_called_once()
        call_kwargs = repository.create_recommendation_copy_run.call_args
        run_data = call_kwargs[1] if call_kwargs[1] else call_kwargs[0][0]

        assert run_data.status == EnrichmentStatus.VALID
        assert run_data.candidate_case_ids == ["case_001", "case_002"]
        assert run_data.model_id == "deepseek-v4-pro"
        assert run_data.request_purpose == RequestPurpose.RECOMMENDATION_COPY
        assert run_data.schema_validation_status == EnrichmentStatus.VALID
        assert len(run_data.items) == 2

        # 验证响应中包含持久化的 copy_run_id
        assert response.copy_run_id == "copy_run_001"

    @pytest.mark.asyncio
    async def test_injection_risk_blocks_copy_generation(self):
        """注入风险应阻断文案生成并抛出异常。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (
            True,
            "检测到高风险注入模式",
        )

        repository = AsyncMock()

        service = _create_service(
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(OutputValidationException) as exc_info:
            await service.generate_copy(_make_request())

        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED

    @pytest.mark.asyncio
    async def test_injection_risk_does_not_call_llm(self):
        """注入风险时不应调用 LLM。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (
            True,
            "injection detected",
        )

        llm_client = AsyncMock()
        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(OutputValidationException):
            await service.generate_copy(_make_request())

        llm_client.complete_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_call_uses_correct_request_parameters(self):
        """LLM 调用应使用正确的请求参数。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "built prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = _make_validated_items()

        repository = AsyncMock()
        repository.create_recommendation_copy_run.return_value = _make_copy_run_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        await service.generate_copy(_make_request())

        llm_call_args = llm_client.complete_json.call_args[0][0]
        assert llm_call_args.prompt == "built prompt"
        assert llm_call_args.model_id == "deepseek-v4-pro"
        assert llm_call_args.task_type == TaskType.CASE_ENRICHMENT
        assert llm_call_args.request_purpose == RequestPurpose.RECOMMENDATION_COPY

    @pytest.mark.asyncio
    async def test_does_not_modify_candidate_order_or_filter(self):
        """服务不应修改候选顺序、过滤候选或新增候选。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        # validator 返回的 case_id 列表与输入完全一致
        items = [
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
        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = items

        repository = AsyncMock()
        repository.create_recommendation_copy_run.return_value = _make_copy_run_orm(
            candidate_case_ids=["case_B", "case_A", "case_C"],
        )

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        request = RecommendationCopyRequest(
            query_text="问题",
            candidates=[
                RecommendationCandidate(case_id="case_B"),
                RecommendationCandidate(case_id="case_A"),
                RecommendationCandidate(case_id="case_C"),
            ],
        )

        response = await service.generate_copy(request)

        # 验证输入顺序被保持
        assert len(response.items) == 3
        assert [item.case_id for item in response.items] == [
            "case_B",
            "case_A",
            "case_C",
        ]
        # 验证校验时传入的候选顺序也一致
        validator_call_args = validator.validate_recommendation_copy.call_args
        assert validator_call_args[0][1] == ["case_B", "case_A", "case_C"]

    @pytest.mark.asyncio
    async def test_response_contains_copy_run_id_from_repository(self):
        """响应中的 copy_run_id 应来自仓储持久化的结果。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_recommendation_copy.return_value = _make_validated_items()

        repository = AsyncMock()
        custom_run = _make_copy_run_orm(copy_run_id="custom_run_id_999")
        repository.create_recommendation_copy_run.return_value = custom_run

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        response = await service.generate_copy(_make_request())

        assert response.copy_run_id == "custom_run_id_999"

    @pytest.mark.asyncio
    async def test_llm_rate_limited_raises_exception(self):
        """LLM 限流时应抛出 LLMClientError。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_RATE_LIMITED,
            message="LLM 限流",
            retryable=True,
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(LLMClientError) as exc_info:
            await service.generate_copy(_make_request())

        assert exc_info.value.error_code == ErrorCode.LLM_RATE_LIMITED
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_llm_privacy_config_missing_raises_exception(self):
        """隐私配置缺失时应抛出 LLMClientError。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_recommendation_injection.return_value = (False, "")
        prompt_catalog.build_recommendation_copy_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_PRIVACY_CONFIG_MISSING,
            message="隐私配置未确认",
            retryable=False,
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(LLMClientError) as exc_info:
            await service.generate_copy(_make_request())

        assert exc_info.value.error_code == ErrorCode.LLM_PRIVACY_CONFIG_MISSING
        assert exc_info.value.retryable is False

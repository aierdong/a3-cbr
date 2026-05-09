"""EnrichmentService 测试。

测试案例增强服务编排逻辑：
- 注入风险检测与阻断
- Prompt 构造与 LLM 调用编排
- 输出校验与结果保存
- 失败记录与错误映射
- 派生数据删除

Requirements: 1.1, 1.3, 1.4, 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 4.3, 4.6, 7.1, 7.2
Boundary: EnrichmentService
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.common.llm_client import LLMClientError
from app.core.config import EnrichmentLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.models import CaseEnrichmentResult
from app.enrichment.schemas import (
    CaseEnrichmentOutput,
    CaseInputSnapshot,
    DeleteEnrichmentResult,
    EnrichmentStatus,
    ErrorStage,
    LLMCompletionResult,
    MissingInformationItem,
    RequestPurpose,
    SourceField,
    StructuredSuggestions,
)
from app.enrichment.service import EnrichmentService
from app.enrichment.validators import OutputValidationException, ValidationErrorCode


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_snapshot(**overrides) -> CaseInputSnapshot:
    data = dict(
        case_id="case_001",
        problem_description="门店近三个月销售下降明显",
        problem_type="销售下降",
        context={"scene": "堂食", "period": "近三个月"},
        root_cause="出餐速度慢导致顾客流失",
        solution_steps=[
            {"step": "优化出餐流程"},
            {"step": "增加高峰期人手"},
        ],
        outcome={"result": "销售回升 15%"},
        status="active",
        updated_at=_make_utc_now(),
        store_id="store_001",
        store_name="测试门店",
        brand_id="brand_001",
        brand_name="测试品牌",
        business_type="餐饮",
        store_scale="中型",
        franchise_type="直营",
        city="上海",
        city_tier="一线",
    )
    data.update(overrides)
    return CaseInputSnapshot(**data)


def _make_config(**overrides) -> EnrichmentLLMConfig:
    data = dict(
        api_key="deepseek",
        model_id="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        timeout_ms=30000,
        max_retries=2,
        privacy_acknowledged=True,
    )
    data.update(overrides)
    return EnrichmentLLMConfig(**data)


def _make_llm_result() -> LLMCompletionResult:
    return LLMCompletionResult(
        content='{"problem_summary": "问题摘要", "solution_summary": "方案摘要", '
        '"structured_suggestions": {"problem_type_suggestion": "客户投诉", '
        '"root_cause_category": "服务流程", "applicable_scenarios": ["门店运营"], '
        '"confidence_notes": "基于案例内容分析"}, "tag_suggestions": ["服务", "投诉"], '
        '"source_references": ["problem_description", "root_cause"], '
        '"missing_information": []}',
        model_id="deepseek-v4-flash",
    )


def _make_validated_output() -> CaseEnrichmentOutput:
    return CaseEnrichmentOutput(
        problem_summary="问题摘要",
        solution_summary="方案摘要",
        structured_suggestions=StructuredSuggestions(
            problem_type_suggestion="客户投诉",
            root_cause_category="服务流程",
            applicable_scenarios=["门店运营"],
            confidence_notes="基于案例内容分析",
        ),
        tag_suggestions=["服务", "投诉"],
        source_references=[SourceField.PROBLEM_DESCRIPTION, SourceField.ROOT_CAUSE],
        missing_information=[],
    )


def _make_result_orm(**overrides) -> CaseEnrichmentResult:
    defaults = dict(
        enrichment_id="enrich_001",
        case_id="case_001",
        case_updated_at=_make_utc_now(),
        status=EnrichmentStatus.VALID,
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
        output_version="1.0",
    )
    defaults.update(overrides)
    result = CaseEnrichmentResult()
    for key, value in defaults.items():
        setattr(result, key, value)
    return result


def _create_service(
    llm_client=None,
    prompt_catalog=None,
    validator=None,
    repository=None,
    config=None,
) -> EnrichmentService:
    """创建带有 mock 依赖的 EnrichmentService 实例。"""
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

    return EnrichmentService(
        llm_client=llm_client,
        prompt_catalog=prompt_catalog,
        validator=validator,
        repository=repository,
        config=config,
    )


# ===========================================================================
# execute_enrichment 测试
# ===========================================================================


class TestExecuteEnrichment:
    """测试 execute_enrichment 编排逻辑。"""

    @pytest.mark.asyncio
    async def test_successful_enrichment(self):
        """成功增强应返回 valid 派生结果。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "test prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.return_value = _make_validated_output()

        repository = AsyncMock()
        repository.complete_run.return_value = MagicMock()
        repository.get_current_result.return_value = _make_result_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )
        snapshot = _make_snapshot()

        result = await service.execute_enrichment(snapshot, "run_001")

        assert result.status == EnrichmentStatus.VALID
        assert result.case_id == "case_001"
        prompt_catalog.check_enrichment_injection.assert_called_once_with(snapshot)
        prompt_catalog.build_enrichment_prompt.assert_called_once_with(snapshot)
        llm_client.complete_json.assert_called_once()
        validator.validate_enrichment_output.assert_called_once()
        repository.complete_run.assert_called_once()
        repository.get_current_result.assert_called_once_with("case_001")

    @pytest.mark.asyncio
    async def test_injection_risk_blocks_enrichment(self):
        """注入风险应阻断增强并标记运行失败。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (
            True,
            "检测到高风险注入模式: ignore previous instructions",
        )

        repository = AsyncMock()

        service = _create_service(
            prompt_catalog=prompt_catalog,
            repository=repository,
        )
        snapshot = _make_snapshot()

        with pytest.raises(OutputValidationException) as exc_info:
            await service.execute_enrichment(snapshot, "run_002")

        assert exc_info.value.error_code == ValidationErrorCode.INJECTION_SUSPECTED
        repository.fail_run.assert_called_once()
        fail_call_args = repository.fail_run.call_args
        assert fail_call_args[0][0] == "run_002"
        error_data = fail_call_args[0][1]
        assert error_data.error_code == ErrorCode.INJECTION_RISK_DETECTED
        assert error_data.error_stage == ErrorStage.VALIDATE

    @pytest.mark.asyncio
    async def test_injection_risk_does_not_call_llm(self):
        """注入风险时不应调用 LLM。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (True, "injection")

        llm_client = AsyncMock()
        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(OutputValidationException):
            await service.execute_enrichment(_make_snapshot(), "run_003")

        llm_client.complete_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_timeout_marks_retryable(self):
        """LLM 超时（可重试）应标记运行为 retryable（error_stage=llm_call）。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

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

        with pytest.raises(LLMClientError):
            await service.execute_enrichment(_make_snapshot(), "run_004")

        repository.mark_retryable.assert_called_once()
        repository.fail_run.assert_not_called()
        error_data = repository.mark_retryable.call_args[0][1]
        assert error_data.error_code == ErrorCode.LLM_TIMEOUT
        assert error_data.error_stage == ErrorStage.LLM_CALL

    @pytest.mark.asyncio
    async def test_llm_rate_limited_marks_retryable(self):
        """LLM 限流（可重试）应标记运行为 retryable。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

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

        with pytest.raises(LLMClientError):
            await service.execute_enrichment(_make_snapshot(), "run_005")

        repository.mark_retryable.assert_called_once()
        error_data = repository.mark_retryable.call_args[0][1]
        assert error_data.error_code == ErrorCode.LLM_RATE_LIMITED
        assert error_data.error_stage == ErrorStage.LLM_CALL

    @pytest.mark.asyncio
    async def test_llm_provider_error_marks_retryable(self):
        """LLM 供应商故障（可重试）应标记运行为 retryable。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_PROVIDER_ERROR,
            message="供应商故障",
            retryable=True,
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(LLMClientError):
            await service.execute_enrichment(_make_snapshot(), "run_006")

        repository.mark_retryable.assert_called_once()
        error_data = repository.mark_retryable.call_args[0][1]
        assert error_data.error_code == ErrorCode.LLM_PROVIDER_ERROR
        assert error_data.error_stage == ErrorStage.LLM_CALL

    @pytest.mark.asyncio
    async def test_llm_privacy_config_missing_fails_run(self):
        """隐私配置缺失应标记运行失败。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

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

        with pytest.raises(LLMClientError):
            await service.execute_enrichment(_make_snapshot(), "run_007")

        error_data = repository.fail_run.call_args[0][1]
        assert error_data.error_code == ErrorCode.LLM_PRIVACY_CONFIG_MISSING
        assert error_data.error_stage == ErrorStage.LLM_CALL

    @pytest.mark.asyncio
    async def test_llm_invalid_response_fails_run_with_parse_stage(self):
        """LLM 无效响应应标记运行失败（error_stage=parse）。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.side_effect = LLMClientError(
            error_code=ErrorCode.LLM_INVALID_RESPONSE,
            message="LLM 响应无法解析",
            retryable=False,
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            repository=repository,
        )

        with pytest.raises(LLMClientError):
            await service.execute_enrichment(_make_snapshot(), "run_008")

        error_data = repository.fail_run.call_args[0][1]
        assert error_data.error_code == ErrorCode.LLM_INVALID_RESPONSE
        assert error_data.error_stage == ErrorStage.PARSE

    @pytest.mark.asyncio
    async def test_validation_failure_fails_run(self):
        """输出校验失败应标记运行失败（error_stage=validate）。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.side_effect = OutputValidationException(
            error_code=ValidationErrorCode.LLM_INVALID_RESPONSE,
            message="schema 校验失败",
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        with pytest.raises(OutputValidationException):
            await service.execute_enrichment(_make_snapshot(), "run_009")

        repository.fail_run.assert_called_once()
        error_data = repository.fail_run.call_args[0][1]
        assert error_data.error_code == ValidationErrorCode.LLM_INVALID_RESPONSE
        assert error_data.error_stage == ErrorStage.VALIDATE

    @pytest.mark.asyncio
    async def test_injection_suspected_in_output_fails_run(self):
        """输出侧注入嫌疑应标记运行失败。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.side_effect = OutputValidationException(
            error_code=ValidationErrorCode.INJECTION_SUSPECTED,
            message="输出侧注入嫌疑",
        )

        repository = AsyncMock()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        with pytest.raises(OutputValidationException):
            await service.execute_enrichment(_make_snapshot(), "run_010")

        error_data = repository.fail_run.call_args[0][1]
        assert error_data.error_code == ValidationErrorCode.INJECTION_SUSPECTED
        assert error_data.error_stage == ErrorStage.VALIDATE

    @pytest.mark.asyncio
    async def test_persistence_failure_fails_run(self):
        """持久化失败应标记运行失败（error_stage=persist）。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.return_value = _make_validated_output()

        repository = AsyncMock()
        repository.complete_run.side_effect = RuntimeError("数据库连接失败")

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        with pytest.raises(RuntimeError, match="数据库连接失败"):
            await service.execute_enrichment(_make_snapshot(), "run_011")

        # 完整的 fail_run 调用（包括持久化失败的 fail_run）
        assert repository.fail_run.call_count == 1
        error_data = repository.fail_run.call_args[0][1]
        assert error_data.error_code == ErrorCode.INTERNAL_ERROR
        assert error_data.error_stage == ErrorStage.PERSIST

    @pytest.mark.asyncio
    async def test_passes_request_purpose_to_llm(self):
        """应将 request_purpose 传递给 LLM 请求。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.return_value = _make_validated_output()

        repository = AsyncMock()
        repository.complete_run.return_value = MagicMock()
        repository.get_current_result.return_value = _make_result_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        await service.execute_enrichment(
            _make_snapshot(),
            "run_012",
            request_purpose=RequestPurpose.CASE_ENRICHMENT,
        )

        llm_call_args = llm_client.complete_json.call_args[0][0]
        assert llm_call_args.request_purpose == RequestPurpose.CASE_ENRICHMENT
        assert llm_call_args.model_id == "deepseek-v4-pro"

    @pytest.mark.asyncio
    async def test_result_missing_after_complete_raises(self):
        """结果写入后查询不到应抛出 RuntimeError。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.return_value = _make_validated_output()

        repository = AsyncMock()
        repository.complete_run.return_value = MagicMock()
        repository.get_current_result.return_value = None

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        with pytest.raises(RuntimeError, match="增强结果写入后查询失败"):
            await service.execute_enrichment(_make_snapshot(), "run_013")

    @pytest.mark.asyncio
    async def test_missing_information_scenario(self):
        """内容不足时 LLM 应在 missing_information 中返回缺失说明。

        Requirement 2.3: 内容不足时不生成或发布编造摘要。
        """
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = LLMCompletionResult(
            content='{"problem_summary": null, "solution_summary": null, '
            '"structured_suggestions": {"problem_type_suggestion": "无法判断", '
            '"root_cause_category": "信息不足", "applicable_scenarios": ["未知"], '
            '"confidence_notes": "信息不足"}, "tag_suggestions": [], '
            '"source_references": [], '
            '"missing_information": [{"field": "problem_description", '
            '"reason": "问题描述过于简略", "blocking_level": "required"}]}',
            model_id="deepseek-v4-pro",
        )

        validated = CaseEnrichmentOutput(
            problem_summary=None,
            solution_summary=None,
            structured_suggestions=StructuredSuggestions(
                problem_type_suggestion="无法判断",
                root_cause_category="信息不足",
                applicable_scenarios=["未知"],
                confidence_notes="信息不足",
            ),
            tag_suggestions=[],
            source_references=[],
            missing_information=[
                MissingInformationItem(
                    field=SourceField.PROBLEM_DESCRIPTION,
                    reason="问题描述过于简略",
                    blocking_level="required",
                ),
            ],
        )
        validator = MagicMock()
        validator.validate_enrichment_output.return_value = validated

        result_orm = _make_result_orm(
            problem_summary=None,
            solution_summary=None,
            tag_suggestions=[],
            source_references=[],
        )
        repository = AsyncMock()
        repository.complete_run.return_value = MagicMock()
        repository.get_current_result.return_value = result_orm

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        result = await service.execute_enrichment(_make_snapshot(), "run_014")

        assert result.problem_summary is None
        assert result.solution_summary is None
        assert result.status == EnrichmentStatus.VALID


# ===========================================================================
# delete_enrichment_data 测试
# ===========================================================================


class TestDeleteEnrichmentData:
    """测试 delete_enrichment_data 方法。

    Requirements: 7.1, 7.2
    """

    @pytest.mark.asyncio
    async def test_delete_by_case_id_delegates_to_repository(self):
        """按 case_id 删除应委托仓储执行。"""
        repository = AsyncMock()
        repository.delete_enrichment_data.return_value = DeleteEnrichmentResult(
            success=True,
            deleted_count=2,
            deleted_at=_make_utc_now(),
        )

        service = _create_service(repository=repository)
        result = await service.delete_enrichment_data(case_id="case_001")

        assert result.success is True
        assert result.deleted_count == 2
        repository.delete_enrichment_data.assert_called_once_with(
            case_id="case_001",
            enrichment_id=None,
        )

    @pytest.mark.asyncio
    async def test_delete_by_enrichment_id_delegates_to_repository(self):
        """按 enrichment_id 删除应委托仓储执行。"""
        repository = AsyncMock()
        repository.delete_enrichment_data.return_value = DeleteEnrichmentResult(
            success=True,
            deleted_count=1,
            deleted_at=_make_utc_now(),
        )

        service = _create_service(repository=repository)
        result = await service.delete_enrichment_data(
            enrichment_id="enrich_001",
        )

        assert result.success is True
        assert result.deleted_count == 1
        repository.delete_enrichment_data.assert_called_once_with(
            case_id=None,
            enrichment_id="enrich_001",
        )

    @pytest.mark.asyncio
    async def test_delete_by_both_ids(self):
        """同时提供 case_id 和 enrichment_id 应委托仓储执行。"""
        repository = AsyncMock()
        repository.delete_enrichment_data.return_value = DeleteEnrichmentResult(
            success=True,
            deleted_count=2,
            deleted_at=_make_utc_now(),
        )

        service = _create_service(repository=repository)
        result = await service.delete_enrichment_data(
            case_id="case_001",
            enrichment_id="enrich_001",
        )

        assert result.success is True
        repository.delete_enrichment_data.assert_called_once_with(
            case_id="case_001",
            enrichment_id="enrich_001",
        )

    @pytest.mark.asyncio
    async def test_delete_no_ids_raises_value_error(self):
        """未提供 case_id 或 enrichment_id 应抛出 ValueError。"""
        repository = AsyncMock()

        service = _create_service(repository=repository)

        with pytest.raises(ValueError, match="至少提供"):
            await service.delete_enrichment_data()

        repository.delete_enrichment_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_idempotent_returns_zero(self):
        """删除不存在的数据应返回 deleted_count=0（幂等性）。"""
        repository = AsyncMock()
        repository.delete_enrichment_data.return_value = DeleteEnrichmentResult(
            success=True,
            deleted_count=0,
            deleted_at=_make_utc_now(),
        )

        service = _create_service(repository=repository)
        result = await service.delete_enrichment_data(case_id="nonexistent")

        assert result.success is True
        assert result.deleted_count == 0


# ===========================================================================
# 重复增强与派生内容独立性测试
# ===========================================================================


class TestReEnrichmentAndIsolation:
    """测试重复增强流程和派生内容独立性。

    Requirements: 4.6, 2.5, 3.4
    """

    @pytest.mark.asyncio
    async def test_re_enrichment_calls_complete_run_with_new_result(self):
        """重复增强应调用 complete_run 写入新结果（仓储层负责删除旧记录）。

        验证：service 正确构造 result_create 并传递给 repository.complete_run。
        Repository.complete_run 在事务内原子性地删除旧结果再写入新结果。
        Requirement: 4.6
        """
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.return_value = _make_validated_output()

        repository = AsyncMock()
        repository.complete_run.return_value = MagicMock()
        repository.get_current_result.return_value = _make_result_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )
        snapshot = _make_snapshot()

        # 第一次增强
        await service.execute_enrichment(snapshot, "run_001")
        assert repository.complete_run.call_count == 1

        # 第二次增强（同一 case_id）
        await service.execute_enrichment(snapshot, "run_002")
        assert repository.complete_run.call_count == 2

        # 验证两次调用都传递了正确的 result_create
        for call in repository.complete_run.call_args_list:
            result_create = call[0][1]
            assert result_create.case_id == "case_001"
            assert result_create.status == EnrichmentStatus.VALID
            assert result_create.problem_summary == "问题摘要"
            assert result_create.solution_summary == "方案摘要"

    @pytest.mark.asyncio
    async def test_enrichment_does_not_write_back_to_case_base_fields(self):
        """增强结果应仅保存在 CaseEnrichmentResult 中，不修改案例基础字段。

        验证：service 调用 complete_run 时传递的 result_create 只包含
        派生结果字段（enrichment_id, case_id, status, problem_summary,
        solution_summary, structured_suggestions, tag_suggestions,
        source_references, output_version），不包含案例基础字段。
        Requirement: 2.5, 3.4
        """
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.return_value = _make_validated_output()

        repository = AsyncMock()
        repository.complete_run.return_value = MagicMock()
        repository.get_current_result.return_value = _make_result_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        await service.execute_enrichment(_make_snapshot(), "run_001")

        # 验证 result_create 不包含案例基础字段
        result_create = repository.complete_run.call_args[0][1]
        result_dict = result_create.model_dump()

        # 应包含派生结果字段
        assert "enrichment_id" in result_dict
        assert "case_id" in result_dict
        assert "problem_summary" in result_dict
        assert "solution_summary" in result_dict
        assert "structured_suggestions" in result_dict
        assert "tag_suggestions" in result_dict
        assert "source_references" in result_dict
        assert "output_version" in result_dict

        # 不应包含案例基础管理字段
        assert "store_id" not in result_dict
        assert "brand_id" not in result_dict
        assert "store_name" not in result_dict
        assert "business_type" not in result_dict
        assert "franchise_type" not in result_dict
        assert "city" not in result_dict

    @pytest.mark.asyncio
    async def test_successful_enrichment_output_version_is_set(self):
        """成功增强应设置 output_version。"""
        prompt_catalog = MagicMock()
        prompt_catalog.check_enrichment_injection.return_value = (False, "")
        prompt_catalog.build_enrichment_prompt.return_value = "prompt"

        llm_client = AsyncMock()
        llm_client.complete_json.return_value = _make_llm_result()

        validator = MagicMock()
        validator.validate_enrichment_output.return_value = _make_validated_output()

        repository = AsyncMock()
        repository.complete_run.return_value = MagicMock()
        repository.get_current_result.return_value = _make_result_orm()

        service = _create_service(
            llm_client=llm_client,
            prompt_catalog=prompt_catalog,
            validator=validator,
            repository=repository,
        )

        await service.execute_enrichment(_make_snapshot(), "run_001")

        result_create = repository.complete_run.call_args[0][1]
        assert result_create.output_version == "1.0"
        assert result_create.case_updated_at is not None


# ===========================================================================
# _map_llm_error_stage 测试
# ===========================================================================


class TestMapLLMErrorStage:
    """测试 LLM 错误码到错误阶段的映射。"""

    def test_timeout_maps_to_llm_call(self):
        """LLM_TIMEOUT 应映射到 llm_call 阶段。"""
        assert (
            EnrichmentService._map_llm_error_stage(ErrorCode.LLM_TIMEOUT)
            == ErrorStage.LLM_CALL
        )

    def test_rate_limited_maps_to_llm_call(self):
        """LLM_RATE_LIMITED 应映射到 llm_call 阶段。"""
        assert (
            EnrichmentService._map_llm_error_stage(ErrorCode.LLM_RATE_LIMITED)
            == ErrorStage.LLM_CALL
        )

    def test_provider_error_maps_to_llm_call(self):
        """LLM_PROVIDER_ERROR 应映射到 llm_call 阶段。"""
        assert (
            EnrichmentService._map_llm_error_stage(ErrorCode.LLM_PROVIDER_ERROR)
            == ErrorStage.LLM_CALL
        )

    def test_privacy_config_missing_maps_to_llm_call(self):
        """LLM_PRIVACY_CONFIG_MISSING 应映射到 llm_call 阶段。"""
        assert (
            EnrichmentService._map_llm_error_stage(
                ErrorCode.LLM_PRIVACY_CONFIG_MISSING,
            )
            == ErrorStage.LLM_CALL
        )

    def test_invalid_response_maps_to_parse(self):
        """LLM_INVALID_RESPONSE 应映射到 parse 阶段。"""
        assert (
            EnrichmentService._map_llm_error_stage(ErrorCode.LLM_INVALID_RESPONSE)
            == ErrorStage.PARSE
        )

    def test_unknown_error_maps_to_llm_call(self):
        """未知错误码应默认映射到 llm_call 阶段。"""
        assert (
            EnrichmentService._map_llm_error_stage("UNKNOWN_ERROR")
            == ErrorStage.LLM_CALL
        )

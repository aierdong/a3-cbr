"""案例增强服务编排。

编排案例快照读取、Prompt 构造、LLM 调用、输出校验、结果保存和失败记录。
内容不足时返回缺失信息说明，不生成或发布编造摘要。
校验通过后委托 EnrichmentRepository.complete_run 写入新的 valid 结果。
实现 delete_enrichment_data 委托仓储删除指定案例的所有派生数据。

Requirements: 1.1, 1.3, 1.4, 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 4.3, 4.6, 7.1, 7.2
Boundary: EnrichmentService
"""

import logging
import uuid
from typing import Optional

from app.common.llm_client import LLMClient, LLMClientError
from app.core.config import EnrichmentLLMConfig
from app.core.errors import ErrorCode
from app.enrichment.models import CaseEnrichmentResult
from app.enrichment.prompts import PromptCatalog
from app.enrichment.repository import EnrichmentRepository
from app.enrichment.schemas import (
    CaseEnrichmentResultCreate,
    CaseInputSnapshot,
    DeleteEnrichmentResult,
    EnrichmentErrorData,
    EnrichmentStatus,
    ErrorStage,
    LLMCompletionRequest,
    RequestPurpose,
    TaskType,
)
from app.enrichment.validators import (
    OUTPUT_VERSION,
    OutputValidationException,
    OutputValidator,
    ValidationErrorCode,
)

logger = logging.getLogger(__name__)


class EnrichmentService:
    """案例增强服务，编排单次增强逻辑。

    职责：
    - 注入风险检测
    - Prompt 构造
    - LLM 调用
    - 输出校验
    - 结果保存（通过 EnrichmentRepository.complete_run）
    - 失败记录（通过 EnrichmentRepository.fail_run）

    不职责：
    - 不创建运行记录（由 EnrichmentJobRunner 负责）
    - 不直接调用 CaseSnapshotProvider（由 EnrichmentJobRunner 负责）
    - 不修改 A3Case 基础字段
    """

    def __init__(
        self,
        llm_client: LLMClient,
        prompt_catalog: PromptCatalog,
        validator: OutputValidator,
        repository: EnrichmentRepository,
        config: EnrichmentLLMConfig,
    ) -> None:
        """初始化服务。

        Args:
            llm_client: 共享 LLM 客户端。
            prompt_catalog: Prompt 模板管理。
            validator: 输出校验器。
            repository: 增强数据仓储。
            config: LLM 增强配置。
        """
        self._llm_client = llm_client
        self._prompt_catalog = prompt_catalog
        self._validator = validator
        self._repository = repository
        self._config = config

    async def execute_enrichment(
        self,
        input_snapshot: CaseInputSnapshot,
        run_id: str,
        request_purpose: RequestPurpose = RequestPurpose.CASE_ENRICHMENT,
    ) -> CaseEnrichmentResult:
        """执行单次案例增强。

        编排流程：
        1. 注入风险检测
        2. 构造 Prompt
        3. 调用 LLM
        4. 校验输出
        5. 委托仓储写入结果（原子性删除旧记录 + 写入新结果）

        任何阶段失败均通过 repository.fail_run 记录失败信息。

        Args:
            input_snapshot: 案例输入快照。
            run_id: 运行标识（由 EnrichmentJobRunner 创建）。
            request_purpose: 请求目的，默认为案例增强。

        Returns:
            校验通过的案例增强派生结果 ORM 对象。

        Raises:
            OutputValidationException: 注入风险或输出校验失败。
            LLMClientError: LLM 调用失败（不可重试时）。
        """
        case_id = input_snapshot.case_id

        # -----------------------------------------------------------
        # 1. 注入风险检测
        # -----------------------------------------------------------
        is_blocked, reason = self._prompt_catalog.check_enrichment_injection(
            input_snapshot,
        )
        if is_blocked:
            logger.warning(
                "注入风险阻断: case_id=%s, run_id=%s, reason=%s",
                case_id,
                run_id,
                reason,
            )
            await self._fail_run(
                run_id,
                error_code=ErrorCode.INJECTION_RISK_DETECTED,
                error_stage=ErrorStage.VALIDATE,
            )
            raise OutputValidationException(
                error_code=ValidationErrorCode.INJECTION_SUSPECTED,
                message=reason,
            )

        # -----------------------------------------------------------
        # 2. 构造 Prompt
        # -----------------------------------------------------------
        prompt_text = self._prompt_catalog.build_enrichment_prompt(input_snapshot)

        llm_request = LLMCompletionRequest(
            prompt=prompt_text,
            model_id=self._config.model_id,
            task_type=TaskType.CASE_ENRICHMENT,
            request_purpose=request_purpose,
        )

        # -----------------------------------------------------------
        # 3. 调用 LLM
        # -----------------------------------------------------------
        try:
            llm_result = await self._llm_client.complete_json(llm_request)
        except LLMClientError as exc:
            logger.warning(
                "LLM 调用失败: case_id=%s, run_id=%s, error_code=%s, message=%s",
                case_id,
                run_id,
                exc.error_code,
                exc.message,
            )
            error_stage = self._map_llm_error_stage(exc.error_code)
            await self._fail_run(
                run_id,
                error_code=exc.error_code,
                error_stage=error_stage,
            )
            raise

        # -----------------------------------------------------------
        # 4. 校验输出
        # -----------------------------------------------------------
        try:
            validated_output = self._validator.validate_enrichment_output(
                llm_result.content,
                case_id,
            )
        except OutputValidationException as exc:
            logger.warning(
                "输出校验失败: case_id=%s, run_id=%s, error_code=%s, message=%s",
                case_id,
                run_id,
                exc.error_code,
                exc.message,
            )
            await self._fail_run(
                run_id,
                error_code=exc.error_code,
                error_stage=ErrorStage.VALIDATE,
            )
            raise

        # -----------------------------------------------------------
        # 5. 写入结果（仓储层保证事务原子性）
        # -----------------------------------------------------------
        enrichment_id = str(uuid.uuid4())

        result_create = CaseEnrichmentResultCreate(
            enrichment_id=enrichment_id,
            case_id=case_id,
            case_updated_at=input_snapshot.updated_at,
            status=EnrichmentStatus.VALID,
            problem_summary=validated_output.problem_summary,
            solution_summary=validated_output.solution_summary,
            structured_suggestions=validated_output.structured_suggestions.model_dump(),
            tag_suggestions=validated_output.tag_suggestions,
            source_references=validated_output.source_references,
            output_version=OUTPUT_VERSION,
        )

        try:
            await self._repository.complete_run(run_id, result_create)
        except Exception as exc:
            logger.error(
                "结果持久化失败: case_id=%s, run_id=%s, error=%s",
                case_id,
                run_id,
                str(exc),
            )
            await self._fail_run(
                run_id,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_stage=ErrorStage.PERSIST,
            )
            raise

        logger.info(
            "增强完成: case_id=%s, run_id=%s, enrichment_id=%s",
            case_id,
            run_id,
            enrichment_id,
        )

        # 从仓储查询并返回完整结果
        result = await self._repository.get_current_result(case_id)
        if result is None:
            raise RuntimeError(
                f"增强结果写入后查询失败: case_id={case_id}, enrichment_id={enrichment_id}"
            )
        return result

    async def delete_enrichment_data(
        self,
        case_id: Optional[str] = None,
        enrichment_id: Optional[str] = None,
    ) -> DeleteEnrichmentResult:
        """删除指定案例或增强标识的所有派生数据。

        委托 EnrichmentRepository.delete_enrichment_data 在同一事务内
        原子性地删除派生结果和运行记录。

        Args:
            case_id: 案例标识，按案例删除所有增强数据。
            enrichment_id: 增强标识，删除特定增强记录。

        Returns:
            删除结果，包含 success、deleted_count、deleted_at。

        Raises:
            ValueError: 未提供 case_id 或 enrichment_id 时抛出。
        """
        if case_id is None and enrichment_id is None:
            raise ValueError(
                "至少提供 case_id 或 enrichment_id 之一",
            )

        return await self._repository.delete_enrichment_data(
            case_id=case_id,
            enrichment_id=enrichment_id,
        )

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    async def _fail_run(
        self,
        run_id: str,
        error_code: str,
        error_stage: ErrorStage,
    ) -> None:
        """标记运行失败。

        Args:
            run_id: 运行标识。
            error_code: 错误码。
            error_stage: 错误阶段。
        """
        error = EnrichmentErrorData(
            error_code=error_code,
            error_stage=error_stage,
        )
        await self._repository.fail_run(run_id, error)

    @staticmethod
    def _map_llm_error_stage(error_code: str) -> ErrorStage:
        """将 LLM 错误码映射到错误阶段。

        Args:
            error_code: LLM 错误码。

        Returns:
            对应的错误阶段。
        """
        mapping = {
            ErrorCode.LLM_TIMEOUT: ErrorStage.LLM_CALL,
            ErrorCode.LLM_RATE_LIMITED: ErrorStage.LLM_CALL,
            ErrorCode.LLM_PROVIDER_ERROR: ErrorStage.LLM_CALL,
            ErrorCode.LLM_PRIVACY_CONFIG_MISSING: ErrorStage.LLM_CALL,
            ErrorCode.LLM_INVALID_RESPONSE: ErrorStage.PARSE,
        }
        return mapping.get(error_code, ErrorStage.LLM_CALL)

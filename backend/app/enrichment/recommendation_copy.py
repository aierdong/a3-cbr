"""推荐候选文案服务。

接收当前问题、已排序候选案例和候选来源信息，
将所有候选合入同一 prompt 一次性调用 LLM 生成全部候选的推荐理由、
参考解决点和注意事项。

保留输入候选顺序和 case_id 引用，不新增候选、不过滤候选、
不改变相似度或排序。

Requirements: 5.1, 5.2, 5.3, 5.4
Boundary: RecommendationCopyService
"""

import hashlib
import logging
import uuid

from app.core.llm_client import LLMClient, LLMClientError
from app.core.config import EnrichmentLLMConfig
from app.enrichment.prompts import PromptCatalog
from app.enrichment.repository import EnrichmentRepository
from app.enrichment.schemas import (
    EnrichmentStatus,
    LLMCompletionRequest,
    LLM_RESPONSE_FORMAT_JSON_OBJECT,
    RecommendationCopyRequest,
    RecommendationCopyResponse,
    RecommendationCopyRunCreate,
    RequestPurpose,
    TaskType,
)
from app.enrichment.validators import (
    OutputValidationException,
    OutputValidator,
)

logger = logging.getLogger(__name__)


class RecommendationCopyService:
    """推荐候选文案服务。

    对已排序推荐候选生成解释文案，不参与排序。

    职责：
    - 注入风险检测
    - Prompt 构造（通过 PromptCatalog）
    - 单次 LLM 调用（通过 LLMClient）
    - 输出校验（通过 OutputValidator）
    - RecommendationCopyRun 持久化（通过 EnrichmentRepository）

    不职责：
    - 不决定召回、过滤、相似度分值或最终排序
    - 不新增或过滤候选
    - 不改变输入候选顺序
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

    async def generate_copy(
        self,
        request: RecommendationCopyRequest,
    ) -> RecommendationCopyResponse:
        """生成推荐候选文案。

        编排流程：
        1. 注入风险检测
        2. 构造 Prompt
        3. 单次调用 LLM
        4. 校验输出
        5. 持久化 RecommendationCopyRun

        单次调用策略：只有"全部成功"或"全部失败"两种结果。

        Args:
            request: 推荐文案请求，含当前问题和已排序候选列表。

        Returns:
            推荐文案响应。

        Raises:
            LLMClientError: LLM 调用失败时抛出。
            OutputValidationException: 注入风险或输出校验失败时抛出。
        """
        candidate_case_ids = [c.case_id for c in request.candidates]
        copy_run_id = str(uuid.uuid4())

        # -----------------------------------------------------------
        # 1. 注入风险检测
        # -----------------------------------------------------------
        is_blocked, reason = self._prompt_catalog.check_recommendation_injection(
            request,
        )
        if is_blocked:
            logger.warning(
                "推荐文案注入风险阻断: copy_run_id=%s, reason=%s",
                copy_run_id,
                reason,
            )
            # 持久化失败记录
            await self._persist_failed_run(
                copy_run_id=copy_run_id,
                request=request,
                candidate_case_ids=candidate_case_ids,
                schema_validation_status=EnrichmentStatus.FAILED,
            )
            raise OutputValidationException(
                error_code="INJECTION_SUSPECTED",
                message=reason,
            )

        # -----------------------------------------------------------
        # 2. 构造 Prompt
        # -----------------------------------------------------------
        prompt_text = self._prompt_catalog.build_recommendation_copy_prompt(request)

        llm_request = LLMCompletionRequest(
            prompt=prompt_text,
            model_id=self._config.model_id,
            task_type=TaskType.CASE_ENRICHMENT,
            request_purpose=RequestPurpose.RECOMMENDATION_COPY,
            response_format=LLM_RESPONSE_FORMAT_JSON_OBJECT,
        )

        # -----------------------------------------------------------
        # 3. 单次调用 LLM
        # -----------------------------------------------------------
        try:
            llm_result = await self._llm_client.complete_json(llm_request)
        except LLMClientError as exc:
            logger.warning(
                "推荐文案 LLM 调用失败: copy_run_id=%s, error_code=%s, "
                "retryable=%s, http_status=%s, message=%s",
                copy_run_id,
                exc.error_code,
                exc.retryable,
                exc.status_code,
                exc.message,
            )
            await self._persist_failed_run(
                copy_run_id=copy_run_id,
                request=request,
                candidate_case_ids=candidate_case_ids,
                schema_validation_status=EnrichmentStatus.FAILED,
            )
            raise

        # -----------------------------------------------------------
        # 4. 校验输出
        # -----------------------------------------------------------
        try:
            validated_items = self._validator.validate_recommendation_copy(
                llm_result.content,
                candidate_case_ids,
            )
        except OutputValidationException as exc:
            logger.warning(
                "推荐文案校验失败: copy_run_id=%s, error_code=%s",
                copy_run_id,
                exc.error_code,
            )
            await self._persist_failed_run(
                copy_run_id=copy_run_id,
                request=request,
                candidate_case_ids=candidate_case_ids,
                schema_validation_status=EnrichmentStatus.FAILED,
            )
            raise

        # -----------------------------------------------------------
        # 5. 持久化 RecommendationCopyRun
        # -----------------------------------------------------------
        token_usage_dict = None
        if llm_result.usage is not None:
            token_usage_dict = {
                "prompt_tokens": llm_result.usage.prompt_tokens,
                "completion_tokens": llm_result.usage.completion_tokens,
                "total_tokens": llm_result.usage.total_tokens,
            }

        items_dicts = [item.model_dump() for item in validated_items]
        query_text_hash = hashlib.sha256(
            request.query_text.encode("utf-8"),
        ).hexdigest()

        run_create = RecommendationCopyRunCreate(
            copy_run_id=copy_run_id,
            query_text_hash=query_text_hash,
            status=EnrichmentStatus.VALID,
            candidate_case_ids=candidate_case_ids,
            items=items_dicts,
            model_id=llm_result.model_id,
            request_purpose=RequestPurpose.RECOMMENDATION_COPY,
            token_usage=token_usage_dict,
            schema_validation_status=EnrichmentStatus.VALID,
        )

        persisted_run = await self._repository.create_recommendation_copy_run(
            run_create,
        )

        logger.info(
            "推荐文案生成完成: copy_run_id=%s, candidate_count=%d",
            copy_run_id,
            len(candidate_case_ids),
        )

        # 构造响应
        return RecommendationCopyResponse(
            copy_run_id=persisted_run.copy_run_id,
            status=EnrichmentStatus.VALID,
            items=validated_items,
            schema_validation_status=EnrichmentStatus.VALID,
            model_id=llm_result.model_id,
            request_purpose=RequestPurpose.RECOMMENDATION_COPY,
            token_usage=token_usage_dict,
            created_at=persisted_run.created_at,
        )

    async def _persist_failed_run(
        self,
        copy_run_id: str,
        request: RecommendationCopyRequest,
        candidate_case_ids: list[str],
        schema_validation_status: EnrichmentStatus,
    ) -> None:
        """持久化失败的推荐文案运行记录。

        Args:
            copy_run_id: 运行标识。
            request: 原始请求。
            candidate_case_ids: 候选 case_id 列表。
            schema_validation_status: schema 校验状态。
        """
        query_text_hash = hashlib.sha256(
            request.query_text.encode("utf-8"),
        ).hexdigest()

        run_create = RecommendationCopyRunCreate(
            copy_run_id=copy_run_id,
            query_text_hash=query_text_hash,
            status=EnrichmentStatus.FAILED,
            candidate_case_ids=candidate_case_ids,
            items=[],
            model_id=self._config.model_id,
            request_purpose=RequestPurpose.RECOMMENDATION_COPY,
            token_usage=None,
            schema_validation_status=schema_validation_status,
        )

        try:
            await self._repository.create_recommendation_copy_run(run_create)
        except Exception as exc:
            logger.error(
                "推荐文案失败记录持久化失败: copy_run_id=%s, error=%s",
                copy_run_id,
                str(exc),
            )

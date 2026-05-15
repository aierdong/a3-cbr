"""RecommendationService：端到端检索推荐流程编排。

串联 QueryNormalizer、向量候选消费、候选快照读取、语义精排、
结构化局部评分、业务评分、分值聚合、推荐解释和结果组装。

使用 RecommendationRunContext 上下文管理器保证运行记录终态一致性。

设计约束：
- 先 create_run 再执行 LLM normalizer
- Requirement 1.7 失败时须 fail_run 且响应含 recommendation_run_id
- reranker + aggregation 同时失败时按业务分优先降级

Boundary: RecommendationService_
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional, Sequence

from app.core.config import RetrievalConfig
from app.retrieval.business_scoring import BusinessScore, BusinessScoreCalculator
from app.retrieval.case_provider import RecommendationCaseProvider
from app.retrieval.explainer import (
    ExplanationResult,
    RecommendationExplainer,
    is_explainer_enabled,
)
from app.retrieval.query import QueryNormalizer
from app.retrieval.relevance_filter import (
    RelevanceFilterConfig,
    filter_relevant_candidates,
)
from app.retrieval.repository import RecommendationRepository
from app.retrieval.run_context import RecommendationRunContext
from app.retrieval.schemas import (
    AggregationStatus,
    CandidateSnapshot,
    ExplanationStatus,
    NormalizedRetrievalQuery,
    RecommendationErrorData,
    RecommendationItemRecord,
    RecommendationItemResponse,
    RecommendationResponse,
    RecommendationRunCreate,
    RecommendationRunResponse,
    RetrievalRequest,
    RerankerStatus,
    RunResult,
    RunStatus,
    ScoreBreakdownResponse,
    ScoreBreakdownSource,
)
from app.retrieval.score_aggregator import (
    AggregatedCandidate,
    ScoreAggregator,
    ScoredCandidate,
)
from app.retrieval.structured_similarity import (
    StructuredSimilarityScore,
    StructuredSimilarityScorer,
)
from app.retrieval.vector_port import VectorSearchPort


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from app.retrieval.reranker_client import RerankerClient


# =============================================================================
# 常量
# =============================================================================

# 默认聚合权重
DEFAULT_SCORE_WEIGHTS = {
    "vector": 0.3,
    "semantic": 0.4,
    "structured": 0.1,
    "business": 0.2,
}

# 降级原因
DEGRADED_REASON_RERANKER_FAILED = "reranker_failed"
DEGRADED_REASON_AGGREGATION_FAILED = "aggregation_failed"
DEGRADED_REASON_RERANKER_AND_AGGREGATION_FAILED = "reranker_and_aggregation_failed"
DEGRADED_REASON_EXPLANATION_FALLBACK = "explanation_fallback"
DEGRADED_REASON_NO_CANDIDATES = "no_candidates"
DEGRADED_REASON_NO_RELEVANT_CANDIDATES = "no_relevant_candidates"

# 契约版本
CONTRACT_VERSION = "mvp-1"


# =============================================================================
# Feature Flag
# =============================================================================

RECOMMENDATION_SERVICE_ENABLED = True


def is_recommendation_service_enabled() -> bool:
    """检查 RecommendationService 功能是否启用。"""
    return RECOMMENDATION_SERVICE_ENABLED


# =============================================================================
# RecommendationService
# =============================================================================


class RecommendationService:
    """端到端检索推荐服务。

    职责：
    1. 编排端到端检索推荐流程
    2. 使用 RecommendationRunContext 保证运行记录终态一致性
    3. 执行故障矩阵定义的降级策略
    4. 组装推荐响应

    设计约束：
    - 先 create_run 再执行 LLM normalizer
    - Requirement 1.7 失败时须 fail_run 且响应含 recommendation_run_id
    - reranker + aggregation 同时失败时按业务分优先降级
    - 不写回案例、LLM 派生结果、向量记录或反馈表
    """

    def __init__(
        self,
        repository: RecommendationRepository,
        normalizer: QueryNormalizer,
        vector_port: VectorSearchPort,
        case_provider: RecommendationCaseProvider,
        structured_scorer: StructuredSimilarityScorer,
        business_scorer: BusinessScoreCalculator,
        reranker: RerankerClient,
        aggregator: ScoreAggregator,
        explainer: RecommendationExplainer,
        config: RetrievalConfig,
    ) -> None:
        """初始化 RecommendationService。

        Args:
            repository: 推荐运行仓储。
            normalizer: 查询标准化器。
            vector_port: 向量搜索端口。
            case_provider: 候选快照读取器。
            structured_scorer: 结构化局部相似度评分器。
            business_scorer: 业务参数评分器。
            reranker: 远程 reranker 客户端。
            aggregator: 分值聚合器。
            explainer: 推荐解释生成器（RecommendationCopyService）。
            config: 推荐检索配置。
        """
        self._repo = repository
        self._normalizer = normalizer
        self._vector_port = vector_port
        self._case_provider = case_provider
        self._structured_scorer = structured_scorer
        self._business_scorer = business_scorer
        self._reranker = reranker
        self._aggregator = aggregator
        self._explainer = explainer
        self._config = config

    async def recommend_similar_cases(
        self,
        request: RetrievalRequest,
    ) -> RecommendationResponse:
        """执行相似案例推荐。

        流程：
        1. 创建运行记录（create_run）
        2. 查询标准化（LLM normalizer，可能失败 - Requirement 1.7）
        3. 向量搜索候选消费
        4. 候选快照读取
        5. 结构化局部评分（MVP skipped）
        6. 业务参数评分
        7. 语义精排（reranker）
        8. 分值聚合
        9. 相关性过滤（语义绝对/相对门槛或向量降级）
        10. 推荐解释
        11. 结果组装

        Args:
            request: 检索请求（已通过 schema 校验）。

        Returns:
            RecommendationResponse：推荐响应。

        Raises:
            不抛出异常，所有异常通过上下文管理器收口并返回错误响应。
        """
        start_time = time.monotonic()

        # 构建运行创建数据
        query_hash = self._compute_query_hash(request.query_text)
        run_create = self._build_run_create(request, query_hash)

        # 使用上下文管理器保证运行记录终态一致性
        context = RecommendationRunContext(self._repo, run_create)
        async with context as run_id:
            try:
                # 步骤 1: 查询标准化（可能失败 - Requirement 1.7）
                try:
                    normalized = await self._normalizer.normalize(request)
                except Exception as exc:
                    # LLM normalizer 失败：fail closed，不调用向量搜索
                    logger.warning(
                        "LLM normalizer 失败，触发 fail_run: error=%s",
                        str(exc),
                        extra={"run_id": run_id},
                    )
                    await self._fail_with_error(
                        context=context,
                        error_code="QUERY_SUMMARIZATION_FAILED",
                        message="当前无法理解您的问题，请稍后重试",
                        internal_reason=type(exc).__name__,
                    )
                    return self._build_fail_response(
                        run_id=run_id,
                        error_code="QUERY_SUMMARIZATION_FAILED",
                        message="当前无法理解您的问题，请稍后重试",
                    )

                # 步骤 2: 向量搜索
                try:
                    candidate_batch = await self._vector_port.search(normalized)
                except Exception as exc:
                    logger.warning(
                        "向量搜索失败，触发 fail_run: error=%s",
                        str(exc),
                        extra={"run_id": run_id},
                    )
                    await self._fail_with_error(
                        context=context,
                        error_code="VECTOR_SEARCH_FAILED",
                        message="检索服务暂时不可用，请稍后重试",
                        internal_reason=type(exc).__name__,
                    )
                    return self._build_fail_response(
                        run_id=run_id,
                        error_code="VECTOR_SEARCH_FAILED",
                        message="检索服务暂时不可用，请稍后重试",
                    )

                # 检查空候选
                if not candidate_batch.candidates:
                    # 空候选：正常终态，非失败
                    await self._complete_empty(
                        context=context,
                        run_create=run_create,
                        latency_ms=self._compute_latency_ms(start_time),
                    )
                    return self._build_empty_response(
                        run_id=run_id,
                        applied_filters=normalized.applied_filters,
                        effective_weights=normalized.effective_weights,
                        latency_ms=self._compute_latency_ms(start_time),
                        requested_top_k=normalized.top_k,
                    )

                # 步骤 3: 候选快照读取
                snapshots = await self._case_provider.load_candidates(
                    [c.model_dump() for c in candidate_batch.candidates]
                )

                # 步骤 4: 结构化局部评分（MVP skipped）
                structured_scores = self._structured_scorer.score(
                    query_structured_suggestions=normalized.query_structured_suggestions.model_dump(),
                    candidate_snapshots=[s.model_dump() for s in snapshots],
                )

                # 步骤 5: 业务参数评分
                business_scores = self._business_scorer.score(
                    effective_weights=normalized.effective_weights,
                    query_business_context={},  # 查询侧业务上下文（暂未使用）
                    candidate_snapshots=[s.model_dump() for s in snapshots],
                )

                # 步骤 6: 语义精排（reranker）
                reranker_status = RerankerStatus.PENDING
                semantic_scores: Optional[list[float]] = None
                try:
                    # 构建 reranker 输入
                    query_text = normalized.normalized_query_text
                    documents = [
                        self._build_reranker_document(s) for s in snapshots
                    ]
                    rerank_result = await self._reranker.rerank(
                        query=query_text,
                        documents=documents,
                        top_n=len(snapshots),
                    )
                    semantic_scores = rerank_result.scores
                    reranker_status = RerankerStatus.SUCCEEDED
                except Exception as exc:
                    logger.warning(
                        "Reranker 失败，触发降级: error=%s",
                        str(exc),
                        extra={"run_id": run_id},
                    )
                    reranker_status = RerankerStatus.FAILED

                # 步骤 7: 分值聚合
                aggregation_status = AggregationStatus.SKIPPED
                ranked: Optional[Sequence[AggregatedCandidate]] = None
                fallback_ranking_source: Optional[str] = None

                # 构建 ScoredCandidate 列表
                scored_candidates = self._build_scored_candidates(
                    snapshots=snapshots,
                    structured_scores=structured_scores,
                    business_scores=business_scores,
                    semantic_scores=semantic_scores,
                )

                try:
                    # effective_weights 为业务因子权重（business_type 等），
                    # 与 ScoreAggregator 的 vector/semantic/structured/business 无关；
                    # 传错会导致无法匹配分项、全部走「未聚合」占位 final_score=0。
                    agg_result = self._aggregator.aggregate(
                        candidates=scored_candidates,
                        weights=None,
                    )
                    ranked = agg_result.candidates
                    aggregation_status = AggregationStatus.SUCCEEDED
                except Exception as exc:
                    logger.warning(
                        "分值聚合失败，触发降级排序: error=%s",
                        str(exc),
                        extra={"run_id": run_id},
                    )
                    aggregation_status = AggregationStatus.FAILED

                    # 降级排序：reranker + aggregation 同时失败时按业务分优先
                    if reranker_status == RerankerStatus.FAILED:
                        # 业务分优先，业务分不可用时向量顺序
                        ranked, fallback_ranking_source = self._fallback_business_first(
                            scored_candidates, business_scores
                        )
                    elif semantic_scores is not None:
                        # 语义分优先
                        ranked, fallback_ranking_source = self._fallback_semantic_first(
                            scored_candidates, semantic_scores
                        )
                    else:
                        # 向量顺序
                        ranked, fallback_ranking_source = self._fallback_vector_order(
                            scored_candidates
                        )

                # 步骤 8: 相关性过滤（聚合排序后、Top-K 前）
                relevance_config = RelevanceFilterConfig(
                    semantic_absolute_floor=self._config.semantic_absolute_floor,
                    semantic_relative_ratio=self._config.semantic_relative_ratio,
                    semantic_low_confidence=self._config.semantic_low_confidence,
                    vector_fallback_floor=self._config.vector_fallback_floor,
                )
                filter_result = filter_relevant_candidates(
                    ranked or [],
                    reranker_ok=reranker_status == RerankerStatus.SUCCEEDED,
                    top_k=normalized.top_k,
                    config=relevance_config,
                )
                ranked = filter_result.candidates

                if not ranked:
                    await self._complete_relevance_filtered_empty(
                        context=context,
                        vector_candidate_count=len(candidate_batch.candidates),
                        reranker_status=reranker_status,
                        aggregation_status=aggregation_status,
                        latency_ms=self._compute_latency_ms(start_time),
                    )
                    return self._build_empty_response(
                        run_id=run_id,
                        applied_filters=normalized.applied_filters,
                        effective_weights=normalized.effective_weights,
                        latency_ms=self._compute_latency_ms(start_time),
                        requested_top_k=normalized.top_k,
                        degraded_reason=DEGRADED_REASON_NO_RELEVANT_CANDIDATES,
                    )

                # 步骤 9: 推荐解释
                explanation_result = await self._generate_explanation(
                    normalized,
                    ranked,  # type: ignore[arg-type]
                    snapshots,
                )

                # 步骤 10: 组装推荐项
                items = self._build_recommendation_items(
                    run_id,
                    ranked=ranked,  # type: ignore
                    snapshots=snapshots,
                    structured_scores=structured_scores,
                    business_scores=business_scores,
                    explanation_result=explanation_result,
                )

                # 步骤 11: 完成运行
                degraded_reason = self._determine_degraded_reason(
                    reranker_status=reranker_status,
                    aggregation_status=aggregation_status,
                    explanation_status=explanation_result.status,
                )
                is_degraded = degraded_reason is not None

                result = RunResult(
                    status=RunStatus.DEGRADED if is_degraded else RunStatus.SUCCEEDED,
                    returned_count=len(items),
                    vector_candidate_count=len(candidate_batch.candidates),
                    reranker_status=reranker_status,
                    aggregation_status=aggregation_status,
                    degraded_reason=degraded_reason,
                    latency_ms=self._compute_latency_ms(start_time),
                    items=items,
                )

                await self._complete_with_items(
                    context=context,
                    result=result,
                    run_create=run_create,
                )

                return self._build_success_response(
                    run_id=run_id,
                    normalized=normalized,
                    items=items,
                    reranker_status=reranker_status,
                    aggregation_status=aggregation_status,
                    degraded_reason=degraded_reason,
                    latency_ms=self._compute_latency_ms(start_time),
                    explanation_result=explanation_result,
                    snapshots=snapshots,
                )

            except Exception as exc:
                # 未预期的异常：上下文管理器会自动处理
                logger.error(
                    "推荐流程未预期异常: error=%s",
                    str(exc),
                    extra={"run_id": run_id},
                )
                raise

    async def get_run(self, run_id: str) -> Optional[RecommendationRunResponse]:
        """查询推荐运行记录。

        Args:
            run_id: 运行标识。

        Returns:
            推荐运行响应，不存在时返回 None。
        """
        run, items = await self._repo.get_run_with_items(run_id)
        if run is None:
            return None

        return RecommendationRunResponse(
            recommendation_run_id=run.recommendation_run_id,
            contract_version=run.contract_version,
            query_text_hash=run.query_text_hash,
            applied_filters=run.applied_filters,
            score_weights=run.score_weights,
            requested_top_k=run.requested_top_k,
            returned_count=run.returned_count,
            vector_candidate_count=run.vector_candidate_count,
            status=RunStatus(run.status),
            degraded_reason=run.degraded_reason,
            reranker_model_id=run.reranker_model_id,
            reranker_status=RerankerStatus(run.reranker_status),
            aggregation_status=AggregationStatus(run.aggregation_status),
            latency_ms=run.latency_ms,
            error_code=run.error_code,
            created_at=run.created_at,
            updated_at=run.updated_at,
            items=[
                self._build_item_response(item) for item in items
            ],
        )

    # ===================================================================
    # 内部方法
    # ===================================================================

    def _compute_query_hash(self, query_text: str) -> str:
        """计算查询文本哈希。"""
        return hashlib.sha256(query_text.encode()).hexdigest()[:32]

    def _build_run_create(
        self,
        request: RetrievalRequest,
        query_hash: str,
    ) -> RecommendationRunCreate:
        """构建运行创建数据。"""
        return RecommendationRunCreate(
            recommendation_run_id=str(uuid.uuid4()),
            query_text_hash=query_hash,
            applied_filters=request.filters.model_dump() if request.filters else {},
            score_weights=DEFAULT_SCORE_WEIGHTS,
            contract_version=CONTRACT_VERSION,
            requested_top_k=request.top_k,
            reranker_model_id=self._config.reranker_model_id,
        )

    async def _fail_with_error(
        self,
        context: RecommendationRunContext,
        error_code: str,
        message: str,
        internal_reason: str,
    ) -> None:
        """写入失败终态。"""
        error_data = RecommendationErrorData(
            error_code=error_code,
            internal_reason=internal_reason,
        )
        await context.fail(error_data)

    async def _complete_empty(
        self,
        context: RecommendationRunContext,
        run_create: RecommendationRunCreate,
        latency_ms: int,
    ) -> None:
        """完成空候选运行。"""
        result = RunResult(
            status=RunStatus.EMPTY,
            returned_count=0,
            vector_candidate_count=0,
            reranker_status=RerankerStatus.PENDING,
            aggregation_status=AggregationStatus.SKIPPED,
            degraded_reason=DEGRADED_REASON_NO_CANDIDATES,
            latency_ms=latency_ms,
            items=[],
        )
        await context.complete(result)

    async def _complete_relevance_filtered_empty(
        self,
        context: RecommendationRunContext,
        vector_candidate_count: int,
        reranker_status: RerankerStatus,
        aggregation_status: AggregationStatus,
        latency_ms: int,
    ) -> None:
        """完成「有向量候选但相关性过滤后为空」的运行。"""
        result = RunResult(
            status=RunStatus.EMPTY,
            returned_count=0,
            vector_candidate_count=vector_candidate_count,
            reranker_status=reranker_status,
            aggregation_status=aggregation_status,
            degraded_reason=DEGRADED_REASON_NO_RELEVANT_CANDIDATES,
            latency_ms=latency_ms,
            items=[],
        )
        await context.complete(result)

    async def _complete_with_items(
        self,
        context: RecommendationRunContext,
        result: RunResult,
        run_create: RecommendationRunCreate,
    ) -> None:
        """完成运行并写入推荐项快照。"""
        await context.complete(result)

    def _build_reranker_document(self, snapshot: CandidateSnapshot) -> str:
        """构建 reranker 输入文档。"""
        parts = []
        if snapshot.problem_summary:
            parts.append(f"问题摘要: {snapshot.problem_summary}")
        if snapshot.problem_description:
            parts.append(f"问题描述: {snapshot.problem_description}")
        if snapshot.core_solution_steps:
            parts.append(f"解决步骤: {snapshot.core_solution_steps}")
        return " | ".join(parts)

    def _build_scored_candidates(
        self,
        snapshots: list[CandidateSnapshot],
        structured_scores: list[StructuredSimilarityScore],
        business_scores: list[BusinessScore],
        semantic_scores: Optional[list[float]],
    ) -> list[ScoredCandidate]:
        """构建已评分候选列表。"""
        candidates = []
        for i, snapshot in enumerate(snapshots):
            structured_score = structured_scores[i] if i < len(structured_scores) else None
            business_score = business_scores[i] if i < len(business_scores) else None

            candidates.append(
                ScoredCandidate(
                    case_id=snapshot.case_id,
                    vector_score=snapshot.vector_similarity_score,
                    semantic_score=(
                        semantic_scores[i]
                        if semantic_scores and i < len(semantic_scores)
                        else None
                    ),
                    structured_score=structured_score.score if structured_score else None,
                    business_score=business_score.score if business_score else None,
                    case_updated_at=snapshot.case_updated_at,
                )
            )
        return candidates

    def _fallback_business_first(
        self,
        candidates: list[ScoredCandidate],
        business_scores: list[BusinessScore],
    ) -> tuple[Sequence[AggregatedCandidate], str]:
        """业务分优先降级排序。"""
        if not candidates:
            return [], "business_first"

        # 按业务分排序
        scored_with_business = [
            (c, business_scores[i].score if i < len(business_scores) else 0.0)
            for i, c in enumerate(candidates)
        ]
        scored_with_business.sort(key=lambda x: -x[1])

        # 构建 AggregatedCandidate
        result = []
        for i, (c, biz_score) in enumerate(scored_with_business):
            result.append(
                AggregatedCandidate(
                    case_id=c.case_id,
                    final_score=biz_score,
                    score_breakdown={
                        "vector_similarity_score": c.vector_score,
                        "semantic_similarity_score": c.semantic_score,
                        "structured_similarity_score": c.structured_score,
                        "business_score": c.business_score,
                        "final_score_source": ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                    },
                    normalized_scores={},
                    effective_weights={},
                    final_score_source=ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                    case_updated_at=c.case_updated_at,
                )
            )
        return result, "business_first"

    def _fallback_semantic_first(
        self,
        candidates: list[ScoredCandidate],
        semantic_scores: list[float],
    ) -> tuple[Sequence[AggregatedCandidate], str]:
        """语义分优先降级排序。"""
        if not candidates:
            return [], "semantic_first"

        # 按语义分排序
        scored_with_semantic = [
            (c, semantic_scores[i] if i < len(semantic_scores) else 0.0)
            for i, c in enumerate(candidates)
        ]
        scored_with_semantic.sort(key=lambda x: -x[1])

        # 构建 AggregatedCandidate
        result = []
        for c, sem_score in scored_with_semantic:
            result.append(
                AggregatedCandidate(
                    case_id=c.case_id,
                    final_score=sem_score,
                    score_breakdown={
                        "vector_similarity_score": c.vector_score,
                        "semantic_similarity_score": c.semantic_score,
                        "structured_similarity_score": c.structured_score,
                        "business_score": c.business_score,
                        "final_score_source": ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                    },
                    normalized_scores={},
                    effective_weights={},
                    final_score_source=ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                    case_updated_at=c.case_updated_at,
                )
            )
        return result, "semantic_first"

    def _fallback_vector_order(
        self,
        candidates: list[ScoredCandidate],
    ) -> tuple[Sequence[AggregatedCandidate], str]:
        """向量顺序降级排序。"""
        # 按向量分排序
        sorted_candidates = sorted(candidates, key=lambda c: -(c.vector_score or 0.0))

        result = []
        for c in sorted_candidates:
            result.append(
                AggregatedCandidate(
                    case_id=c.case_id,
                    final_score=c.vector_score or 0.0,
                    score_breakdown={
                        "vector_similarity_score": c.vector_score,
                        "semantic_similarity_score": c.semantic_score,
                        "structured_similarity_score": c.structured_score,
                        "business_score": c.business_score,
                        "final_score_source": ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                    },
                    normalized_scores={},
                    effective_weights={},
                    final_score_source=ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                    case_updated_at=c.case_updated_at,
                )
            )
        return result, "vector_order"

    async def _generate_explanation(
        self,
        query: NormalizedRetrievalQuery,
        ranked: Sequence[AggregatedCandidate],
        snapshots: list[CandidateSnapshot],
    ) -> ExplanationResult:
        """生成推荐解释（调用 RecommendationExplainer → RecommendationCopyService）。"""
        if not ranked:
            return ExplanationResult(items=[], status=ExplanationStatus.UNAVAILABLE)

        if not is_explainer_enabled():
            return ExplanationResult(
                items=[],
                status=ExplanationStatus.FALLBACK,
                metadata={"reason": "explainer_disabled"},
            )

        snapshot_map = {s.case_id: s for s in snapshots}
        ranked_snapshots: list[CandidateSnapshot] = []
        for c in ranked:
            snap = snapshot_map.get(c.case_id)
            if snap is not None:
                ranked_snapshots.append(snap)

        if not ranked_snapshots:
            return ExplanationResult(items=[], status=ExplanationStatus.UNAVAILABLE)

        return await self._explainer.explain(query, ranked_snapshots)

    def _determine_degraded_reason(
        self,
        reranker_status: RerankerStatus,
        aggregation_status: AggregationStatus,
        explanation_status: ExplanationStatus,
    ) -> Optional[str]:
        """确定降级原因。"""
        # reranker + aggregation 同时失败
        if (
            reranker_status == RerankerStatus.FAILED
            and aggregation_status == AggregationStatus.FAILED
        ):
            return DEGRADED_REASON_RERANKER_AND_AGGREGATION_FAILED

        # 仅 reranker 失败
        if reranker_status == RerankerStatus.FAILED:
            return DEGRADED_REASON_RERANKER_FAILED

        # 仅聚合失败
        if aggregation_status == AggregationStatus.FAILED:
            return DEGRADED_REASON_AGGREGATION_FAILED

        # 仅解释降级
        if explanation_status == ExplanationStatus.FALLBACK:
            return DEGRADED_REASON_EXPLANATION_FALLBACK

        return None

    def _build_recommendation_items(
        self,
        run_id: str,
        ranked: Sequence[AggregatedCandidate],
        snapshots: list[CandidateSnapshot],
        structured_scores: list[StructuredSimilarityScore],
        business_scores: list[BusinessScore],
        explanation_result: "ExplanationResult",
    ) -> list[RecommendationItemRecord]:
        """构建推荐项记录列表（写入 ``run_id``，与快照持久化及反馈解析一致）。"""
        # 构建 case_id -> snapshot 映射
        snapshot_map = {s.case_id: s for s in snapshots}

        # 构建 case_id -> explanation 映射
        explanation_map = {item.case_id: item for item in explanation_result.items}

        items = []
        for i, aggregated in enumerate(ranked):
            snapshot = snapshot_map.get(aggregated.case_id)
            if snapshot is None:
                continue

            explanation = explanation_map.get(aggregated.case_id)

            # 查找 business_score
            business_score = None
            for bs in business_scores:
                if bs.case_id == aggregated.case_id:
                    business_score = bs.score
                    break

            item = RecommendationItemRecord(
                recommendation_item_id=self._generate_item_id(),
                recommendation_run_id=run_id,
                case_id=aggregated.case_id,
                vector_id=snapshot.vector_id,
                rank=i + 1,
                vector_similarity_score=snapshot.vector_similarity_score,
                semantic_similarity_score=aggregated.score_breakdown.get(
                    "semantic_similarity_score"
                ),
                structured_similarity_score=aggregated.score_breakdown.get(
                    "structured_similarity_score"
                ),
                business_score=business_score,
                final_score=aggregated.final_score,
                score_breakdown=aggregated.score_breakdown,
                explanation_status=(
                    explanation.status
                    if explanation
                    else ExplanationStatus.UNAVAILABLE
                ),
                missing_fields=snapshot.missing_fields,
                case_updated_at=snapshot.case_updated_at,
                created_at=datetime.now(timezone.utc),
            )
            items.append(item)

        return items

    def _generate_item_id(self) -> str:
        """生成推荐项标识。"""
        return f"rec_item_{uuid.uuid4().hex[:24]}"

    def _build_fail_response(
        self,
        run_id: str,
        error_code: str,
        message: str,
    ) -> RecommendationResponse:
        """构建失败响应。"""
        return RecommendationResponse(
            recommendation_run_id=run_id,
            contract_version=CONTRACT_VERSION,
            status=RunStatus.FAILED,
            applied_filters={},
            score_weights=DEFAULT_SCORE_WEIGHTS,
            query_metadata={
                "requested_top_k": 0,
                "returned_count": 0,
                "latency_ms": 0,
            },
            items=[],
            error_code=error_code,
            message=message,
        )

    def _build_empty_response(
        self,
        run_id: str,
        applied_filters: dict[str, Any],
        effective_weights: dict[str, float],
        latency_ms: int,
        requested_top_k: int = 0,
        degraded_reason: str = DEGRADED_REASON_NO_CANDIDATES,
    ) -> RecommendationResponse:
        """构建空结果响应。"""
        return RecommendationResponse(
            recommendation_run_id=run_id,
            contract_version=CONTRACT_VERSION,
            status=RunStatus.EMPTY,
            applied_filters=applied_filters,
            score_weights=effective_weights,
            query_metadata={
                "requested_top_k": requested_top_k,
                "returned_count": 0,
                "latency_ms": latency_ms,
            },
            items=[],
            degraded_reason=degraded_reason,
        )

    @staticmethod
    def _case_reference_from_snapshot(snapshot: CandidateSnapshot) -> dict[str, Any]:
        """由候选快照组装 case_reference（含增强结果投影）。"""
        ref: dict[str, Any] = {"case_id": snapshot.case_id}
        if snapshot.problem_summary:
            ref["description_preview"] = snapshot.problem_summary
        elif snapshot.problem_description:
            ref["description_preview"] = snapshot.problem_description
        ref["case_updated_at"] = snapshot.case_updated_at.isoformat()
        enrichment_block: dict[str, Any] = {}
        if snapshot.problem_summary:
            enrichment_block["problem_summary"] = snapshot.problem_summary
        if snapshot.enrichment_solution_summary:
            enrichment_block["solution_summary"] = snapshot.enrichment_solution_summary
        if enrichment_block:
            ref["case_enrichment_results"] = enrichment_block
        return ref

    def _build_success_response(
        self,
        run_id: str,
        normalized: NormalizedRetrievalQuery,
        items: list[RecommendationItemRecord],
        reranker_status: RerankerStatus,
        aggregation_status: AggregationStatus,
        degraded_reason: Optional[str],
        latency_ms: int,
        explanation_result: "ExplanationResult",
        snapshots: list[CandidateSnapshot],
    ) -> RecommendationResponse:
        """构建成功响应。"""
        snapshot_map = {s.case_id: s for s in snapshots}
        # 构建推荐项响应
        item_responses = []
        for item in items:
            snapshot = snapshot_map.get(item.case_id)
            if snapshot is not None:
                case_ref = self._case_reference_from_snapshot(snapshot)
                core_solution_steps = snapshot.core_solution_steps
                outcome_summary = snapshot.outcome_summary
                structured_suggestions_summary = snapshot.structured_suggestions
            else:
                case_ref = {"case_id": item.case_id}
                core_solution_steps = None
                outcome_summary = None
                structured_suggestions_summary = None

            # 构建 score_metadata
            score_breakdown = item.score_breakdown or {}
            score_metadata = ScoreBreakdownResponse(
                vector_similarity_score=item.vector_similarity_score,
                semantic_similarity_score=item.semantic_similarity_score,
                structured_similarity_score=item.structured_similarity_score,
                business_score=item.business_score,
                final_score=item.final_score,
                final_score_source=ScoreBreakdownSource(
                    score_breakdown.get(
                        "final_score_source",
                        ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                    )
                ),
                normalized_scores={},
                effective_weights={},
            )

            # 获取解释
            explanation_map = {e.case_id: e for e in explanation_result.items}
            explanation = explanation_map.get(item.case_id)

            item_response = RecommendationItemResponse(
                recommendation_item_id=item.recommendation_item_id,
                case_id=item.case_id,
                rank=item.rank,
                case_reference=case_ref,
                core_solution_steps=core_solution_steps,
                outcome_summary=outcome_summary,
                structured_suggestions_summary=structured_suggestions_summary,
                missing_fields=item.missing_fields,
                vector_similarity_score=item.vector_similarity_score,
                semantic_similarity_score=item.semantic_similarity_score,
                structured_similarity_score=item.structured_similarity_score,
                business_score=item.business_score,
                final_score=item.final_score,
                score_metadata=score_metadata,
                recommendation_reason=explanation.recommendation_reason if explanation else None,
                reference_points=explanation.reference_points if explanation else None,
                cautions=explanation.cautions if explanation else None,
                source_references=explanation.source_references if explanation else None,
                explanation_status=item.explanation_status,
            )
            item_responses.append(item_response)

        return RecommendationResponse(
            recommendation_run_id=run_id,
            contract_version=CONTRACT_VERSION,
            status=RunStatus.DEGRADED if degraded_reason else RunStatus.SUCCEEDED,
            applied_filters=normalized.applied_filters,
            score_weights=normalized.effective_weights,
            query_metadata={
                "requested_top_k": normalized.top_k,
                "returned_count": len(items),
                "latency_ms": latency_ms,
            },
            items=item_responses,
            degraded_reason=degraded_reason,
        )

    def _build_item_response(
        self,
        item: RecommendationItemRecord,
    ) -> RecommendationItemResponse:
        """构建单个推荐项响应。"""
        score_breakdown = item.score_breakdown or {}
        score_metadata = ScoreBreakdownResponse(
            vector_similarity_score=item.vector_similarity_score,
            semantic_similarity_score=item.semantic_similarity_score,
            structured_similarity_score=item.structured_similarity_score,
            business_score=item.business_score,
            final_score=item.final_score,
            final_score_source=ScoreBreakdownSource(
                score_breakdown.get(
                    "final_score_source",
                    ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
                )
            ),
            normalized_scores={},
            effective_weights={},
        )

        return RecommendationItemResponse(
            recommendation_item_id=item.recommendation_item_id,
            case_id=item.case_id,
            rank=item.rank,
            case_reference={"case_id": item.case_id},
            core_solution_steps=None,
            outcome_summary=None,
            structured_suggestions_summary=None,
            missing_fields=item.missing_fields,
            vector_similarity_score=item.vector_similarity_score,
            semantic_similarity_score=item.semantic_similarity_score,
            structured_similarity_score=item.structured_similarity_score,
            business_score=item.business_score,
            final_score=item.final_score,
            score_metadata=score_metadata,
            recommendation_reason=None,
            reference_points=None,
            cautions=None,
            source_references=None,
            explanation_status=item.explanation_status,
        )

    @staticmethod
    def _compute_latency_ms(start_time: float) -> int:
        """计算耗时（毫秒）。"""
        return int((time.monotonic() - start_time) * 1000)

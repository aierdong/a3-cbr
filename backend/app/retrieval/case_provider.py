"""RecommendationCaseProvider：读取上游案例详情和 CaseEnrichmentResult，补齐推荐候选快照。

根据向量候选读取上游案例详情和当前可消费的 CaseEnrichmentResult，
补齐问题摘要、结构化建议、过滤字段摘要、核心解决步骤、效果结果和更新时间。

对齐依赖契约快照：保证 not_found 与 forbidden 可区分，单候选失败仅标记缺失而非整批失败。
对缺失摘要、结构化建议、解决步骤或效果信息的候选标记 missing_fields，不直接移除候选。

Boundary: RecommendationCaseProvider_
"""

from __future__ import annotations

import logging
from typing import Any

from app.cases.schemas import CaseDetailResponse
from app.cases.service import CaseNotFoundError, CaseService
from app.enrichment.repository import EnrichmentRepository
from app.retrieval.schemas import CandidateSnapshot


logger = logging.getLogger(__name__)


# =============================================================================
# 依赖契约快照：a3-case-management
# =============================================================================
# Required input: case_id 列表（来自向量候选）。
# Required output fields:
#   - case_id（string）
#   - status（可用于过滤与可用性判断）
#   - problem_summary 或 problem_description（至少一个可用）
#   - core_solution_steps（可为空，但需显式缺失）
#   - outcome_summary 或等价结果字段（可为空，但需显式缺失）
#   - brand_id、store_id、problem_type、tags、created_at、updated_at（过滤与业务评分依赖）
# Tolerant fields: 标题、扩展业务字段、展示附加信息。
# Error contract: not_found 与 forbidden 必须可区分；单候选失败不得导致整批崩溃。
# =============================================================================


# =============================================================================
# Feature Flag: 全局启用开关
# =============================================================================

RECOMMENDATION_CASE_PROVIDER_ENABLED = True


def is_case_provider_enabled() -> bool:
    """检查 RecommendationCaseProvider 功能是否启用。"""
    return RECOMMENDATION_CASE_PROVIDER_ENABLED


# =============================================================================
# 专用异常
# =============================================================================


class CaseFetchError(Exception):
    """案例读取基础异常。"""

    pass


class CaseForbiddenError(CaseFetchError):
    """案例访问被拒绝（forbidden）。"""

    def __init__(self, case_id: str) -> None:
        """初始化 CaseForbiddenError。

        Args:
            case_id: 案例标识。
        """
        self.case_id = case_id
        super().__init__(f"案例访问被拒绝: case_id='{case_id}'")


# =============================================================================
# RecommendationCaseProvider
# =============================================================================


class RecommendationCaseProvider:
    """推荐候选案例快照读取器。

    职责：
    1. 根据向量候选的 case_id 列表读取上游案例详情
    2. 读取当前可消费的 CaseEnrichmentResult
    3. 补齐问题摘要、结构化建议、过滤字段摘要、核心解决步骤、效果结果和更新时间
    4. 对齐依赖契约快照：not_found 与 forbidden 可区分
    5. 单候选失败仅标记缺失字段而非整批失败
    6. 对缺失摘要、结构化建议、解决步骤或效果信息的候选标记 missing_fields

    使用 a3-case-management 的 CaseService 和 llm-case-enrichment 的 EnrichmentRepository。
    """

    def __init__(
        self,
        case_service: CaseService,
        enrichment_repository: EnrichmentRepository,
    ) -> None:
        """初始化 RecommendationCaseProvider。

        Args:
            case_service: a3-case-management 提供的案例服务。
            enrichment_repository: llm-case-enrichment 提供的增强结果仓储。
        """
        self._case_service = case_service
        self._enrichment_repo = enrichment_repository

    async def load_candidates(
        self,
        vector_candidates: list[dict[str, Any]],
    ) -> list[CandidateSnapshot]:
        """加载候选案例快照列表。

        遍历向量候选列表，依次读取案例详情和增强结果，
        补齐候选快照字段。单个候选失败仅标记缺失字段，
        不导致整批失败。

        Args:
            vector_candidates: 向量候选列表，每项包含 case_id、vector_id、
                              similarity_score 等字段。

        Returns:
            候选快照列表，按输入顺序排列。每个快照包含案例详情、
            增强字段、向量候选原语和缺失字段标记。
        """
        if not vector_candidates:
            return []

        snapshots: list[CandidateSnapshot] = []

        for raw_candidate in vector_candidates:
            try:
                snapshot = await self._load_single_candidate(raw_candidate)
                snapshots.append(snapshot)
            except CaseForbiddenError:
                # foridden 异常上抛，不标记缺失
                raise
            except Exception as exc:
                # 其他异常（not_found 等）标记缺失字段，继续处理
                logger.warning(
                    f"加载候选快照失败，标记缺失: case_id={raw_candidate.get('case_id')}, "
                    f"error={exc}"
                )
                snapshot = self._build_missing_snapshot(raw_candidate, exc)
                snapshots.append(snapshot)

        return snapshots

    async def _load_single_candidate(
        self,
        raw_candidate: dict[str, Any],
    ) -> CandidateSnapshot:
        """加载单个候选案例快照。

        Args:
            raw_candidate: 向量候选原始数据。

        Returns:
            候选快照。

        Raises:
            CaseForbiddenError: 案例访问被拒绝。
            CaseNotFoundError: 案例不存在。
        """
        case_id = raw_candidate["case_id"]

        # 1. 读取案例详情
        try:
            case_detail: CaseDetailResponse = await self._case_service.get_case(case_id)
        except CaseNotFoundError:
            raise
        except PermissionError as exc:
            raise CaseForbiddenError(case_id) from exc
        except Exception as exc:
            # 映射其他异常
            await self._map_case_error(case_id, exc)

        # 2. 读取当前有效的 CaseEnrichmentResult
        enrichment_result = await self._enrichment_repo.get_current_result(case_id)

        # 3. 组装候选快照
        return self._build_snapshot(raw_candidate, case_detail, enrichment_result)

    def _build_snapshot(
        self,
        raw_candidate: dict[str, Any],
        case_detail: CaseDetailResponse,
        enrichment_result: Any,
    ) -> CandidateSnapshot:
        """构建候选快照。

        Args:
            raw_candidate: 向量候选原始数据。
            case_detail: 案例详情。
            enrichment_result: 当前有效的增强结果（可能为 None）。

        Returns:
            候选快照。
        """
        # 初始化 missing_fields
        missing_fields: list[str] = []

        # 向量候选原语
        case_id = raw_candidate.get("case_id", "")
        vector_id = raw_candidate.get("vector_id", "")
        similarity_score = raw_candidate.get("similarity_score", 0.0)
        case_updated_at = raw_candidate.get(
            "case_updated_at", case_detail.updated_at
        )

        # 案例基础字段
        brand_id = case_detail.store.brand_id if case_detail.store else None
        store_id = case_detail.store_id
        problem_type = (
            case_detail.problem_type.value
            if hasattr(case_detail.problem_type, "value")
            else case_detail.problem_type
        )
        case_status = (
            case_detail.status.value
            if hasattr(case_detail.status, "value")
            else case_detail.status
        )

        # 问题摘要：优先使用 enrichment.problem_summary，否则使用 problem_description
        if enrichment_result and enrichment_result.problem_summary:
            problem_summary = enrichment_result.problem_summary
        else:
            problem_summary = None
            if not case_detail.problem_description:
                missing_fields.append("problem_summary")

        problem_description = case_detail.problem_description or None

        # 结构化建议：来自 enrichment
        if enrichment_result and enrichment_result.structured_suggestions:
            structured_suggestions = enrichment_result.structured_suggestions
        else:
            structured_suggestions = None
            missing_fields.append("structured_suggestions")

        enrichment_solution_summary: str | None = None
        if enrichment_result and enrichment_result.solution_summary:
            enrichment_solution_summary = enrichment_result.solution_summary

        # 核心解决步骤：优先增强 solution_summary，其次案例 solution_steps
        if enrichment_solution_summary:
            core_solution_steps = enrichment_solution_summary
        elif case_detail.solution_steps:
            core_solution_steps = self._serialize_solution_steps(
                case_detail.solution_steps
            )
        else:
            core_solution_steps = None
            missing_fields.append("core_solution_steps")

        # 效果结果：优先使用 enrichment.solution_summary，其次使用案例 outcome
        if enrichment_result and enrichment_result.solution_summary:
            outcome_summary = enrichment_result.solution_summary
        elif case_detail.outcome:
            outcome_summary = self._serialize_outcome(case_detail.outcome)
        else:
            outcome_summary = None
            missing_fields.append("outcome_summary")

        # 标签：来自 enrichment 或案例
        tags: list[str] | None = None
        if enrichment_result and enrichment_result.tag_suggestions:
            tags = enrichment_result.tag_suggestions

        return CandidateSnapshot(
            case_id=case_id,
            vector_id=vector_id,
            vector_similarity_score=float(similarity_score),
            problem_summary=problem_summary,
            problem_description=problem_description,
            enrichment_solution_summary=enrichment_solution_summary,
            core_solution_steps=core_solution_steps,
            outcome_summary=outcome_summary,
            structured_suggestions=structured_suggestions,
            brand_id=brand_id,
            store_id=store_id,
            problem_type=problem_type,
            tags=tags,
            case_status=case_status,
            case_updated_at=case_updated_at,
            missing_fields=missing_fields,
        )

    def _build_missing_snapshot(
        self,
        raw_candidate: dict[str, Any],
        error: Exception,
    ) -> CandidateSnapshot:
        """构建缺失字段的候选快照。

        当单个候选读取失败时，构造一个包含缺失字段标记的空快照。

        Args:
            raw_candidate: 向量候选原始数据。
            error: 导致失败的异常。

        Returns:
            标记缺失字段的候选快照。
        """
        case_id = raw_candidate.get("case_id", "")

        # 根据错误类型确定缺失字段
        missing_fields = ["problem_summary", "structured_suggestions"]

        if isinstance(error, CaseNotFoundError):
            missing_fields.extend(
                [
                    "problem_description",
                    "core_solution_steps",
                    "outcome_summary",
                ]
            )

        return CandidateSnapshot(
            case_id=case_id,
            vector_id=raw_candidate.get("vector_id", ""),
            vector_similarity_score=float(raw_candidate.get("similarity_score", 0.0)),
            problem_summary=None,
            problem_description=None,
            core_solution_steps=None,
            outcome_summary=None,
            structured_suggestions=None,
            brand_id=None,
            store_id=None,
            problem_type=None,
            tags=None,
            case_status=None,
            case_updated_at=raw_candidate.get("case_updated_at"),
            missing_fields=list(set(missing_fields)),
        )

    def _serialize_solution_steps(
        self,
        solution_steps: list[Any],
    ) -> str:
        """序列化解决步骤为字符串。

        Args:
            solution_steps: 解决步骤列表。

        Returns:
            序列化后的字符串。
        """
        if not solution_steps:
            return ""

        parts = []
        for step in solution_steps:
            if hasattr(step, "model_dump"):
                step_dict = step.model_dump()
            elif isinstance(step, dict):
                step_dict = step
            else:
                step_dict = {"order": 0, "content": str(step)}

            order = step_dict.get("order", 0)
            content = step_dict.get("content", "")
            if content:
                parts.append(f"{order}. {content}")

        return "\n".join(parts)

    def _serialize_outcome(self, outcome: Any) -> str:
        """序列化效果结果为字符串。

        Args:
            outcome: 效果结果对象。

        Returns:
            序列化后的字符串。
        """
        if not outcome:
            return ""

        if hasattr(outcome, "model_dump"):
            outcome_dict = outcome.model_dump()
        elif isinstance(outcome, dict):
            outcome_dict = outcome
        else:
            return str(outcome)

        result = outcome_dict.get("result", "")
        notes = outcome_dict.get("notes", "")

        if notes:
            return f"{result}: {notes}"
        return result

    async def _map_case_error(self, case_id: str, error: Exception) -> None:
        """映射案例服务异常。

        Args:
            case_id: 案例标识。
            error: 案例服务抛出的异常。

        Raises:
            CaseForbiddenError: 当权限错误时。
            CaseNotFoundError: 当案例不存在时。
        """
        if isinstance(error, PermissionError) or (
            "forbidden" in str(error).lower() or "denied" in str(error).lower()
        ):
            raise CaseForbiddenError(case_id)
        elif isinstance(error, CaseNotFoundError):
            raise
        else:
            # 其他错误（如连接失败）也上抛
            raise


# =============================================================================
# 异步上下文管理器（可选）
# =============================================================================


class RecommendationCaseProviderPool:
    """候选读取器池，用于批量处理候选读取。

    提供批量读取能力和错误聚合。
    """

    def __init__(self, provider: RecommendationCaseProvider) -> None:
        """初始化池。

        Args:
            provider: 实际的 RecommendationCaseProvider 实例。
        """
        self._provider = provider

    async def load_candidates(
        self,
        vector_candidates: list[dict[str, Any]],
    ) -> tuple[list[CandidateSnapshot], list[CaseForbiddenError]]:
        """加载候选案例快照，区分成功和 forbidden 失败。

        Args:
            vector_candidates: 向量候选列表。

        Returns:
            (成功快照列表, forbidden 错误列表)
        """
        snapshots: list[CandidateSnapshot] = []
        forbidden_errors: list[CaseForbiddenError] = []

        for raw_candidate in vector_candidates:
            case_id = raw_candidate.get("case_id", "")
            try:
                snapshot = await self._provider._load_single_candidate(raw_candidate)
                snapshots.append(snapshot)
            except CaseForbiddenError as exc:
                forbidden_errors.append(exc)
            except Exception as exc:
                logger.warning(
                    f"加载候选快照失败，标记缺失: case_id={case_id}, error={exc}"
                )
                snapshot = self._provider._build_missing_snapshot(
                    raw_candidate, exc
                )
                snapshots.append(snapshot)

        return snapshots, forbidden_errors
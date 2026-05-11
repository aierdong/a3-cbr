"""ScoreAggregator：多源分值归一化、重加权与加权聚合。

对候选集执行 min-max 归一化、缺失分项重加权（`w'_k = w_k / sum(w_j, j in A)`）
和加权求和，将向量相似度、语义分、结构化局部相似度、业务参数分聚合为最终排序分值。

设计约束：
- 只处理向量搜索已返回候选集，不从全量 SQL casebase 重新检索
- 聚合器内部对象不进入数据库和 API 响应（返回适配类型）
- `final_score=0` 有两种语义（见 `ScoreBreakdownSource`）

Boundary: ScoreAggregator_
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.retrieval.schemas import ScoreBreakdownSource


logger = logging.getLogger(__name__)


# =============================================================================
# Feature Flag: 全局启用开关（行为任务需 TDD + Feature Flag）
# =============================================================================


RETRIEVAL_SCORE_AGGREGATOR_ENABLED = True


def is_score_aggregator_enabled() -> bool:
    """检查 ScoreAggregator 功能是否启用。"""
    return RETRIEVAL_SCORE_AGGREGATOR_ENABLED


# =============================================================================
# 内部数据模型
# =============================================================================


@dataclass
class ScoredCandidate:
    """已评分的候选案例（内部模型）。

    来自向量搜索候选 + reranker 语义分 + 结构化局部相似度 + 业务参数分。
    """

    case_id: str
    vector_score: Optional[float] = None
    semantic_score: Optional[float] = None
    structured_score: Optional[float] = None
    business_score: Optional[float] = None
    case_updated_at: Optional[datetime] = None


@dataclass
class AggregatedCandidate:
    """聚合后的候选案例（内部模型）。"""

    case_id: str
    final_score: float
    score_breakdown: dict
    normalized_scores: dict
    effective_weights: dict
    final_score_source: str
    case_updated_at: Optional[datetime] = None


@dataclass
class AggregateRankingResult:
    """聚合排序结果。"""

    candidates: list[AggregatedCandidate] = field(default_factory=list)


# =============================================================================
# ScoreAggregator
# =============================================================================


class ScoreAggregator:
    """分值聚合器。

    职责：
    1. 分值归一化（min-max normalization）
    2. 缺失分项重加权
    3. 加权求和聚合
    4. 并列打破（语义分 > 业务分 > 向量分 > 更新时间 > case_id）

    设计约束：
    - 只处理传入候选集，不从全量 SQL casebase 重新检索
    - 不读取反馈数据
    - 内部对象不泄漏到数据库或 API 响应
    """

    # 分项 Key 常量
    KEY_VECTOR = "vector"
    KEY_SEMANTIC = "semantic"
    KEY_STRUCTURED = "structured"
    KEY_BUSINESS = "business"

    # 所有可聚合分项 Key 有序列表（用于 min-max 计算）
    SCORE_KEYS = [KEY_VECTOR, KEY_SEMANTIC, KEY_STRUCTURED, KEY_BUSINESS]

    def __init__(self, default_weights: dict[str, float]):
        """初始化聚合器。

        Args:
            default_weights: 默认权重，格式 {
                'vector': 0.3,
                'semantic': 0.4,
                'structured': 0.1,
                'business': 0.2
            }
        """
        self.default_weights = default_weights

    def aggregate(
        self,
        candidates: list[ScoredCandidate],
        weights: Optional[dict[str, float]] = None,
    ) -> AggregateRankingResult:
        """聚合候选案例分值。

        Args:
            candidates: 已评分的候选列表
            weights: 可选的自定义权重，覆盖默认权重

        Returns:
            聚合并排序后的候选列表（ AggregateRankingResult）
        """
        if not candidates:
            return AggregateRankingResult(candidates=[])

        # 使用自定义权重或默认权重
        weights = weights or self.default_weights

        # 1. 计算 min-max 归一化
        normalized_scores_list = self._normalize_scores(candidates)

        # 2. 对每个候选计算有效权重并加权求和
        aggregated_items: list[AggregatedCandidate] = []
        for candidate, norm_scores in zip(candidates, normalized_scores_list):
            effective_weights = self._compute_effective_weights(norm_scores, weights)

            # 检查是否有有效分项
            available_keys = [k for k in self.SCORE_KEYS if k in effective_weights]

            if not available_keys:
                # 所有可聚合分项均缺失 -> aggregation_unavailable
                aggregated_items.append(
                    self._make_aggregation_unavailable_item(candidate)
                )
            else:
                # 正常聚合
                final_score = sum(
                    effective_weights[k] * norm_scores[k]
                    for k in available_keys
                )
                aggregated_items.append(
                    self._build_aggregated_item(
                        candidate=candidate,
                        final_score=final_score,
                        norm_scores=norm_scores,
                        effective_weights=effective_weights,
                        final_score_source=ScoreBreakdownSource.AGGREGATED,
                    )
                )

        # 3. 排序（含并列打破）
        sorted_items = self._sort_with_tiebreak(aggregated_items, candidates)

        return AggregateRankingResult(candidates=sorted_items)

    def _normalize_scores(
        self, candidates: list[ScoredCandidate]
    ) -> list[dict[str, float]]:
        """Min-max 归一化（候选集内统计，不跨请求）。

        算法：
        - norm_i = (x_i - min_x) / (max_x - min_x)，当 max_x > min_x
        - 若 max_x == min_x：
          - 若所有候选该分项均为 0：统一置为 0.0
          - 若所有候选该分项均为相同非零值：统一置为 1.0
        - 最后 clip(0, 1)
        """
        result: list[dict[str, float]] = []

        for key in self.SCORE_KEYS:
            # 提取所有候选的该分项原始值（跳过 None）
            raw_scores = []
            for c in candidates:
                score = self._get_candidate_score(c, key)
                if score is not None:
                    raw_scores.append(score)

            if not raw_scores:
                # 所有候选该分项均缺失
                for _ in candidates:
                    result.append({})
                continue

            min_val = min(raw_scores)
            max_val = max(raw_scores)

            for c in candidates:
                # 延迟初始化每个候选的归一化字典
                while len(result) < len(candidates):
                    result.append({})

                score = self._get_candidate_score(c, key)
                if score is None:
                    # 缺失分项不填充，在重加权时处理
                    continue

                if max_val > min_val:
                    norm = (score - min_val) / (max_val - min_val)
                else:
                    # max_val == min_val
                    if score == 0.0:
                        norm = 0.0
                    else:
                        # 所有候选该分项均为相同非零值
                        norm = 1.0

                # clip(0, 1)
                norm = max(0.0, min(1.0, norm))
                result[self._candidate_index(c, candidates)][key] = norm

        return result

    def _get_candidate_score(self, candidate: ScoredCandidate, key: str) -> Optional[float]:
        """根据 key 获取候选分值。"""
        if key == self.KEY_VECTOR:
            return candidate.vector_score
        elif key == self.KEY_SEMANTIC:
            return candidate.semantic_score
        elif key == self.KEY_STRUCTURED:
            return candidate.structured_score
        elif key == self.KEY_BUSINESS:
            return candidate.business_score
        return None

    def _candidate_index(
        self,
        candidate: ScoredCandidate,
        candidates: list[ScoredCandidate],
    ) -> int:
        """获取候选在列表中的索引。"""
        for i, c in enumerate(candidates):
            if c.case_id == candidate.case_id:
                return i
        return -1

    def _compute_effective_weights(
        self, norm_scores: dict[str, float], weights: dict[str, float]
    ) -> dict[str, float]:
        """计算有效权重（缺失分项重加权）。

        w'_k = w_k / sum(w_j, j in A)，其中 A 为有效分项集合
        """
        available_weights = {
            k: weights[k] for k in norm_scores.keys() if k in weights
        }

        if not available_weights:
            return {}

        total_weight = sum(available_weights.values())
        return {k: v / total_weight for k, v in available_weights.items()}

    def _make_aggregation_unavailable_item(
        self, candidate: ScoredCandidate
    ) -> AggregatedCandidate:
        """构建 aggregation_unavailable 的占位符项。"""
        return AggregatedCandidate(
            case_id=candidate.case_id,
            final_score=0.0,
            score_breakdown={
                "vector_similarity_score": candidate.vector_score,
                "semantic_similarity_score": candidate.semantic_score,
                "structured_similarity_score": candidate.structured_score,
                "business_score": candidate.business_score,
                "final_score_source": ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
            },
            normalized_scores={},
            effective_weights={},
            final_score_source=ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED,
            case_updated_at=candidate.case_updated_at,
        )

    def _build_aggregated_item(
        self,
        candidate: ScoredCandidate,
        final_score: float,
        norm_scores: dict[str, float],
        effective_weights: dict[str, float],
        final_score_source: str,
    ) -> AggregatedCandidate:
        """构建正常聚合项。"""
        return AggregatedCandidate(
            case_id=candidate.case_id,
            final_score=final_score,
            score_breakdown={
                "vector_similarity_score": candidate.vector_score,
                "semantic_similarity_score": candidate.semantic_score,
                "structured_similarity_score": candidate.structured_score,
                "business_score": candidate.business_score,
                "final_score_source": final_score_source,
            },
            normalized_scores=norm_scores,
            effective_weights=effective_weights,
            final_score_source=final_score_source,
            case_updated_at=candidate.case_updated_at,
        )

    def _sort_with_tiebreak(
        self,
        aggregated: list[AggregatedCandidate],
        original_candidates: list[ScoredCandidate],
    ) -> list[AggregatedCandidate]:
        """排序并打破并列。

        并列打破顺序（design.md Score Normalization & Aggregation Policy）：
        1. final_score 高优先
        2. semantic_similarity_score_norm 高优先
        3. business_score_norm 高优先
        4. vector_similarity_score_norm 高优先
        5. case_updated_at 新优先；若缺失则使用 created_at 替代
        6. case_id 字典序
        """
        # 构建 case_id -> original index 映射（用于稳定排序）
        original_index_map = {
            c.case_id: i for i, c in enumerate(original_candidates)
        }

        def sort_key(item: AggregatedCandidate) -> tuple:
            # 主排序：final_score（高优先，所以取负值）
            score = -item.final_score

            # 并列打破分项
            semantic = -item.normalized_scores.get(self.KEY_SEMANTIC, 0.0)
            business = -item.normalized_scores.get(self.KEY_BUSINESS, 0.0)
            vector = -item.normalized_scores.get(self.KEY_VECTOR, 0.0)

            # 更新时间（新优先，所以取负值）
            updated_at = item.case_updated_at
            if updated_at is None:
                updated_at = datetime(1970, 1, 1)  # 缺失时用极旧时间

            # case_id 字典序
            case_id = item.case_id

            # 原始列表顺序（稳定性保证）
            orig_idx = original_index_map.get(item.case_id, 0)

            return (score, semantic, business, vector, -updated_at.timestamp(), case_id, orig_idx)

        return sorted(aggregated, key=sort_key)


# =============================================================================
# 公开函数（Feature Flag gate 供外部调用）
# =============================================================================


def aggregate_scores(
    candidates: list[ScoredCandidate],
    weights: Optional[dict[str, float]] = None,
) -> AggregateRankingResult:
    """聚合候选分值（带 Feature Flag gate）。

    当 RETRIEVAL_SCORE_AGGREGATOR_ENABLED 为 False 时返回空结果。
    """
    if not is_score_aggregator_enabled():
        return AggregateRankingResult(candidates=[])

    default_weights = {
        "vector": 0.3,
        "semantic": 0.4,
        "structured": 0.1,
        "business": 0.2,
    }
    aggregator = ScoreAggregator(default_weights=default_weights)
    return aggregator.aggregate(candidates, weights=weights)

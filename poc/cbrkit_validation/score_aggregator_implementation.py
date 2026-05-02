"""
ScoreAggregator 完整实现示例

本文件提供生产就绪的 ScoreAggregator 实现，包含：
1. 分值归一化（min-max normalization）
2. 缺失分项重加权
3. 加权求和聚合
4. 并列打破
5. 完整的类型注解和文档字符串
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ScoreDimension(str, Enum):
    """分值维度枚举"""
    VECTOR = "vector"
    SEMANTIC = "semantic"
    STRUCTURED = "structured"
    BUSINESS = "business"


@dataclass
class ScoredCandidate:
    """已评分的候选案例"""
    case_id: str
    vector_score: float
    semantic_score: Optional[float] = None
    structured_score: Optional[float] = None
    business_score: Optional[float] = None
    case_updated_at: Optional[str] = None  # ISO 8601 格式


@dataclass
class AggregatedCandidate:
    """聚合后的候选案例"""
    case_id: str
    final_score: float
    score_breakdown: Dict[str, float]  # 原始分值
    normalized_scores: Dict[str, float]  # 归一化分值
    effective_weights: Dict[str, float]  # 有效权重
    final_score_source: str  # "aggregated" 或 "default_zero_not_aggregated"


class ScoreAggregator:
    """
    分值聚合器

    职责：
    1. 对候选集的各维度分值做 min-max 归一化
    2. 处理缺失分项（有效分项重加权）
    3. 加权求和聚合
    4. 并列打破（语义分 > 业务分 > 向量分 > 更新时间 > case_id）

    设计决策：
    - 自实现而非使用 CBRKit aggregator，因为：
      1. CBRKit 的缺失处理是 default_pooling_weight，不是重加权
      2. CBRKit 不负责归一化
      3. 加权求和逻辑简单，自实现完全可控
    """

    def __init__(self, default_weights: Dict[str, float]):
        """
        Args:
            default_weights: 默认权重，如 {
                'vector': 0.3,
                'semantic': 0.4,
                'structured': 0.1,
                'business': 0.2
            }
        """
        self.default_weights = default_weights
        self._validate_weights(default_weights)

    def _validate_weights(self, weights: Dict[str, float]) -> None:
        """验证权重配置"""
        total = sum(weights.values())
        if not (0.99 <= total <= 1.01):  # 允许浮点误差
            raise ValueError(f"权重和必须为 1.0，当前为 {total}")

        for key, value in weights.items():
            if not (0 <= value <= 1):
                raise ValueError(f"权重 {key} 必须在 [0, 1] 范围内，当前为 {value}")

    def aggregate(
        self,
        candidates: List[ScoredCandidate],
        weights: Optional[Dict[str, float]] = None
    ) -> List[AggregatedCandidate]:
        """
        聚合候选案例分值

        Args:
            candidates: 已评分的候选列表
            weights: 可选的自定义权重，覆盖默认权重

        Returns:
            聚合并排序后的候选列表（按 final_score 降序）

        Raises:
            ValueError: 权重配置无效
        """
        if not candidates:
            return []

        # 使用自定义权重或默认权重
        effective_weights = weights or self.default_weights
        self._validate_weights(effective_weights)

        # 步骤 1：归一化各维度分值
        normalized_scores = self._normalize_scores(candidates)

        # 步骤 2：对每个候选计算有效权重和最终分值
        aggregated = []
        for candidate, norm_scores in zip(candidates, normalized_scores):
            # 计算该候选的有效权重（处理缺失分项）
            candidate_weights = self._compute_effective_weights(
                norm_scores, effective_weights
            )

            # 加权求和
            if candidate_weights:
                final_score = sum(
                    candidate_weights[key] * norm_scores[key]
                    for key in norm_scores.keys()
                )
                final_score_source = "aggregated"
            else:
                # 所有分项均缺失
                final_score = 0.0
                final_score_source = "default_zero_not_aggregated"

            aggregated.append(AggregatedCandidate(
                case_id=candidate.case_id,
                final_score=final_score,
                score_breakdown={
                    'vector': candidate.vector_score,
                    'semantic': candidate.semantic_score,
                    'structured': candidate.structured_score,
                    'business': candidate.business_score,
                },
                normalized_scores=norm_scores,
                effective_weights=candidate_weights,
                final_score_source=final_score_source
            ))

        # 步骤 3：排序（包含并列打破）
        return self._sort_with_tiebreak(aggregated, candidates)

    def _normalize_scores(
        self, candidates: List[ScoredCandidate]
    ) -> List[Dict[str, float]]:
        """
        Min-max 归一化

        对每个维度在候选集内做归一化：
        - norm_i = (x_i - min_x) / (max_x - min_x)
        - 若 max_x == min_x，则该维度所有候选统一为 1.0
        - 最后 clip 到 [0, 1]

        Args:
            candidates: 候选列表

        Returns:
            每个候选的归一化分值字典列表
        """
        # 收集各维度的所有有效分值
        dimension_values: Dict[str, List[float]] = {
            'vector': [],
            'semantic': [],
            'structured': [],
            'business': [],
        }

        for candidate in candidates:
            dimension_values['vector'].append(candidate.vector_score)
            if candidate.semantic_score is not None:
                dimension_values['semantic'].append(candidate.semantic_score)
            if candidate.structured_score is not None:
                dimension_values['structured'].append(candidate.structured_score)
            if candidate.business_score is not None:
                dimension_values['business'].append(candidate.business_score)

        # 计算各维度的 min/max
        dimension_ranges: Dict[str, Tuple[float, float]] = {}
        for dim, values in dimension_values.items():
            if values:
                dimension_ranges[dim] = (min(values), max(values))

        # 归一化每个候选
        normalized = []
        for candidate in candidates:
            norm_scores = {}

            # Vector 分值（必有）
            if 'vector' in dimension_ranges:
                min_val, max_val = dimension_ranges['vector']
                if max_val > min_val:
                    norm_scores['vector'] = (candidate.vector_score - min_val) / (max_val - min_val)
                else:
                    norm_scores['vector'] = 1.0
                norm_scores['vector'] = max(0.0, min(1.0, norm_scores['vector']))

            # Semantic 分值（可选）
            if candidate.semantic_score is not None and 'semantic' in dimension_ranges:
                min_val, max_val = dimension_ranges['semantic']
                if max_val > min_val:
                    norm_scores['semantic'] = (candidate.semantic_score - min_val) / (max_val - min_val)
                else:
                    norm_scores['semantic'] = 1.0
                norm_scores['semantic'] = max(0.0, min(1.0, norm_scores['semantic']))

            # Structured 分值（可选）
            if candidate.structured_score is not None and 'structured' in dimension_ranges:
                min_val, max_val = dimension_ranges['structured']
                if max_val > min_val:
                    norm_scores['structured'] = (candidate.structured_score - min_val) / (max_val - min_val)
                else:
                    norm_scores['structured'] = 1.0
                norm_scores['structured'] = max(0.0, min(1.0, norm_scores['structured']))

            # Business 分值（可选）
            if candidate.business_score is not None and 'business' in dimension_ranges:
                min_val, max_val = dimension_ranges['business']
                if max_val > min_val:
                    norm_scores['business'] = (candidate.business_score - min_val) / (max_val - min_val)
                else:
                    norm_scores['business'] = 1.0
                norm_scores['business'] = max(0.0, min(1.0, norm_scores['business']))

            normalized.append(norm_scores)

        return normalized

    def _compute_effective_weights(
        self, scores: Dict[str, float], weights: Dict[str, float]
    ) -> Dict[str, float]:
        """
        计算有效权重（处理缺失分项）

        有效分项重加权公式：w'_k = w_k / sum(w_j, j in A)
        其中 A 是有效分项集合

        Args:
            scores: 该候选的归一化分值（只包含有效分项）
            weights: 原始权重配置

        Returns:
            重加权后的有效权重
        """
        available_keys = scores.keys()
        available_weights = {k: weights[k] for k in available_keys if k in weights}

        if not available_weights:
            return {}

        total_weight = sum(available_weights.values())
        return {k: v / total_weight for k, v in available_weights.items()}

    def _sort_with_tiebreak(
        self,
        aggregated: List[AggregatedCandidate],
        original: List[ScoredCandidate]
    ) -> List[AggregatedCandidate]:
        """
        排序并打破并列

        排序规则（降序）：
        1. final_score（主排序键）
        2. semantic_score_norm（并列打破）
        3. business_score_norm
        4. vector_score_norm
        5. case_updated_at（新者优先）
        6. case_id（字典序，保证稳定输出）

        Args:
            aggregated: 聚合后的候选列表
            original: 原始候选列表（用于获取 updated_at）

        Returns:
            排序后的候选列表
        """
        # 构建 case_id -> original candidate 映射
        original_map = {c.case_id: c for c in original}

        def sort_key(agg: AggregatedCandidate):
            orig = original_map[agg.case_id]
            return (
                -agg.final_score,  # 降序
                -agg.normalized_scores.get('semantic', 0.0),  # 降序
                -agg.normalized_scores.get('business', 0.0),  # 降序
                -agg.normalized_scores.get('vector', 0.0),  # 降序
                orig.case_updated_at or "",  # 降序（新者优先，ISO 8601 字典序）
                agg.case_id  # 升序（字典序）
            )

        return sorted(aggregated, key=sort_key)


# ============================================================================
# 使用示例
# ============================================================================

def example_usage():
    """使用示例"""

    # 1. 创建聚合器
    aggregator = ScoreAggregator(default_weights={
        'vector': 0.3,
        'semantic': 0.4,
        'structured': 0.1,
        'business': 0.2
    })

    # 2. 准备候选数据
    candidates = [
        ScoredCandidate(
            case_id='case_1',
            vector_score=0.95,
            semantic_score=0.88,
            structured_score=0.75,
            business_score=0.82,
            case_updated_at='2026-04-15T10:00:00Z'
        ),
        ScoredCandidate(
            case_id='case_2',
            vector_score=0.87,
            semantic_score=0.92,
            structured_score=None,  # 缺失
            business_score=0.79,
            case_updated_at='2026-04-20T10:00:00Z'
        ),
        ScoredCandidate(
            case_id='case_3',
            vector_score=0.82,
            semantic_score=None,  # 缺失
            structured_score=0.80,
            business_score=0.88,
            case_updated_at='2026-04-10T10:00:00Z'
        ),
    ]

    # 3. 聚合
    results = aggregator.aggregate(candidates)

    # 4. 输出结果
    print("聚合结果：")
    print("=" * 80)
    for i, result in enumerate(results, 1):
        print(f"\n排名 {i}: {result.case_id}")
        print(f"  最终分值: {result.final_score:.4f}")
        print(f"  分值来源: {result.final_score_source}")
        print(f"  原始分值: {result.score_breakdown}")
        print(f"  归一化分值: {result.normalized_scores}")
        print(f"  有效权重: {result.effective_weights}")


if __name__ == "__main__":
    example_usage()

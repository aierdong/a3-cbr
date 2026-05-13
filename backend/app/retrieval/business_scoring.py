"""BusinessScoreCalculator：根据业务权重和候选字段计算业务参数分。

支持相同业态、相近门店等级、同品牌、时间接近度等可配置评分因子。
输出业务参数分和每个因子的贡献明细，供聚合和响应解释使用。

设计约束：
- 支持相同业态、相近门店等级、同品牌、时间接近度等可配置评分因子
- 请求可在受控范围内调整业务权重
- 输出业务参数分和每个因子的贡献明细

Boundary: BusinessScoreCalculator
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


# =============================================================================
# Feature Flag: 全局启用开关（无 Feature Flag 要求，直接启用）
# =============================================================================


BUSINESS_SCORE_CALCULATOR_ENABLED = True


def is_business_score_calculator_enabled() -> bool:
    """检查 BusinessScoreCalculator 功能是否启用。"""
    return BUSINESS_SCORE_CALCULATOR_ENABLED


# =============================================================================
# 业务评分因子贡献明细
# =============================================================================


@dataclass
class BusinessScoreFactorContribution:
    """业务评分因子贡献明细。"""

    factor_name: str  # "business_type" | "store_tier" | "brand_affinity" | "recency"
    raw_score: float  # 原始分值（未归一化）
    normalized_score: float  # 归一化分值 [0, 1]
    weight: float  # 该因子在业务分中的权重
    contribution: float  # 权重 * 归一化分值
    matched: bool  # 是否匹配（如相同业态、同品牌等）
    details: str  # 匹配详情描述


@dataclass
class BusinessScore:
    """业务参数评分结果。

    包含业务分值、状态、因子贡献明细和计算元数据。
    """

    case_id: str
    score: float  # 业务参数总分（已归一化到 [0, 1]）
    status: str  # "computed" | "skipped" | "unavailable"
    factors: list[BusinessScoreFactorContribution]  # 各因子贡献明细
    metadata: dict[str, object]  # 计算元数据


# =============================================================================
# 默认业务评分因子配置
# =============================================================================


# 默认因子权重（与 BusinessWeights schema 对齐）
DEFAULT_BUSINESS_TYPE_WEIGHT = 0.2
DEFAULT_STORE_TIER_WEIGHT = 0.15
DEFAULT_BRAND_AFFINITY_WEIGHT = 0.1
DEFAULT_RECENCY_WEIGHT = 0.05

# 门店等级接近度阈值
STORE_TIER_TOLERANCE = 1  # 相差 1 级以内视为"相近"

# 时间接近度半衰期（天）
RECENCY_HALF_LIFE_DAYS = 180


# =============================================================================
# BusinessScoreCalculator
# =============================================================================


class BusinessScoreCalculator:
    """业务参数评分计算器。

    职责：
    1. 根据业务权重和候选字段计算业态、门店等级、品牌、时间等业务参数分
    2. 保留因子贡献明细，供聚合和响应解释使用
    3. 支持配置化的评分因子和权重

    输入：
    - NormalizedRetrievalQuery.effective_weights（有效业务权重）
    - CandidateSnapshot（候选快照，包含 brand_id、store_id、problem_type、case_updated_at 等）

    输出：
    - list[BusinessScore]，与输入候选顺序一致
    """

    def __init__(
        self,
        store_tier_tolerance: int = STORE_TIER_TOLERANCE,
        recency_half_life_days: int = RECENCY_HALF_LIFE_DAYS,
    ) -> None:
        """初始化 BusinessScoreCalculator。

        Args:
            store_tier_tolerance: 门店等级接近度容忍值（相差多少级以内视为"相近"）
            recency_half_life_days: 时间接近度半衰期（天），用于计算时间衰减
        """
        self._store_tier_tolerance = store_tier_tolerance
        self._recency_half_life_days = recency_half_life_days

    def score(
        self,
        effective_weights: dict[str, float],
        query_business_context: dict,
        candidate_snapshots: list[dict],
    ) -> list[BusinessScore]:
        """计算候选案例的业务参数分。

        Args:
            effective_weights: 有效业务权重，键为因子名
                (business_type/store_tier/brand_affinity/recency)
            query_business_context: 查询侧业务上下文，包含：
                - business_type: 查询目标业态（如 "餐饮"、"零售" 等）
                - brand_id: 查询目标品牌（可选）
                - store_tier: 查询目标门店等级（可选）
                - case_created_at_from/to: 查询时间范围（可选）
            candidate_snapshots: 候选快照列表，每项包含：
                - case_id: 案例标识
                - brand_id: 品牌标识
                - problem_type: 问题类型（用于业态判断）
                - store_id: 门店标识
                - case_updated_at: 案例更新时间
                - business_type: 候选的业态（可选，来自 structured_suggestions）

        Returns:
            业务参数评分列表，与候选顺序一致
        """
        if not candidate_snapshots:
            return []

        # 提取权重（使用默认值）
        weights = {
            "business_type": effective_weights.get(
                "business_type", DEFAULT_BUSINESS_TYPE_WEIGHT
            ),
            "store_tier": effective_weights.get(
                "store_tier", DEFAULT_STORE_TIER_WEIGHT
            ),
            "brand_affinity": effective_weights.get(
                "brand_affinity", DEFAULT_BRAND_AFFINITY_WEIGHT
            ),
            "recency": effective_weights.get(
                "recency", DEFAULT_RECENCY_WEIGHT
            ),
        }

        # 计算各因子最大可能分值（用于归一化）
        max_scores = self._compute_max_scores(weights)

        # 计算每个候选的业务分
        scores = []
        for snapshot in candidate_snapshots:
            score = self._compute_single_score(
                snapshot=snapshot,
                query_context=query_business_context,
                weights=weights,
                max_scores=max_scores,
            )
            scores.append(score)

        return scores

    def _compute_max_scores(
        self,
        weights: dict[str, float],
    ) -> dict[str, float]:
        """计算各因子最大可能分值（用于归一化）。"""
        # 各因子原始分最大值（与评分逻辑一致）
        return {
            "business_type": 1.0,  # 精确匹配为 1
            "store_tier": 1.0,  # 精确或相近为 1
            "brand_affinity": 1.0,  # 同品牌为 1
            "recency": 1.0,  # 最新为 1
        }

    def _compute_single_score(
        self,
        snapshot: dict,
        query_context: dict,
        weights: dict[str, float],
        max_scores: dict[str, float],
    ) -> BusinessScore:
        """计算单个候选的业务参数分。"""
        case_id = snapshot.get("case_id", "")
        factors: list[BusinessScoreFactorContribution] = []
        total_contribution = 0.0

        # 1. 业态匹配分
        business_type_score, business_type_details = self._compute_business_type_score(
            query_context.get("business_type"),
            snapshot.get("problem_type"),  # 使用 problem_type 作为业态指标
        )
        business_type_contribution = weights["business_type"] * business_type_score
        total_contribution += business_type_contribution

        factors.append(BusinessScoreFactorContribution(
            factor_name="business_type",
            raw_score=business_type_score,
            normalized_score=business_type_score / max_scores["business_type"]
            if max_scores["business_type"] > 0 else 0.0,
            weight=weights["business_type"],
            contribution=business_type_contribution,
            matched=business_type_score > 0,
            details=business_type_details,
        ))

        # 2. 门店等级接近度分
        store_tier_score, store_tier_details = self._compute_store_tier_score(
            query_context.get("store_tier"),
            snapshot.get("store_tier"),
        )
        store_tier_contribution = weights["store_tier"] * store_tier_score
        total_contribution += store_tier_contribution

        factors.append(BusinessScoreFactorContribution(
            factor_name="store_tier",
            raw_score=store_tier_score,
            normalized_score=store_tier_score / max_scores["store_tier"]
            if max_scores["store_tier"] > 0 else 0.0,
            weight=weights["store_tier"],
            contribution=store_tier_contribution,
            matched=store_tier_score >= (1.0 - self._store_tier_tolerance * 0.5),
            details=store_tier_details,
        ))

        # 3. 品牌亲和度分
        brand_score, brand_details = self._compute_brand_affinity_score(
            query_context.get("brand_id"),
            snapshot.get("brand_id"),
        )
        brand_contribution = weights["brand_affinity"] * brand_score
        total_contribution += brand_contribution

        factors.append(BusinessScoreFactorContribution(
            factor_name="brand_affinity",
            raw_score=brand_score,
            normalized_score=brand_score / max_scores["brand_affinity"]
            if max_scores["brand_affinity"] > 0 else 0.0,
            weight=weights["brand_affinity"],
            contribution=brand_contribution,
            matched=brand_score > 0,
            details=brand_details,
        ))

        # 4. 时间接近度分
        recency_score, recency_details = self._compute_recency_score(
            query_context.get("case_created_at_from"),
            query_context.get("case_created_at_to"),
            snapshot.get("case_updated_at"),
        )
        recency_contribution = weights["recency"] * recency_score
        total_contribution += recency_contribution

        factors.append(BusinessScoreFactorContribution(
            factor_name="recency",
            raw_score=recency_score,
            normalized_score=recency_score / max_scores["recency"]
            if max_scores["recency"] > 0 else 0.0,
            weight=weights["recency"],
            contribution=recency_contribution,
            matched=recency_score > 0.5,  # 中位数以上视为"匹配"
            details=recency_details,
        ))

        return BusinessScore(
            case_id=case_id,
            score=min(total_contribution, 1.0),  # 裁剪到 [0, 1]
            status="computed",
            factors=factors,
            metadata={
                "weights_used": weights,
                "case_count": len(factors),
            },
        )

    def _compute_business_type_score(
        self,
        query_business_type: Optional[str],
        candidate_problem_type: Optional[str],
    ) -> tuple[float, str]:
        """计算业态匹配分。

        简化实现：使用 problem_type 作为业态指标。
        完全匹配返回 1.0，不匹配返回 0.0。
        后续可扩展为语义相似度匹配。
        """
        if not query_business_type or not candidate_problem_type:
            return 0.0, "未提供查询业态或候选问题类型"

        # 简化：直接比较是否相同
        matched = query_business_type == candidate_problem_type
        score = 1.0 if matched else 0.0

        if matched:
            return (
                score,
                f"业态匹配: 查询'{query_business_type}' == "
                f"候选'{candidate_problem_type}'",
            )
        else:
            return (
                score,
                f"业态不匹配: 查询'{query_business_type}' != "
                f"候选'{candidate_problem_type}'",
            )

    def _compute_store_tier_score(
        self,
        query_store_tier: Optional[str],
        candidate_store_tier: Optional[str],
    ) -> tuple[float, str]:
        """计算门店等级接近度分。

        精确匹配或相差在容忍范围内返回 1.0，完全不匹配返回 0.0。
        """
        if not query_store_tier or not candidate_store_tier:
            return 0.0, "未提供查询门店等级或候选门店等级"

        # 尝试解析为数字等级
        try:
            query_tier = int(query_store_tier)
            candidate_tier = int(candidate_store_tier)
        except (ValueError, TypeError):
            # 非数字等级，精确比较
            matched = query_store_tier == candidate_store_tier
            score = 1.0 if matched else 0.0
            match_word = "匹配" if matched else "不匹配"
            details = (
                f"门店等级{match_word}: "
                f"查询'{query_store_tier}' vs 候选'{candidate_store_tier}'"
            )
            return score, details

        # 计算等级差
        tier_diff = abs(query_tier - candidate_tier)
        if tier_diff == 0:
            return 1.0, f"门店等级完全匹配: {query_tier} == {candidate_tier}"
        elif tier_diff <= self._store_tier_tolerance:
            # 在容忍范围内，按距离衰减
            score = 1.0 - (tier_diff / (self._store_tier_tolerance + 1))
            return (
                score,
                f"门店等级相近: |{query_tier} - {candidate_tier}| = "
                f"{tier_diff} <= {self._store_tier_tolerance}",
            )
        else:
            return (
                0.0,
                f"门店等级差异过大: |{query_tier} - {candidate_tier}| = "
                f"{tier_diff} > {self._store_tier_tolerance}",
            )

    def _compute_brand_affinity_score(
        self,
        query_brand_id: Optional[str],
        candidate_brand_id: Optional[str],
    ) -> tuple[float, str]:
        """计算品牌亲和度分。"""
        if not query_brand_id or not candidate_brand_id:
            return 0.0, "未提供查询品牌或候选品牌"

        matched = query_brand_id == candidate_brand_id
        score = 1.0 if matched else 0.0

        if matched:
            return score, f"品牌匹配: 查询'{query_brand_id}' == 候选'{candidate_brand_id}'"
        else:
            return score, f"品牌不匹配: 查询'{query_brand_id}' != 候选'{candidate_brand_id}'"

    def _compute_recency_score(
        self,
        query_date_from: Optional[datetime],
        query_date_to: Optional[datetime],
        candidate_updated_at: Optional[datetime],
    ) -> tuple[float, str]:
        """计算时间接近度分。

        使用半衰期衰减模型：
        - 最新案例得分为 1.0
        - 随时间线性衰减，半衰期后降至 0.5
        - 超过两倍半衰期降至接近 0
        """
        if not candidate_updated_at:
            return 0.0, "候选无更新时间"

        # 与 ORM/Pydantic 中 timezone-aware 的 case_updated_at 对齐，避免 naive/aware 相减
        now = datetime.now(timezone.utc)
        candidate_at = candidate_updated_at
        if candidate_at.tzinfo is None:
            candidate_at = candidate_at.replace(tzinfo=timezone.utc)
        age_days = (now - candidate_at).days

        # 计算衰减分
        # 使用指数衰减：score = 0.5 ^ (age / half_life)
        import math
        score = math.pow(0.5, age_days / self._recency_half_life_days)

        # 如果有时间范围限制，检查是否在范围内（统一为 UTC 再比较）
        def _to_utc_bound(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        if query_date_from:
            q_from = _to_utc_bound(query_date_from)
            if candidate_at < q_from:
                return (
                    0.0,
                    f"候选时间 {candidate_at.date()} "
                    f"早于查询起始 {q_from.date()}",
                )
        if query_date_to:
            q_to = _to_utc_bound(query_date_to)
            if candidate_at > q_to:
                return (
                    0.0,
                    f"候选时间 {candidate_at.date()} "
                    f"晚于查询结束 {q_to.date()}",
                )

        return (
            score,
            f"时间接近度: 案例年龄 {age_days} 天，"
            f"半衰期 {self._recency_half_life_days} 天，评分 {score:.4f}",
        )
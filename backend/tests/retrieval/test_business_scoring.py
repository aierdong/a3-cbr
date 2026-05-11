"""BusinessScoreCalculator 单元测试。

测试 BusinessScoreCalculator 的：
1. 成功路径：计算业务参数分
2. 因子贡献明细验证：business_type, store_tier, brand_affinity, recency
3. 权重应用验证
4. 时间接近度计算
5. 空候选列表处理

无 Feature Flag 要求，直接启用。
"""

from datetime import datetime, timedelta

import pytest

from app.retrieval.business_scoring import (
    BusinessScore,
    BusinessScoreCalculator,
    BusinessScoreFactorContribution,
    DEFAULT_BUSINESS_TYPE_WEIGHT,
    DEFAULT_BRAND_AFFINITY_WEIGHT,
    DEFAULT_RECENCY_WEIGHT,
    DEFAULT_STORE_TIER_WEIGHT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_effective_weights(
    business_type: float = DEFAULT_BUSINESS_TYPE_WEIGHT,
    store_tier: float = DEFAULT_STORE_TIER_WEIGHT,
    brand_affinity: float = DEFAULT_BRAND_AFFINITY_WEIGHT,
    recency: float = DEFAULT_RECENCY_WEIGHT,
) -> dict[str, float]:
    """构造有效业务权重。"""
    return {
        "business_type": business_type,
        "store_tier": store_tier,
        "brand_affinity": brand_affinity,
        "recency": recency,
    }


def _make_query_context(
    business_type: str = "零售",
    brand_id: str = "brand-001",
    store_tier: str = "3",
    case_created_at_from: datetime | None = None,
    case_created_at_to: datetime | None = None,
) -> dict:
    """构造查询侧业务上下文。"""
    return {
        "business_type": business_type,
        "brand_id": brand_id,
        "store_tier": store_tier,
        "case_created_at_from": case_created_at_from,
        "case_created_at_to": case_created_at_to,
    }


def _make_candidate_snapshot(
    case_id: str = "case-001",
    brand_id: str = "brand-001",
    problem_type: str = "零售",
    store_tier: str = "3",
    case_updated_at: datetime | None = None,
    store_scale: str = "中型",
) -> dict:
    """构造候选快照。"""
    return {
        "case_id": case_id,
        "brand_id": brand_id,
        "problem_type": problem_type,
        "store_tier": store_tier,
        "case_updated_at": case_updated_at or datetime.now() - timedelta(days=30),
        "store_scale": store_scale,
    }


# ---------------------------------------------------------------------------
# Tests: 初始化和 Feature Flag
# ---------------------------------------------------------------------------


class TestBusinessScoreCalculatorInit:
    """BusinessScoreCalculator 初始化测试。"""

    def test_default_init(self):
        """默认初始化使用常量配置。"""
        calculator = BusinessScoreCalculator()
        assert calculator._store_tier_tolerance == 1
        assert calculator._recency_half_life_days == 180

    def test_custom_init(self):
        """自定义初始化。"""
        calculator = BusinessScoreCalculator(
            store_tier_tolerance=2,
            recency_half_life_days=365,
        )
        assert calculator._store_tier_tolerance == 2
        assert calculator._recency_half_life_days == 365


# ---------------------------------------------------------------------------
# Tests: 空候选列表处理
# ---------------------------------------------------------------------------


class TestBusinessScoreCalculatorEmptyCandidates:
    """空候选列表处理测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_score_returns_empty_list_for_empty_candidates(self):
        """空候选列表返回空列表。"""
        weights = _make_effective_weights()
        context = _make_query_context()
        result = self._calculator.score(weights, context, [])
        assert result == []


# ---------------------------------------------------------------------------
# Tests: 成功路径
# ---------------------------------------------------------------------------


class TestBusinessScoreCalculatorSuccess:
    """BusinessScoreCalculator 成功场景测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_score_returns_business_scores_for_candidates(self):
        """返回候选的业务分列表。"""
        weights = _make_effective_weights()
        context = _make_query_context()
        candidates = [
            _make_candidate_snapshot("case-001"),
            _make_candidate_snapshot("case-002"),
        ]
        result = self._calculator.score(weights, context, candidates)

        assert len(result) == 2
        assert all(isinstance(r, BusinessScore) for r in result)

    def test_score_preserves_case_id_order(self):
        """返回结果顺序与候选顺序一致。"""
        weights = _make_effective_weights()
        context = _make_query_context()
        candidates = [
            _make_candidate_snapshot("case-A"),
            _make_candidate_snapshot("case-B"),
            _make_candidate_snapshot("case-C"),
        ]
        result = self._calculator.score(weights, context, candidates)

        assert len(result) == 3
        assert result[0].case_id == "case-A"
        assert result[1].case_id == "case-B"
        assert result[2].case_id == "case-C"

    def test_score_includes_four_factors(self):
        """每个结果包含四个因子贡献明细。"""
        weights = _make_effective_weights()
        context = _make_query_context()
        candidates = [_make_candidate_snapshot("case-001")]
        result = self._calculator.score(weights, context, candidates)

        assert len(result) == 1
        factors = result[0].factors
        assert len(factors) == 4
        factor_names = {f.factor_name for f in factors}
        assert factor_names == {"business_type", "store_tier", "brand_affinity", "recency"}

    def test_score_status_is_computed(self):
        """正常计算时 status 为 "computed"。"""
        weights = _make_effective_weights()
        context = _make_query_context()
        candidates = [_make_candidate_snapshot("case-001")]
        result = self._calculator.score(weights, context, candidates)

        assert result[0].status == "computed"

    def test_score_includes_metadata(self):
        """结果包含 metadata 字段。"""
        weights = _make_effective_weights()
        context = _make_query_context()
        candidates = [_make_candidate_snapshot("case-001")]
        result = self._calculator.score(weights, context, candidates)

        assert "weights_used" in result[0].metadata
        assert "case_count" in result[0].metadata


# ---------------------------------------------------------------------------
# Tests: 业态匹配分
# ---------------------------------------------------------------------------


class TestBusinessTypeScore:
    """业态匹配分测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_business_type_exact_match_returns_one(self):
        """精确匹配业态返回 1.0。"""
        score, details = self._calculator._compute_business_type_score(
            "零售", "零售"
        )
        assert score == 1.0
        assert "匹配" in details

    def test_business_type_mismatch_returns_zero(self):
        """不匹配业态返回 0.0。"""
        score, details = self._calculator._compute_business_type_score(
            "零售", "餐饮"
        )
        assert score == 0.0
        assert "不匹配" in details

    def test_business_type_missing_query_returns_zero(self):
        """缺少查询业态返回 0.0。"""
        score, _ = self._calculator._compute_business_type_score(None, "零售")
        assert score == 0.0

    def test_business_type_missing_candidate_returns_zero(self):
        """缺少候选业态返回 0.0。"""
        score, _ = self._calculator._compute_business_type_score("零售", None)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Tests: 门店等级接近度分
# ---------------------------------------------------------------------------


class TestStoreTierScore:
    """门店等级接近度分测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_store_tier_exact_match_returns_one(self):
        """精确匹配返回 1.0。"""
        score, details = self._calculator._compute_store_tier_score("3", "3")
        assert score == 1.0
        assert "完全匹配" in details

    def test_store_tier_close_match_returns_partial(self):
        """在容忍范围内返回部分分数。"""
        score, details = self._calculator._compute_store_tier_score("3", "4")
        assert 0 < score < 1.0
        assert "相近" in details

    def test_store_tier_far_mismatch_returns_zero(self):
        """超出容忍范围返回 0.0。"""
        score, details = self._calculator._compute_store_tier_score("3", "5")
        assert score == 0.0
        assert "差异过大" in details

    def test_store_tier_string_match(self):
        """字符串等级精确匹配。"""
        score, _ = self._calculator._compute_store_tier_score("大型", "大型")
        assert score == 1.0

    def test_store_tier_missing_returns_zero(self):
        """缺少任一等级返回 0.0。"""
        score, _ = self._calculator._compute_store_tier_score(None, "3")
        assert score == 0.0
        score, _ = self._calculator._compute_store_tier_score("3", None)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Tests: 品牌亲和度分
# ---------------------------------------------------------------------------


class TestBrandAffinityScore:
    """品牌亲和度分测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_brand_affinity_same_brand_returns_one(self):
        """同品牌返回 1.0。"""
        score, details = self._calculator._compute_brand_affinity_score(
            "brand-001", "brand-001"
        )
        assert score == 1.0
        assert "匹配" in details

    def test_brand_affinity_different_brand_returns_zero(self):
        """不同品牌返回 0.0。"""
        score, details = self._calculator._compute_brand_affinity_score(
            "brand-001", "brand-002"
        )
        assert score == 0.0
        assert "不匹配" in details

    def test_brand_affinity_missing_returns_zero(self):
        """缺少任一品牌返回 0.0。"""
        score, _ = self._calculator._compute_brand_affinity_score(None, "brand-001")
        assert score == 0.0
        score, _ = self._calculator._compute_brand_affinity_score("brand-001", None)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Tests: 时间接近度分
# ---------------------------------------------------------------------------


class TestRecencyScore:
    """时间接近度分测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_recency_recent_case_returns_high_score(self):
        """最近案例返回高分。"""
        recent_time = datetime.now() - timedelta(days=1)
        score, details = self._calculator._compute_recency_score(
            None, None, recent_time
        )
        assert 0.9 < score <= 1.0

    def test_recency_old_case_returns_low_score(self):
        """老案例返回低分（超过半衰期）。"""
        # 超过 2 个半衰期（180 * 2 = 360 天），分数应 < 0.25
        old_time = datetime.now() - timedelta(days=400)
        score, details = self._calculator._compute_recency_score(
            None, None, old_time
        )
        assert 0.0 < score < 0.3

    def test_recency_before_date_range_returns_zero(self):
        """早于查询起始时间返回 0.0。"""
        candidate_time = datetime(2023, 1, 1)
        query_from = datetime(2024, 1, 1)
        score, details = self._calculator._compute_recency_score(
            query_from, None, candidate_time
        )
        assert score == 0.0

    def test_recency_after_date_range_returns_zero(self):
        """晚于查询结束时间返回 0.0。"""
        candidate_time = datetime(2025, 1, 1)
        query_to = datetime(2024, 12, 31)
        score, details = self._calculator._compute_recency_score(
            None, query_to, candidate_time
        )
        assert score == 0.0

    def test_recency_missing_time_returns_zero(self):
        """缺少时间返回 0.0。"""
        score, _ = self._calculator._compute_recency_score(None, None, None)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Tests: 权重应用
# ---------------------------------------------------------------------------


class TestWeightApplication:
    """权重应用测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_weights_are_used_in_score_calculation(self):
        """权重应用于总分计算。"""
        # 使用自定义权重
        weights = {
            "business_type": 0.5,
            "store_tier": 0.3,
            "brand_affinity": 0.1,
            "recency": 0.1,
        }
        context = _make_query_context(
            business_type="零售",
            brand_id="brand-001",
            store_tier="3",
        )
        candidates = [
            _make_candidate_snapshot(
                "case-001",
                problem_type="零售",
                brand_id="brand-001",
                store_tier="3",
            )
        ]
        result = self._calculator.score(weights, context, candidates)

        # 检查 metadata 中使用了正确的权重
        assert result[0].metadata["weights_used"]["business_type"] == 0.5
        assert result[0].metadata["weights_used"]["store_tier"] == 0.3

    def test_default_weights_when_not_provided(self):
        """未提供权重时使用默认值。"""
        weights = {}  # 空权重
        context = _make_query_context()
        candidates = [_make_candidate_snapshot("case-001")]
        result = self._calculator.score(weights, context, candidates)

        # 应该使用默认权重
        used_weights = result[0].metadata["weights_used"]
        assert used_weights["business_type"] == DEFAULT_BUSINESS_TYPE_WEIGHT
        assert used_weights["store_tier"] == DEFAULT_STORE_TIER_WEIGHT


# ---------------------------------------------------------------------------
# Tests: 因子贡献明细
# ---------------------------------------------------------------------------


class TestFactorContributions:
    """因子贡献明细测试。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._calculator = BusinessScoreCalculator()

    def test_factor_contribution_has_required_fields(self):
        """每个因子贡献包含必需字段。"""
        weights = _make_effective_weights()
        context = _make_query_context()
        candidates = [_make_candidate_snapshot("case-001")]
        result = self._calculator.score(weights, context, candidates)

        for factor in result[0].factors:
            assert hasattr(factor, "factor_name")
            assert hasattr(factor, "raw_score")
            assert hasattr(factor, "normalized_score")
            assert hasattr(factor, "weight")
            assert hasattr(factor, "contribution")
            assert hasattr(factor, "matched")
            assert hasattr(factor, "details")

    def test_factor_matched_flag(self):
        """matched 标志正确反映匹配状态。"""
        weights = _make_effective_weights()
        context = _make_query_context(
            business_type="零售",
            brand_id="brand-001",
        )
        # 完全匹配候选
        candidates = [
            _make_candidate_snapshot(
                "case-matched",
                problem_type="零售",
                brand_id="brand-001",
            ),
            # 不匹配候选
            _make_candidate_snapshot(
                "case-unmatched",
                problem_type="餐饮",
                brand_id="brand-002",
            ),
        ]
        result = self._calculator.score(weights, context, candidates)

        # 匹配候选
        matched_factor = next(
            f for f in result[0].factors if f.factor_name == "business_type"
        )
        assert matched_factor.matched is True

        # 不匹配候选
        unmatched_factor = next(
            f for f in result[1].factors if f.factor_name == "business_type"
        )
        assert unmatched_factor.matched is False
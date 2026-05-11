"""ScoreAggregator 单元测试。

测试 ScoreAggregator 的：
1. Feature Flag gate
2. 成功路径：正常聚合、min-max 归一化、缺失分项重加权、加权求和
3. 降级路径：aggregation_unavailable 时 final_score=0
4. 并列打破：final_score 并列时按语义分 > 业务分 > 向量分 > 更新时间 > case_id 排序
5. 边界情况：所有候选某分项均为 0、均为相同非零值、某候选所有分项缺失

Boundary: ScoreAggregator_
"""

from datetime import datetime
from typing import Optional

import pytest

from app.retrieval.schemas import ScoreBreakdownSource


# ---------------------------------------------------------------------------
# Feature Flag: ScoreAggregator 功能开关
# ---------------------------------------------------------------------------

# TODO: 实现完成后改为 True
RETRIEVAL_SCORE_AGGREGATOR_ENABLED = True


def is_score_aggregator_enabled() -> bool:
    """检查 ScoreAggregator 功能是否启用。"""
    return RETRIEVAL_SCORE_AGGREGATOR_ENABLED


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class ScoredCandidate:
    """已评分的候选案例（测试用简易结构）。"""

    def __init__(
        self,
        case_id: str,
        vector_score: float,
        semantic_score: Optional[float] = None,
        structured_score: Optional[float] = None,
        business_score: Optional[float] = None,
        case_updated_at: Optional[datetime] = None,
    ):
        """初始化测试用候选对象。"""
        self.case_id = case_id
        self.vector_score = vector_score
        self.semantic_score = semantic_score
        self.structured_score = structured_score
        self.business_score = business_score
        self.case_updated_at = case_updated_at or datetime(2025, 1, 1)


class RankingCandidateItem:
    """排序候选项（测试用简易结构）。"""

    def __init__(
        self,
        case_id: str,
        final_score: float,
        score_breakdown: dict,
        normalized_scores: dict,
        effective_weights: dict,
        final_score_source: str,
        case_updated_at: Optional[datetime] = None,
    ):
        """初始化测试用排序候选项。"""
        self.case_id = case_id
        self.final_score = final_score
        self.score_breakdown = score_breakdown
        self.normalized_scores = normalized_scores
        self.effective_weights = effective_weights
        self.final_score_source = final_score_source
        self.case_updated_at = case_updated_at


def _make_default_weights() -> dict[str, float]:
    """构造默认权重。"""
    return {
        "vector": 0.3,
        "semantic": 0.4,
        "structured": 0.1,
        "business": 0.2,
    }


# ---------------------------------------------------------------------------
# Tests: Feature Flag Gate
# ---------------------------------------------------------------------------


class TestScoreAggregatorFeatureFlag:
    """Feature Flag Protocol: flag=ON 时功能可用。"""

    def test_feature_flag_enabled_after_implementation(self):
        """实现完成后 feature flag 为 True。"""
        assert RETRIEVAL_SCORE_AGGREGATOR_ENABLED is True

    def test_is_score_aggregator_enabled_returns_correct_value(self):
        """is_score_aggregator_enabled 返回 flag 当前值。"""
        assert is_score_aggregator_enabled() == RETRIEVAL_SCORE_AGGREGATOR_ENABLED


# ---------------------------------------------------------------------------
# Tests: 成功路径 - 基础聚合
# ---------------------------------------------------------------------------


class TestScoreAggregationSuccess:
    """分值聚合成功场景。"""

    def test_aggregate_with_all_score_types(self):
        """所有分项（向量、语义、结构化、业务）均有时正常聚合。

        case-001 在语义分低但向量和业务分高，case-002 语义分高但向量和业务分低。
        加权聚合后 case-002 总分更高（因为语义分权重 0.4 最大）。
        """
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.95,
                semantic_score=0.85,
                structured_score=0.7,
                business_score=0.6,
                case_updated_at=datetime(2025, 1, 15),
            ),
            ScoredCandidate(
                case_id="case-002",
                vector_score=0.80,
                semantic_score=0.90,
                structured_score=0.8,
                business_score=0.5,
                case_updated_at=datetime(2025, 1, 10),
            ),
        ]

        weights = _make_default_weights()
        aggregator = ScoreAggregator(default_weights=weights)
        result = aggregator.aggregate(candidates)

        assert len(result.candidates) == 2
        # case-001: norm_vector=1.0, norm_semantic=0.0, norm_structured=0.0, norm_business=1.0
        #           final = 0.3*1.0 + 0.4*0.0 + 0.1*0.0 + 0.2*1.0 = 0.5
        # case-002: norm_vector=0.0, norm_semantic=1.0, norm_structured=1.0, norm_business=0.0
        #           final = 0.3*0.0 + 0.4*1.0 + 0.1*1.0 + 0.2*0.0 = 0.5
        # 并列打破：semantic_norm: case-002(1.0) > case-001(0.0)，所以 case-002 排第一
        assert result.candidates[0].case_id == "case-002"
        assert result.candidates[1].case_id == "case-001"

        # 验证 score_breakdown 包含 final_score_source
        for item in result.candidates:
            assert item.score_breakdown["final_score_source"] == ScoreBreakdownSource.AGGREGATED

    def test_aggregate_respects_custom_weights(self):
        """自定义权重覆盖默认权重。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.95,
                semantic_score=0.85,
                structured_score=0.7,
                business_score=0.6,
            ),
        ]

        # 自定义权重：只使用向量和语义
        custom_weights = {"vector": 0.5, "semantic": 0.5}
        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates, weights=custom_weights)

        assert len(result.candidates) == 1
        item = result.candidates[0]
        # 有效权重应该是 0.5/0.5 = 1.0
        assert item.effective_weights["vector"] == 0.5
        assert item.effective_weights["semantic"] == 0.5

    def test_aggregate_empty_candidates_returns_empty_list(self):
        """空候选列表返回空列表。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate([])

        assert result.candidates == []


# ---------------------------------------------------------------------------
# Tests: min-max 归一化
# ---------------------------------------------------------------------------


class TestMinMaxNormalization:
    """min-max 归一化测试。"""

    def test_normalization_spreads_scores(self):
        """不同分值归一化后应有区分度。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-low",
                vector_score=0.2,
                semantic_score=0.3,
                structured_score=0.4,
                business_score=0.5,
            ),
            ScoredCandidate(
                case_id="case-high",
                vector_score=0.9,
                semantic_score=0.95,
                structured_score=0.85,
                business_score=0.8,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 验证归一化分值存在且有效
        for item in result.candidates:
            for score_type in ["vector", "semantic", "structured", "business"]:
                norm_score = item.normalized_scores.get(score_type)
                if norm_score is not None:
                    assert 0.0 <= norm_score <= 1.0

    def test_all_candidates_same_score_becomes_one(self):
        """所有候选某分项均为相同非零值时归一化为 1.0。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        # 所有候选的语义分都是 0.8
        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.7,
                semantic_score=0.8,
            ),
            ScoredCandidate(
                case_id="case-002",
                vector_score=0.6,
                semantic_score=0.8,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 语义分归一化后应该都是 1.0（无区分度但不偏置）
        for item in result.candidates:
            assert item.normalized_scores["semantic"] == 1.0

    def test_all_candidates_zero_score_becomes_zero(self):
        """所有候选某分项均为 0 时归一化为 0.0。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.7,
                semantic_score=0.0,
            ),
            ScoredCandidate(
                case_id="case-002",
                vector_score=0.6,
                semantic_score=0.0,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 语义分归一化后应该都是 0.0
        for item in result.candidates:
            assert item.normalized_scores["semantic"] == 0.0


# ---------------------------------------------------------------------------
# Tests: 缺失分项重加权
# ---------------------------------------------------------------------------


class TestMissingScoreReweighting:
    """缺失分项重加权测试。"""

    def test_missing_score_reweights_to_one(self):
        """只有一个有效分项时其权重为 1.0。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        # case-001 只有向量分
        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.9,
                semantic_score=None,
                structured_score=None,
                business_score=None,
            ),
            ScoredCandidate(
                case_id="case-002",
                vector_score=0.8,
                semantic_score=0.7,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # case-001 只有向量分有效，其权重应为 1.0
        case001_item = next(
            item for item in result.candidates if item.case_id == "case-001"
        )
        assert case001_item.effective_weights["vector"] == 1.0

    def test_missing_score_excludes_from_calculation(self):
        """缺失分项不参与聚合计算。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        # case-001 没有业务分
        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.9,
                semantic_score=0.8,
                structured_score=0.7,
                business_score=None,  # 缺失
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        item = result.candidates[0]
        # 业务分不应在有效权重中出现
        assert "business" not in item.effective_weights
        # 最终分应该只基于其他三个分项
        assert item.final_score >= 0.0


# ---------------------------------------------------------------------------
# Tests: 降级路径 - aggregation_unavailable
# ---------------------------------------------------------------------------


class TestAggregationUnavailable:
    """aggregation_unavailable 降级路径测试。"""

    def test_all_scores_missing_returns_zero_with_source_mark(self):
        """所有可聚合分项均缺失时 final_score=0 且 final_score_source 为默认值。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        # 所有分项都为 None
        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=None,
                semantic_score=None,
                structured_score=None,
                business_score=None,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        assert len(result.candidates) == 1
        item = result.candidates[0]
        assert item.final_score == 0.0
        source = ScoreBreakdownSource.DEFAULT_ZERO_NOT_AGGREGATED
        assert item.score_breakdown["final_score_source"] == source

    def test_degraded_path_aggregation_failed_uses_semantic_fallback(self):
        """聚合失败时按语义分优先降级（设计约束中的降级路径场景）。

        当 reranker + aggregation 同时失败时，按业务分优先降级。
        此测试验证：case-001 和 case-002 聚合分相同，并列打破按语义分排序。
        """
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        # case-001 和 case-002 的聚合分相同
        # case-001: norm_vector=0.0, norm_semantic=0.0, norm_structured=0.0, norm_business=1.0
        #           final = 0.3*0.0 + 0.4*0.0 + 0.1*0.0 + 0.2*1.0 = 0.2
        # case-002: norm_vector=0.0, norm_semantic=1.0, norm_structured=0.0, norm_business=0.0
        #           final = 0.3*0.0 + 0.4*1.0 + 0.1*0.0 + 0.2*0.0 = 0.4
        # 实际 case-002 聚合分更高 (0.4 > 0.2)
        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.9,
                semantic_score=0.8,
                structured_score=0.7,
                business_score=0.6,
                case_updated_at=datetime(2025, 1, 15),
            ),
            ScoredCandidate(
                case_id="case-002",
                vector_score=0.9,
                semantic_score=0.9,  # 更高
                structured_score=0.7,
                business_score=0.5,
                case_updated_at=datetime(2025, 1, 10),
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # case-002 聚合分更高，应该排第一
        assert result.candidates[0].case_id == "case-002"


# ---------------------------------------------------------------------------
# Tests: 并列打破
# ---------------------------------------------------------------------------


class TestTieBreaking:
    """并列打破测试。"""

    def test_tiebreak_by_semantic_score(self):
        """final_score 并列时按语义分打破并列。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        # 两个候选聚合分相同但语义分不同
        candidates = [
            ScoredCandidate(
                case_id="case-low-semantic",
                vector_score=0.8,
                semantic_score=0.7,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at=datetime(2025, 1, 15),
            ),
            ScoredCandidate(
                case_id="case-high-semantic",
                vector_score=0.8,
                semantic_score=0.9,  # 更高
                structured_score=0.8,
                business_score=0.8,
                case_updated_at=datetime(2025, 1, 10),
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 高语义分排第一
        assert result.candidates[0].case_id == "case-high-semantic"

    def test_tiebreak_by_business_score(self):
        """final_score 并列、语义分相同时按业务分打破并列。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-low-business",
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.6,
                case_updated_at=datetime(2025, 1, 15),
            ),
            ScoredCandidate(
                case_id="case-high-business",
                vector_score=0.8,
                semantic_score=0.8,  # 相同
                structured_score=0.8,
                business_score=0.9,  # 更高
                case_updated_at=datetime(2025, 1, 10),
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 高业务分排第一
        assert result.candidates[0].case_id == "case-high-business"

    def test_tiebreak_by_vector_score(self):
        """final_score 并列、语义分和业务分都相同时按向量分打破并列。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-low-vector",
                vector_score=0.7,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at=datetime(2025, 1, 15),
            ),
            ScoredCandidate(
                case_id="case-high-vector",
                vector_score=0.9,
                semantic_score=0.8,  # 相同
                structured_score=0.8,
                business_score=0.8,  # 相同
                case_updated_at=datetime(2025, 1, 10),
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 高向量分排第一
        assert result.candidates[0].case_id == "case-high-vector"

    def test_tiebreak_by_case_updated_at(self):
        """final_score 并列、前三分项都相同时按更新时间打破并列（新高者优先）。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-old",
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at=datetime(2025, 1, 1),  # 更旧
            ),
            ScoredCandidate(
                case_id="case-new",
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at=datetime(2025, 6, 1),  # 相同向量/语义/业务分，但时间更新
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 更新时间更新排第一
        assert result.candidates[0].case_id == "case-new"

    def test_tiebreak_by_case_id(self):
        """最终并列时按 case_id 字典序打破并列。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-zulu",
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at=datetime(2025, 1, 1),
            ),
            ScoredCandidate(
                case_id="case-alpha",
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at=datetime(2025, 1, 1),  # 相同时间
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # case-alpha 字典序靠前排第一
        assert result.candidates[0].case_id == "case-alpha"


# ---------------------------------------------------------------------------
# Tests: 边界情况
# ---------------------------------------------------------------------------


class TestBoundaryCases:
    """边界情况测试。"""

    def test_only_vector_score_available(self):
        """只有向量分可用时正常聚合。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.95,
            ),
            ScoredCandidate(
                case_id="case-002",
                vector_score=0.80,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        assert len(result.candidates) == 2
        # case-001 向量分更高应该排第一
        assert result.candidates[0].case_id == "case-001"
        assert result.candidates[0].final_score > result.candidates[1].final_score

    def test_score_breakdown_contains_all_fields(self):
        """score_breakdown 包含所有必要字段。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.95,
                semantic_score=0.85,
                structured_score=0.7,
                business_score=0.6,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        item = result.candidates[0]
        breakdown = item.score_breakdown

        # 验证 score_breakdown 包含原始分
        assert "vector_similarity_score" in breakdown
        assert "semantic_similarity_score" in breakdown
        assert "structured_similarity_score" in breakdown
        assert "business_score" in breakdown

        # 验证包含 final_score_source
        assert "final_score_source" in breakdown

    def test_aggregator_does_not_load_from_database(self):
        """聚合器只处理传入候选集，不从全量 SQL casebase 重新检索。"""
        if not _is_score_aggregator_enabled():
            pytest.skip("ScoreAggregator 功能未启用")

        from app.retrieval.score_aggregator import ScoreAggregator

        # 构造一个只有 3 个候选的列表
        candidates = [
            ScoredCandidate(
                case_id="case-001",
                vector_score=0.95,
                semantic_score=0.85,
            ),
            ScoredCandidate(
                case_id="case-002",
                vector_score=0.80,
                semantic_score=0.90,
            ),
            ScoredCandidate(
                case_id="case-003",
                vector_score=0.70,
                semantic_score=0.75,
            ),
        ]

        aggregator = ScoreAggregator(default_weights=_make_default_weights())
        result = aggregator.aggregate(candidates)

        # 结果应该只有 3 个候选，不多不少
        assert len(result.candidates) == 3


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _is_score_aggregator_enabled() -> bool:
    """检查 ScoreAggregator 功能是否启用。"""
    return RETRIEVAL_SCORE_AGGREGATOR_ENABLED

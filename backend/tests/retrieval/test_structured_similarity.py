"""StructuredSimilarityScorer 单元测试。

测试 StructuredSimilarityScorer 的：
1. Feature Flag gate
2. MVP skipped 路径：所有候选返回 status="skipped"
3. 结构化分预留字段验证：score=None, factors, metadata
4. 空候选列表处理

Feature Flag 协议：
- RED 阶段：flag=False，测试跳过
- GREEN 阶段：flag=True，测试执行
- 测试文件从 structured_similarity.py 导入 flag，保持同步
"""

from unittest.mock import MagicMock

import pytest

# 从实现文件导入 feature flag，保持同步
from app.retrieval.structured_similarity import (
    RETRIEVAL_STRUCTURED_SIMILARITY_ENABLED,
    StructuredSimilarityScore,
    StructuredSimilarityScorer,
    is_structured_similarity_enabled,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_query_structured_suggestions() -> dict:
    """构造查询侧结构化画像。"""
    return {
        "suggested_problem_type": "客户投诉",
        "suggested_root_cause_category": "服务态度",
        "suggested_applicable_scenes": ["零售", "餐饮"],
        "suggested_tags": ["投诉", "服务"],
    }


def _make_candidate_snapshot(
    case_id: str = "case-001",
    has_suggestions: bool = True,
) -> dict:
    """构造候选快照。"""
    base = {
        "case_id": case_id,
        "vector_id": "vec-001",
        "vector_similarity_score": 0.85,
        "brand_id": "brand-001",
        "problem_type": "客户投诉",
        "case_updated_at": "2024-01-15T10:00:00Z",
    }
    if has_suggestions:
        base["structured_suggestions"] = {
            "problem_type": "客户投诉",
            "root_cause_category": "服务态度",
            "applicable_scenes": ["零售"],
            "tags": ["投诉", "服务"],
        }
    return base


# ---------------------------------------------------------------------------
# Tests: Feature Flag Gate
# ---------------------------------------------------------------------------


class TestStructuredSimilarityFeatureFlag:
    """Feature Flag Protocol: flag=OFF 时测试应失败或跳过。"""

    def test_feature_flag_default_disabled(self):
        """RED 阶段：flag 默认为 False（实现未完成）。"""
        assert RETRIEVAL_STRUCTURED_SIMILARITY_ENABLED is False

    def test_is_structured_similarity_enabled_returns_correct_value(self):
        """is_structured_similarity_enabled 返回 flag 当前值。"""
        assert is_structured_similarity_enabled() == RETRIEVAL_STRUCTURED_SIMILARITY_ENABLED


# ---------------------------------------------------------------------------
# Tests: MVP Skipped 路径
# ---------------------------------------------------------------------------


class TestStructuredSimilarityMVPSkipped:
    """MVP 版本：所有候选返回 status="skipped"。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._scorer = StructuredSimilarityScorer()

    def test_score_returns_skipped_for_empty_candidates(self):
        """空候选列表返回空列表。"""
        query = _make_query_structured_suggestions()
        result = self._scorer.score(query, [])
        assert result == []

    def test_score_returns_skipped_status_for_all_candidates(self):
        """所有候选返回 status="skipped"。"""
        query = _make_query_structured_suggestions()
        candidates = [
            _make_candidate_snapshot("case-001"),
            _make_candidate_snapshot("case-002"),
            _make_candidate_snapshot("case-003"),
        ]
        result = self._scorer.score(query, candidates)

        assert len(result) == 3
        for score in result:
            assert score.status == "skipped"
            assert score.score is None  # MVP: skipped

    def test_score_returns_skipped_even_when_candidate_has_suggestions(self):
        """即使候选有 structured_suggestions，也返回 skipped（MVP）。"""
        query = _make_query_structured_suggestions()
        candidates = [
            _make_candidate_snapshot("case-001", has_suggestions=True),
        ]
        result = self._scorer.score(query, candidates)

        assert len(result) == 1
        assert result[0].status == "skipped"
        assert result[0].score is None
        # metadata 验证
        assert "reason" in result[0].metadata
        assert "MVP" in result[0].metadata["reason"]

    def test_score_preserves_case_id_order(self):
        """返回结果顺序与候选顺序一致。"""
        query = _make_query_structured_suggestions()
        candidates = [
            _make_candidate_snapshot("case-A"),
            _make_candidate_snapshot("case-B"),
            _make_candidate_snapshot("case-C"),
        ]
        result = self._scorer.score(query, candidates)

        assert len(result) == 3
        assert result[0].case_id == "case-A"
        assert result[1].case_id == "case-B"
        assert result[2].case_id == "case-C"

    def test_score_includes_factors_metadata(self):
        """返回结果包含 factors 和 metadata 字段。"""
        query = _make_query_structured_suggestions()
        candidates = [_make_candidate_snapshot("case-001")]
        result = self._scorer.score(query, candidates)

        assert len(result) == 1
        score = result[0]
        assert isinstance(score.factors, dict)
        assert "problem_type" in score.factors
        assert "root_cause" in score.factors
        assert "scenes" in score.factors
        assert "tags" in score.factors
        assert isinstance(score.metadata, dict)
        assert "reason" in score.metadata


# ---------------------------------------------------------------------------
# Tests: Future Implementation Helper Methods
# ---------------------------------------------------------------------------


class TestStructuredSimilarityHelpers:
    """未来实现辅助方法的单元测试（MVP 不使用但需预留）。"""

    def setup_method(self):
        """每个测试前创建评分器实例。"""
        self._scorer = StructuredSimilarityScorer()

    def test_compute_exact_match_returns_one_for_same_value(self):
        """精确匹配：相同值返回 1.0。"""
        score = self._scorer._compute_exact_match("客户投诉", "客户投诉")
        assert score == 1.0

    def test_compute_exact_match_returns_zero_for_different_value(self):
        """精确匹配：不同值返回 0.0。"""
        score = self._scorer._compute_exact_match("客户投诉", "商品损坏")
        assert score == 0.0

    def test_compute_exact_match_returns_zero_for_none_value(self):
        """精确匹配：任一值为 None 返回 0.0。"""
        score = self._scorer._compute_exact_match(None, "客户投诉")
        assert score == 0.0
        score = self._scorer._compute_exact_match("客户投诉", None)
        assert score == 0.0
        score = self._scorer._compute_exact_match(None, None)
        assert score == 0.0

    def test_compute_list_overlap_returns_one_for_identical_lists(self):
        """列表重叠：相同列表返回 1.0（Jaccard index）。"""
        score = self._scorer._compute_list_overlap(
            ["投诉", "服务"],
            ["投诉", "服务"],
        )
        assert score == 1.0

    def test_compute_list_overlap_returns_zero_for_disjoint_lists(self):
        """列表重叠：无重叠列表返回 0.0。"""
        score = self._scorer._compute_list_overlap(
            ["投诉", "服务"],
            ["商品", "质量"],
        )
        assert score == 0.0

    def test_compute_list_overlap_returns_partial_overlap(self):
        """列表重叠：部分重叠返回部分分数。"""
        score = self._scorer._compute_list_overlap(
            ["投诉", "服务"],
            ["服务", "质量"],
        )
        # intersection = {"服务"}, union = {"投诉", "服务", "质量"}, Jaccard = 1/3
        assert 0.3 < score < 0.4

    def test_compute_list_overlap_returns_zero_for_empty_list(self):
        """列表重叠：任一列表为空返回 0.0。"""
        score = self._scorer._compute_list_overlap([], ["投诉"])
        assert score == 0.0
        score = self._scorer._compute_list_overlap(["投诉"], [])
        assert score == 0.0
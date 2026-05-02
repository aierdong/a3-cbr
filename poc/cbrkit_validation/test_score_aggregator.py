"""
ScoreAggregator 完整测试套件

验证：
1. 归一化正确性
2. 缺失分项重加权
3. 并列打破
4. 边界情况处理
"""

import pytest
from score_aggregator_implementation import (
    ScoreAggregator,
    ScoredCandidate,
    AggregatedCandidate,
)


class TestScoreAggregator:
    """ScoreAggregator 测试套件"""

    @pytest.fixture
    def aggregator(self):
        """标准聚合器实例"""
        return ScoreAggregator(default_weights={
            'vector': 0.3,
            'semantic': 0.4,
            'structured': 0.1,
            'business': 0.2
        })

    def test_basic_aggregation_all_scores_present(self, aggregator):
        """测试：所有分值都存在时的基本聚合"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.9,
                semantic_score=0.8,
                structured_score=0.7,
                business_score=0.6
            ),
        ]

        results = aggregator.aggregate(candidates)

        assert len(results) == 1
        result = results[0]

        # 验证归一化（单个候选，min == max，归一化为 1.0）
        assert result.normalized_scores['vector'] == 1.0
        assert result.normalized_scores['semantic'] == 1.0
        assert result.normalized_scores['structured'] == 1.0
        assert result.normalized_scores['business'] == 1.0

        # 验证权重（所有分项都有，权重不变）
        assert result.effective_weights['vector'] == 0.3
        assert result.effective_weights['semantic'] == 0.4
        assert result.effective_weights['structured'] == 0.1
        assert result.effective_weights['business'] == 0.2

        # 验证最终分值（所有归一化分值为 1.0，加权和为 1.0）
        assert result.final_score == 1.0
        assert result.final_score_source == "aggregated"

    def test_normalization_with_multiple_candidates(self, aggregator):
        """测试：多个候选的归一化"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.9,  # max
                semantic_score=0.6,  # min
                structured_score=0.8,
                business_score=0.7
            ),
            ScoredCandidate(
                case_id='case_2',
                vector_score=0.5,  # min
                semantic_score=1.0,  # max
                structured_score=0.6,
                business_score=0.9
            ),
        ]

        results = aggregator.aggregate(candidates)

        # case_1 的归一化
        case_1 = next(r for r in results if r.case_id == 'case_1')
        assert case_1.normalized_scores['vector'] == pytest.approx(1.0)  # (0.9 - 0.5) / (0.9 - 0.5)
        assert case_1.normalized_scores['semantic'] == pytest.approx(0.0)  # (0.6 - 0.6) / (1.0 - 0.6)

        # case_2 的归一化
        case_2 = next(r for r in results if r.case_id == 'case_2')
        assert case_2.normalized_scores['vector'] == pytest.approx(0.0)  # (0.5 - 0.5) / (0.9 - 0.5)
        assert case_2.normalized_scores['semantic'] == pytest.approx(1.0)  # (1.0 - 0.6) / (1.0 - 0.6)

    def test_missing_score_reweighting(self, aggregator):
        """测试：缺失分项的重加权"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.9,
                semantic_score=None,  # 缺失
                structured_score=None,  # 缺失
                business_score=0.8
            ),
        ]

        results = aggregator.aggregate(candidates)
        result = results[0]

        # 验证只有 vector 和 business 的归一化分值
        assert 'vector' in result.normalized_scores
        assert 'business' in result.normalized_scores
        assert 'semantic' not in result.normalized_scores
        assert 'structured' not in result.normalized_scores

        # 验证重加权：w'_vector = 0.3 / (0.3 + 0.2) = 0.6
        #            w'_business = 0.2 / (0.3 + 0.2) = 0.4
        assert result.effective_weights['vector'] == pytest.approx(0.6)
        assert result.effective_weights['business'] == pytest.approx(0.4)
        assert 'semantic' not in result.effective_weights
        assert 'structured' not in result.effective_weights

    def test_all_scores_missing(self, aggregator):
        """测试：所有分项都缺失（边界情况）"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.9,  # vector 是必有的
                semantic_score=None,
                structured_score=None,
                business_score=None
            ),
        ]

        results = aggregator.aggregate(candidates)
        result = results[0]

        # vector 分值应该存在
        assert 'vector' in result.normalized_scores
        assert result.effective_weights['vector'] == 1.0  # 只有 vector，权重为 1.0

    def test_tiebreak_by_semantic_score(self, aggregator):
        """测试：final_score 相同时，按 semantic_score 打破并列"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.8,
                semantic_score=0.6,  # 较低
                structured_score=0.7,
                business_score=0.7
            ),
            ScoredCandidate(
                case_id='case_2',
                vector_score=0.8,
                semantic_score=0.9,  # 较高
                structured_score=0.7,
                business_score=0.7
            ),
        ]

        results = aggregator.aggregate(candidates)

        # case_2 应该排在前面（semantic_score 更高）
        assert results[0].case_id == 'case_2'
        assert results[1].case_id == 'case_1'

    def test_tiebreak_by_updated_at(self, aggregator):
        """测试：所有分值相同时，按 updated_at 打破并列"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at='2026-04-10T10:00:00Z'  # 较旧
            ),
            ScoredCandidate(
                case_id='case_2',
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at='2026-04-20T10:00:00Z'  # 较新
            ),
        ]

        results = aggregator.aggregate(candidates)

        # case_2 应该排在前面（更新时间更新）
        assert results[0].case_id == 'case_2'
        assert results[1].case_id == 'case_1'

    def test_tiebreak_by_case_id(self, aggregator):
        """测试：所有条件相同时，按 case_id 字典序打破并列"""
        candidates = [
            ScoredCandidate(
                case_id='case_b',
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at='2026-04-10T10:00:00Z'
            ),
            ScoredCandidate(
                case_id='case_a',
                vector_score=0.8,
                semantic_score=0.8,
                structured_score=0.8,
                business_score=0.8,
                case_updated_at='2026-04-10T10:00:00Z'
            ),
        ]

        results = aggregator.aggregate(candidates)

        # case_a 应该排在前面（字典序）
        assert results[0].case_id == 'case_a'
        assert results[1].case_id == 'case_b'

    def test_custom_weights(self, aggregator):
        """测试：自定义权重覆盖默认权重"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.9,
                semantic_score=0.8,
                structured_score=0.7,
                business_score=0.6
            ),
        ]

        custom_weights = {
            'vector': 0.5,
            'semantic': 0.3,
            'structured': 0.1,
            'business': 0.1
        }

        results = aggregator.aggregate(candidates, weights=custom_weights)
        result = results[0]

        # 验证使用了自定义权重
        assert result.effective_weights['vector'] == 0.5
        assert result.effective_weights['semantic'] == 0.3
        assert result.effective_weights['structured'] == 0.1
        assert result.effective_weights['business'] == 0.1

    def test_invalid_weights_sum_not_one(self):
        """测试：权重和不为 1.0 时抛出异常"""
        with pytest.raises(ValueError, match="权重和必须为 1.0"):
            ScoreAggregator(default_weights={
                'vector': 0.3,
                'semantic': 0.4,
                'structured': 0.1,
                'business': 0.1  # 总和 0.9，不是 1.0
            })

    def test_invalid_weights_out_of_range(self):
        """测试：权重超出 [0, 1] 范围时抛出异常"""
        with pytest.raises(ValueError, match="必须在 \\[0, 1\\] 范围内"):
            ScoreAggregator(default_weights={
                'vector': 0.3,
                'semantic': 0.4,
                'structured': 0.1,
                'business': 1.2  # 超出范围
            })

    def test_empty_candidates(self, aggregator):
        """测试：空候选列表"""
        results = aggregator.aggregate([])
        assert results == []

    def test_score_breakdown_preserved(self, aggregator):
        """测试：原始分值被保留在 score_breakdown 中"""
        candidates = [
            ScoredCandidate(
                case_id='case_1',
                vector_score=0.95,
                semantic_score=0.88,
                structured_score=0.75,
                business_score=0.82
            ),
        ]

        results = aggregator.aggregate(candidates)
        result = results[0]

        # 验证原始分值被保留
        assert result.score_breakdown['vector'] == 0.95
        assert result.score_breakdown['semantic'] == 0.88
        assert result.score_breakdown['structured'] == 0.75
        assert result.score_breakdown['business'] == 0.82

    def test_realistic_scenario(self, aggregator):
        """测试：真实场景（多个候选，部分缺失分项）"""
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

        results = aggregator.aggregate(candidates)

        # 验证返回 3 个结果
        assert len(results) == 3

        # 验证所有结果都有 final_score
        for result in results:
            assert result.final_score >= 0.0
            assert result.final_score <= 1.0
            assert result.final_score_source == "aggregated"

        # 验证排序（final_score 降序）
        for i in range(len(results) - 1):
            assert results[i].final_score >= results[i + 1].final_score

        # 验证缺失分项的重加权
        case_2 = next(r for r in results if r.case_id == 'case_2')
        assert 'structured' not in case_2.normalized_scores
        assert 'structured' not in case_2.effective_weights
        # case_2 的有效权重应该重新归一化
        assert sum(case_2.effective_weights.values()) == pytest.approx(1.0)

        case_3 = next(r for r in results if r.case_id == 'case_3')
        assert 'semantic' not in case_3.normalized_scores
        assert 'semantic' not in case_3.effective_weights
        # case_3 的有效权重应该重新归一化
        assert sum(case_3.effective_weights.values()) == pytest.approx(1.0)


# ============================================================================
# 运行测试
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

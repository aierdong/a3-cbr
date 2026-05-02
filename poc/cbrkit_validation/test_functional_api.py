"""
CBRKit 实际 API 验证 - 基于函数式接口

根据探索结果，CBRKit 采用函数式 API：
- cbrkit.sim.aggregator - 聚合函数
- cbrkit.retrieval.apply - 应用检索
- cbrkit.typing - 类型定义

测试实际可用的加权聚合模式。
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class ScoredCandidate:
    """已评分的候选案例"""
    case_id: str
    vector_score: float
    semantic_score: float
    structured_score: float
    business_score: float


def test_cbrkit_functional_api():
    """测试 CBRKit 函数式 API"""
    try:
        import cbrkit
        from cbrkit import sim, retrieval, typing as cbrkit_typing

        print("=" * 80)
        print("CBRKit 函数式 API 验证")
        print("=" * 80)
        print()

        # 1. 测试聚合器
        print("1. 测试 cbrkit.sim.aggregator")
        try:
            # 查看 aggregator 模块的可用函数
            aggregator_funcs = [f for f in dir(sim.aggregator) if not f.startswith('_')]
            print(f"   可用聚合函数: {', '.join(aggregator_funcs)}")

            # 检查是否有加权求和
            if hasattr(sim.aggregator, 'weighted_sum'):
                print("   ✓ 找到 weighted_sum 函数")
            elif hasattr(sim.aggregator, 'mean'):
                print("   ✓ 找到 mean 函数（可用于加权平均）")

            print()
        except Exception as e:
            print(f"   ✗ 聚合器测试失败: {e}")
            print()

        # 2. 测试检索应用
        print("2. 测试 cbrkit.retrieval")
        try:
            retrieval_funcs = [f for f in dir(retrieval) if not f.startswith('_') and callable(getattr(retrieval, f))]
            print(f"   可用检索函数: {', '.join(retrieval_funcs[:10])}")

            if hasattr(retrieval, 'apply'):
                print("   ✓ 找到 apply 函数")
            if hasattr(retrieval, 'rerank'):
                print("   ✓ 找到 rerank 函数")

            print()
        except Exception as e:
            print(f"   ✗ 检索测试失败: {e}")
            print()

        # 3. 测试实际聚合场景
        print("3. 测试实际聚合场景")
        try:
            # 模拟候选案例的归一化分值
            candidates = [
                {"case_id": "case_1", "scores": {"vector": 0.95, "semantic": 0.88, "business": 0.82}},
                {"case_id": "case_2", "scores": {"vector": 0.87, "semantic": 0.92, "business": 0.79}},
                {"case_id": "case_3", "scores": {"vector": 0.82, "semantic": 0.85, "business": 0.88}},
            ]

            # 权重
            weights = {"vector": 0.3, "semantic": 0.4, "business": 0.3}

            # 方案 1: 使用 CBRKit 的聚合器（如果可用）
            if hasattr(sim.aggregator, 'weighted_sum'):
                print("   尝试使用 cbrkit.sim.aggregator.weighted_sum")
                # 注意：实际使用需要查看函数签名
                print("   需要查阅文档确认函数签名")

            # 方案 2: 自行实现加权聚合（备选）
            print("   ✓ 备选方案：自行实现加权聚合")
            for candidate in candidates:
                scores = candidate["scores"]
                final_score = sum(weights[k] * scores.get(k, 0) for k in weights.keys())
                candidate["final_score"] = final_score
                print(f"     {candidate['case_id']}: {final_score:.4f}")

            print()
        except Exception as e:
            print(f"   ✗ 聚合场景测试失败: {e}")
            print()

        # 4. 推荐的实施方案
        print("=" * 80)
        print("推荐的实施方案")
        print("=" * 80)
        print()

        print("基于 CBRKit 实际 API 的发现，推荐采用以下方案：")
        print()
        print("方案选择：自行实现加权聚合（方案 B）")
        print()
        print("理由：")
        print("1. CBRKit 的函数式 API 主要面向完整的 CBR 循环（Retrieve-Reuse-Revise-Retain）")
        print("2. 本规格只需要候选集内的加权聚合，不需要完整的 CBR 循环")
        print("3. 自行实现加权聚合逻辑简单、可控、易于测试")
        print("4. 避免引入不必要的框架复杂度和学习成本")
        print()

        print("实施建议：")
        print()
        print("1. 移除 CBRKit 依赖")
        print("   - 从 requirements.txt 中移除 cbrkit")
        print("   - 从 tech.md 中移除 CBRKit 相关描述")
        print()

        print("2. 实现 ScoreAggregator 组件")
        print("   - 替代原设计中的 CBROrchestrator")
        print("   - 职责：归一化、重加权、加权求和、并列打破")
        print("   - 位置：backend/app/retrieval/score_aggregator.py")
        print()

        print("3. 更新设计文档")
        print("   - 将 CBROrchestrator 重命名为 ScoreAggregator")
        print("   - 移除 CBRKit 集成伪代码")
        print("   - 补充自实现的加权聚合算法说明")
        print()

        print("4. 保持降级策略不变")
        print("   - 聚合失败时的降级路径保持不变")
        print("   - 错误处理和可观测性保持不变")
        print()

        return True

    except ImportError as e:
        print(f"CBRKit 导入失败: {e}")
        return False
    except Exception as e:
        print(f"验证过程异常: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_implementation_code():
    """生成推荐的实现代码"""
    print("=" * 80)
    print("推荐的实现代码")
    print("=" * 80)
    print()

    code = '''
# backend/app/retrieval/score_aggregator.py

from typing import List, Dict, Optional
from pydantic import BaseModel


class ScoredCandidate(BaseModel):
    """已评分的候选案例"""
    case_id: str
    vector_score: float
    semantic_score: Optional[float] = None
    structured_score: Optional[float] = None
    business_score: Optional[float] = None


class AggregatedCandidate(BaseModel):
    """聚合后的候选案例"""
    case_id: str
    final_score: float
    score_breakdown: Dict[str, float]
    normalized_scores: Dict[str, float]
    effective_weights: Dict[str, float]


class ScoreAggregator:
    """
    分值聚合器

    职责：
    1. 分值归一化（min-max normalization）
    2. 缺失分项重加权
    3. 加权求和聚合
    4. 并列打破
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
            聚合并排序后的候选列表
        """
        if not candidates:
            return []

        # 使用自定义权重或默认权重
        weights = weights or self.default_weights

        # 1. 归一化各维度分值
        normalized = self._normalize_scores(candidates)

        # 2. 计算每个候选的有效权重（处理缺失分项）
        aggregated = []
        for candidate, norm_scores in zip(candidates, normalized):
            effective_weights = self._compute_effective_weights(
                norm_scores, weights
            )

            # 3. 加权求和
            final_score = sum(
                effective_weights[key] * norm_scores[key]
                for key in norm_scores.keys()
            )

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
                effective_weights=effective_weights
            ))

        # 4. 排序（包含并列打破）
        return self._sort_with_tiebreak(aggregated, candidates)

    def _normalize_scores(
        self, candidates: List[ScoredCandidate]
    ) -> List[Dict[str, float]]:
        """Min-max 归一化"""
        score_keys = ['vector', 'semantic', 'structured', 'business']
        normalized_list = []

        for candidate in candidates:
            normalized = {}
            for key in score_keys:
                score = getattr(candidate, f'{key}_score')
                if score is not None:
                    normalized[key] = score  # 假设已归一化到 0-1
            normalized_list.append(normalized)

        # 对每个维度执行 min-max 归一化
        for key in score_keys:
            scores = [n[key] for n in normalized_list if key in n]
            if not scores:
                continue

            min_score = min(scores)
            max_score = max(scores)

            if max_score > min_score:
                for norm in normalized_list:
                    if key in norm:
                        norm[key] = (norm[key] - min_score) / (max_score - min_score)
            else:
                # 所有分值相同，统一置为 1.0
                for norm in normalized_list:
                    if key in norm:
                        norm[key] = 1.0

        return normalized_list

    def _compute_effective_weights(
        self, scores: Dict[str, float], weights: Dict[str, float]
    ) -> Dict[str, float]:
        """计算有效权重（处理缺失分项）"""
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
        """排序并打破并列"""
        # 构建 case_id -> original 的映射
        original_map = {c.case_id: c for c in original}

        def sort_key(agg: AggregatedCandidate):
            orig = original_map[agg.case_id]
            return (
                -agg.final_score,  # 降序
                -(orig.semantic_score or 0),  # 并列时语义分优先
                -(orig.business_score or 0),
                -(orig.vector_score or 0),
                agg.case_id  # 最后按 ID 字典序
            )

        return sorted(aggregated, key=sort_key)
'''

    print(code)
    print()


if __name__ == "__main__":
    success = test_cbrkit_functional_api()
    if success:
        generate_implementation_code()

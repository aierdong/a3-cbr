"""StructuredSimilarityScorer：基于结构化派生结果计算局部相似度。

基于 NormalizedRetrievalQuery.query_structured_suggestions 与候选
CaseEnrichmentResult.structured_suggestions 计算问题类型、根因分类、
适用场景和标签的局部相似度。

MVP 策略：评分标记为 skipped，同时 LLM normalizer 仍须生成
query_structured_suggestions 并写入 NormalizedRetrievalQuery。
业务理由：结构化局部相似度尚未经 PoC 校验，生产效果不定；
MVP 先落地字段与数据，暂不纳入聚合，便于线上观察质量。

设计约束：
- MVP 将结构化分标记为 skipped，但 schema、运行记录和响应必须预留
- 不生成 embedding，不改变候选集合，只输出可解释的局部相似度明细

Boundary: StructuredSimilarityScorer
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# =============================================================================
# Feature Flag: 全局启用开关
# =============================================================================
# TDD Protocol: RED 阶段 flag=False（实现未完成），GREEN 阶段 flag=True（实现完成）
RETRIEVAL_STRUCTURED_SIMILARITY_ENABLED = False


def is_structured_similarity_enabled() -> bool:
    """检查 StructuredSimilarityScorer 功能是否启用。"""
    return RETRIEVAL_STRUCTURED_SIMILARITY_ENABLED


# =============================================================================
# 结构化局部相似度评分结果
# =============================================================================


@dataclass
class StructuredSimilarityScore:
    """结构化局部相似度评分结果。

    包含结构化分值、状态、贡献因子明细和计算元数据。
    MVP 版本所有候选的结构化分均标记为 skipped。
    """

    case_id: str
    score: Optional[float]  # None 表示 skipped 或不可用
    status: str  # "skipped" | "computed"
    factors: dict[str, float]  # 各维度贡献因子：problem_type, root_cause, scenes, tags
    metadata: dict[str, object]  # 计算元数据：匹配详情、计算耗时等


# =============================================================================
# StructuredSimilarityScorer
# =============================================================================


class StructuredSimilarityScorer:
    """结构化局部相似度评分器。

    职责：
    1. 基于 query_structured_suggestions 与候选 structured_suggestions 计算局部相似度
    2. 支持问题类型、根因分类、适用场景和标签四个维度的匹配
    3. MVP 将所有评分标记为 skipped，但预留 schema、运行记录和响应字段

    输入：
    - NormalizedRetrievalQuery.query_structured_suggestions（查询侧结构化画像）
    - CandidateSnapshot.structured_suggestions（候选侧结构化建议）

    输出：
    - list[StructuredSimilarityScore]，与输入候选顺序一致
    """

    def score(
        self,
        query_structured_suggestions: dict,
        candidate_snapshots: list[dict],
    ) -> list[StructuredSimilarityScore]:
        """计算候选案例的结构化局部相似度。

        MVP 版本返回所有候选的结构化分为 skipped。
        未来实现时将计算：
        - 问题类型匹配度
        - 根因分类匹配度
        - 适用场景重叠度
        - 标签重叠度

        Args:
            query_structured_suggestions: 查询侧结构化画像（来自 LLM normalizer）
            candidate_snapshots: 候选快照列表（包含 structured_suggestions 字段）

        Returns:
            结构化相似度评分列表，与候选顺序一致
        """
        if not candidate_snapshots:
            return []

        # MVP: 所有候选的结构化分均标记为 skipped
        # 预留字段但暂不计算，待 PoC 验证后开启
        return [
            StructuredSimilarityScore(
                case_id=snapshot.get("case_id", ""),
                score=None,  # MVP: skipped
                status="skipped",
                factors={
                    "problem_type": 0.0,
                    "root_cause": 0.0,
                    "scenes": 0.0,
                    "tags": 0.0,
                },
                metadata={
                    "reason": "MVP: structured similarity not yet validated",
                    "query_suggestions": query_structured_suggestions,
                    "candidate_has_suggestions": snapshot.get("structured_suggestions") is not None,
                },
            )
            for snapshot in candidate_snapshots
        ]

    def _compute_similarity(
        self,
        query: dict,
        candidate: Optional[dict],
    ) -> tuple[float, dict[str, float]]:
        """计算结构化相似度（未来实现用）。

        计算四个维度的相似度：
        1. 问题类型：精确匹配或语义相似
        2. 根因分类：精确匹配或语义相似
        3. 适用场景：集合重叠度（Jaccard）
        4. 标签：集合重叠度（Jaccard）

        Args:
            query: 查询侧结构化画像
            candidate: 候选侧结构化建议

        Returns:
            (总分, 各维度贡献因子)
        """
        if candidate is None:
            return 0.0, {"problem_type": 0.0, "root_cause": 0.0, "scenes": 0.0, "tags": 0.0}

        factors = {
            "problem_type": self._compute_exact_match(
                query.get("suggested_problem_type"),
                candidate.get("problem_type"),
            ),
            "root_cause": self._compute_exact_match(
                query.get("suggested_root_cause_category"),
                candidate.get("root_cause_category"),
            ),
            "scenes": self._compute_list_overlap(
                query.get("suggested_applicable_scenes") or [],
                candidate.get("applicable_scenes") or [],
            ),
            "tags": self._compute_list_overlap(
                query.get("suggested_tags") or [],
                candidate.get("tags") or [],
            ),
        }

        # 加权求和（各维度权重可配置）
        total = sum(factors.values()) / len(factors)
        return total, factors

    def _compute_exact_match(
        self,
        query_value: Optional[str],
        candidate_value: Optional[str],
    ) -> float:
        """计算精确匹配度。"""
        if not query_value or not candidate_value:
            return 0.0
        return 1.0 if query_value == candidate_value else 0.0

    def _compute_list_overlap(
        self,
        query_list: list[str],
        candidate_list: list[str],
    ) -> float:
        """计算集合重叠度（Jaccard index）。"""
        if not query_list or not candidate_list:
            return 0.0
        query_set = set(query_list)
        candidate_set = set(candidate_list)
        intersection = len(query_set & candidate_set)
        union = len(query_set | candidate_set)
        return intersection / union if union > 0 else 0.0
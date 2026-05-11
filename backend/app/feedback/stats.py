"""反馈基础统计（只读聚合）。"""

from typing import Literal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feedback.models import RecommendationFeedback
from app.feedback.schemas import (
    FeedbackStatsGroupBy,
    FeedbackStatsGroupRow,
    FeedbackStatsQuery,
    FeedbackStatsResponse,
)


def _time_and_dimension_conditions(query: FeedbackStatsQuery) -> list:
    conditions = []
    if query.recommendation_run_id is not None:
        conditions.append(
            RecommendationFeedback.recommendation_run_id == query.recommendation_run_id,
        )
    if query.case_id is not None:
        conditions.append(RecommendationFeedback.case_id == query.case_id)
    if query.created_at_from is not None:
        conditions.append(RecommendationFeedback.created_at >= query.created_at_from)
    if query.created_at_to is not None:
        conditions.append(RecommendationFeedback.created_at <= query.created_at_to)
    return conditions


def _rates_row(
    *,
    total: int,
    useful: int,
    not_useful: int,
    unknown: int,
    dimension: Literal["none", "recommendation_run", "case"],
    recommendation_run_id: str | None,
    case_id: str | None,
) -> FeedbackStatsGroupRow:
    useful_rate = useful / total if total else 0.0
    not_useful_rate = not_useful / total if total else 0.0
    unknown_rate = unknown / total if total else 0.0
    return FeedbackStatsGroupRow(
        dimension=dimension,
        recommendation_run_id=recommendation_run_id,
        case_id=case_id,
        total_count=total,
        useful_count=useful,
        not_useful_count=not_useful,
        unknown_count=unknown,
        useful_rate=useful_rate,
        not_useful_rate=not_useful_rate,
        unknown_rate=unknown_rate,
    )


class FeedbackStatsService:
    """基于反馈表计算数量、有用率与有用性分布。"""

    def __init__(self, db: AsyncSession) -> None:
        """初始化统计服务。

        Args:
            db: 异步数据库会话。
        """
        self._db = db

    async def summarize(self, query: FeedbackStatsQuery) -> FeedbackStatsResponse:
        """返回总体统计及可选分组聚合。"""
        conditions = _time_and_dimension_conditions(query)

        base = select(
            func.count().label("total"),
            func.coalesce(
                func.sum(case((RecommendationFeedback.usefulness == "useful", 1), else_=0)),
                0,
            ).label("useful"),
            func.coalesce(
                func.sum(
                    case((RecommendationFeedback.usefulness == "not_useful", 1), else_=0),
                ),
                0,
            ).label("not_useful"),
            func.coalesce(
                func.sum(case((RecommendationFeedback.usefulness == "unknown", 1), else_=0)),
                0,
            ).label("unknown"),
        ).select_from(RecommendationFeedback)
        if conditions:
            base = base.where(*conditions)

        result = await self._db.execute(base)
        row = result.one()
        total = int(row.total or 0)
        useful = int(row.useful or 0)
        not_useful = int(row.not_useful or 0)
        unknown = int(row.unknown or 0)

        overall = _rates_row(
            total=total,
            useful=useful,
            not_useful=not_useful,
            unknown=unknown,
            dimension="none",
            recommendation_run_id=None,
            case_id=None,
        )

        groups: list[FeedbackStatsGroupRow] = []
        if query.group_by == FeedbackStatsGroupBy.RECOMMENDATION_RUN:
            g_stmt = select(
                RecommendationFeedback.recommendation_run_id.label("rid"),
                func.count().label("total"),
                func.coalesce(
                    func.sum(
                        case((RecommendationFeedback.usefulness == "useful", 1), else_=0),
                    ),
                    0,
                ).label("useful"),
                func.coalesce(
                    func.sum(
                        case(
                            (RecommendationFeedback.usefulness == "not_useful", 1),
                            else_=0,
                        ),
                    ),
                    0,
                ).label("not_useful"),
                func.coalesce(
                    func.sum(
                        case((RecommendationFeedback.usefulness == "unknown", 1), else_=0),
                    ),
                    0,
                ).label("unknown"),
            ).group_by(RecommendationFeedback.recommendation_run_id)
            if conditions:
                g_stmt = g_stmt.where(*conditions)
            g_res = await self._db.execute(g_stmt)
            for gr in g_res.all():
                rid = gr.rid
                groups.append(
                    _rates_row(
                        total=int(gr.total or 0),
                        useful=int(gr.useful or 0),
                        not_useful=int(gr.not_useful or 0),
                        unknown=int(gr.unknown or 0),
                        dimension="recommendation_run",
                        recommendation_run_id=rid,
                        case_id=None,
                    ),
                )

        if query.group_by == FeedbackStatsGroupBy.CASE:
            g_stmt = (
                select(
                    RecommendationFeedback.case_id.label("cid"),
                    func.count().label("total"),
                    func.coalesce(
                        func.sum(
                            case((RecommendationFeedback.usefulness == "useful", 1), else_=0),
                        ),
                        0,
                    ).label("useful"),
                    func.coalesce(
                        func.sum(
                            case(
                                (RecommendationFeedback.usefulness == "not_useful", 1),
                                else_=0,
                            ),
                        ),
                        0,
                    ).label("not_useful"),
                    func.coalesce(
                        func.sum(
                            case((RecommendationFeedback.usefulness == "unknown", 1), else_=0),
                        ),
                        0,
                    ).label("unknown"),
                )
                .where(RecommendationFeedback.case_id.is_not(None))
                .group_by(RecommendationFeedback.case_id)
            )
            if conditions:
                g_stmt = g_stmt.where(*conditions)
            g_res = await self._db.execute(g_stmt)
            for gr in g_res.all():
                cid = gr.cid
                groups.append(
                    _rates_row(
                        total=int(gr.total or 0),
                        useful=int(gr.useful or 0),
                        not_useful=int(gr.not_useful or 0),
                        unknown=int(gr.unknown or 0),
                        dimension="case",
                        recommendation_run_id=None,
                        case_id=cid,
                    ),
                )

        return FeedbackStatsResponse(overall=overall, groups=groups)

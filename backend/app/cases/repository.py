"""案例持久化与过滤查询。

CaseRepository 负责 A3Case 的创建、更新、删除、按 ID 查询和分页查询。
对 StoreInfo 只读：按 store_id 查询是否存在、列表/详情与 store_infos 做关联查询。
不在本 Repository 或案例写入路径中对 store_infos 执行 insert/update/delete。
"""
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cases.models import A3Case, StoreInfo


# =============================================================================
# Data Classes for Repository Layer
# =============================================================================


@dataclass
class StoreInfoRecord:
    """门店信息记录（关联查询返回）。"""

    store_id: str
    store_name: str
    brand_id: str
    brand_name: str
    business_type: str
    store_scale: str
    franchise_type: str
    city: str
    city_tier: str
    updated_at: datetime

    @classmethod
    def from_orm(cls, store: StoreInfo) -> "StoreInfoRecord":
        """从 ORM 模型构建记录。"""
        return cls(
            store_id=store.store_id,
            store_name=store.store_name,
            brand_id=store.brand_id,
            brand_name=store.brand_name,
            business_type=store.business_type,
            store_scale=store.store_scale,
            franchise_type=store.franchise_type,
            city=store.city,
            city_tier=store.city_tier,
            updated_at=store.updated_at,
        )


@dataclass
class A3CaseRecord:
    """案例记录（CRUD 操作返回）。"""

    case_id: str
    problem_description: str
    store_id: str
    problem_type: str
    context: dict[str, Any]
    root_cause: str
    solution_steps: list[dict[str, Any]]
    outcome: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    store: StoreInfoRecord

    @classmethod
    def from_orm(cls, case: A3Case, store: StoreInfo) -> "A3CaseRecord":
        """从 ORM 模型构建记录。"""
        return cls(
            case_id=case.case_id,
            problem_description=case.problem_description,
            store_id=case.store_id,
            problem_type=case.problem_type,
            context=(
                json.loads(case.context)
                if isinstance(case.context, str)
                else case.context
            ),
            root_cause=case.root_cause,
            solution_steps=(
                json.loads(case.solution_steps)
                if isinstance(case.solution_steps, str)
                else case.solution_steps
            ),
            outcome=(
                json.loads(case.outcome)
                if isinstance(case.outcome, str)
                else case.outcome
            ),
            status=case.status,
            created_at=case.created_at,
            updated_at=case.updated_at,
            store=StoreInfoRecord.from_orm(store),
        )


@dataclass
class A3CaseCreateData:
    """创建案例的输入数据。"""

    problem_description: str
    store_id: str
    problem_type: str
    context: dict[str, Any]
    root_cause: str
    solution_steps: list[dict[str, Any]]
    outcome: dict[str, Any]
    status: str = "draft"


@dataclass
class A3CaseUpdateData:
    """更新案例的输入数据（所有字段可选）。"""

    problem_description: Optional[str] = None
    store_id: Optional[str] = None
    problem_type: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    root_cause: Optional[str] = None
    solution_steps: Optional[list[dict[str, Any]]] = None
    outcome: Optional[dict[str, Any]] = None
    status: Optional[str] = None


@dataclass
class CaseListQueryRepo:
    """列表查询参数（Repository 层）。"""

    limit: int = 20
    cursor_created_at: Optional[datetime] = None
    cursor_case_id: Optional[str] = None
    include_archived: bool = False

    # 过滤参数
    brand_id: Optional[str] = None
    store_id: Optional[str] = None
    business_type: Optional[str] = None
    store_scale: Optional[str] = None
    franchise_type: Optional[str] = None
    city: Optional[str] = None
    city_tier: Optional[str] = None
    problem_type: Optional[str] = None
    status: Optional[str] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None


@dataclass
class KeysetPage:
    """Keyset 分页返回结构。"""

    items: list[A3CaseRecord] = field(default_factory=list)
    limit: int = 20
    next_cursor_created_at: Optional[datetime] = None
    next_cursor_case_id: Optional[str] = None
    has_more: bool = False
    sort: str = "created_at desc, case_id desc"


# =============================================================================
# CaseRepository
# =============================================================================


class CaseRepository:
    """案例持久化与过滤查询。"""

    def __init__(self, session: AsyncSession) -> None:
        """初始化仓库。

        Args:
            session: 数据库会话
        """
        self._session = session

    async def _get_store_by_id(self, store_id: str) -> StoreInfo | None:
        """根据 store_id 查询门店信息。"""
        result = await self._session.get(StoreInfo, store_id)
        return result

    async def _ensure_store_exists(self, store_id: str) -> StoreInfo:
        """确保 store_id 对应的门店存在，不存在则抛出 ValueError。"""
        store = await self._get_store_by_id(store_id)
        if store is None:
            raise ValueError(f"store_id '{store_id}' does not exist in store_infos")
        return store

    def _generate_case_id(self) -> str:
        """生成全局唯一案例标识。"""
        return f"case_{uuid.uuid4().hex[:12]}"

    def _now_utc(self) -> datetime:
        """返回当前 UTC 时间。"""
        return datetime.now()

    async def create(self, case_data: A3CaseCreateData) -> A3CaseRecord:
        """创建新案例。

        Args:
            case_data: 创建案例的数据

        Returns:
            A3CaseRecord: 创建的案例记录

        Raises:
            ValueError: store_id 不存在
        """
        # 校验 store_id 存在
        store = await self._ensure_store_exists(case_data.store_id)

        # 生成唯一 ID 和时间戳
        case_id = self._generate_case_id()
        now = self._now_utc()

        # 构建案例记录
        case = A3Case(
            case_id=case_id,
            problem_description=case_data.problem_description,
            store_id=case_data.store_id,
            problem_type=case_data.problem_type,
            context=json.dumps(case_data.context, ensure_ascii=False),
            root_cause=case_data.root_cause,
            solution_steps=json.dumps(case_data.solution_steps, ensure_ascii=False),
            outcome=json.dumps(case_data.outcome, ensure_ascii=False),
            status=case_data.status,
            created_at=now,
            updated_at=now,
        )
        self._session.add(case)
        await self._session.flush()
        await self._session.refresh(case)

        return A3CaseRecord.from_orm(case, store)

    async def update(
        self, case_id: str, changes: A3CaseUpdateData
    ) -> A3CaseRecord | None:
        """更新案例。

        Args:
            case_id: 案例标识
            changes: 更新内容

        Returns:
            A3CaseRecord | None: 更新后的记录，不存在则返回 None

        Raises:
            ValueError: store_id 不存在
        """
        # 查询现有案例
        result = await self._session.execute(
            select(A3Case)
            .options(selectinload(A3Case.store))
            .where(A3Case.case_id == case_id)
        )
        case = result.scalar_one_or_none()
        if case is None:
            return None

        # 如果更新 store_id，校验新 store 存在
        if changes.store_id is not None and changes.store_id != case.store_id:
            store = await self._ensure_store_exists(changes.store_id)
            case.store_id = changes.store_id
            case.store = store
        else:
            store = case.store

        # 应用字段更新
        if changes.problem_description is not None:
            case.problem_description = changes.problem_description
        if changes.problem_type is not None:
            case.problem_type = changes.problem_type
        if changes.context is not None:
            case.context = json.dumps(changes.context, ensure_ascii=False)
        if changes.root_cause is not None:
            case.root_cause = changes.root_cause
        if changes.solution_steps is not None:
            case.solution_steps = json.dumps(changes.solution_steps, ensure_ascii=False)
        if changes.outcome is not None:
            case.outcome = json.dumps(changes.outcome, ensure_ascii=False)
        if changes.status is not None:
            case.status = changes.status

        # 更新时间
        case.updated_at = self._now_utc()

        await self._session.flush()
        await self._session.refresh(case)

        return A3CaseRecord.from_orm(case, store)

    async def delete(self, case_id: str) -> bool:
        """删除案例（物理删除）。

        Args:
            case_id: 案例标识

        Returns:
            bool: 是否成功删除（受影响行数 > 0）
        """
        result = await self._session.execute(
            delete(A3Case).where(A3Case.case_id == case_id)
        )
        await self._session.flush()
        return result.rowcount > 0

    async def get_by_id(self, case_id: str) -> A3CaseRecord | None:
        """按案例标识查询。

        Args:
            case_id: 案例标识

        Returns:
            A3CaseRecord | None: 查询结果，不存在则返回 None
        """
        result = await self._session.execute(
            select(A3Case)
            .options(selectinload(A3Case.store))
            .where(A3Case.case_id == case_id)
        )
        case = result.scalar_one_or_none()
        if case is None:
            return None
        return A3CaseRecord.from_orm(case, case.store)

    async def list(self, query: CaseListQueryRepo) -> KeysetPage:
        """分页查询案例列表。

        Args:
            query: 查询参数

        Returns:
            KeysetPage: 分页结果
        """
        # 构建基础查询
        stmt = select(A3Case).options(selectinload(A3Case.store))

        # 排除归档（默认）
        if not query.include_archived:
            stmt = stmt.where(A3Case.status != "archived")

        # 过滤条件
        conditions: list[Any] = []

        if query.store_id is not None:
            conditions.append(A3Case.store_id == query.store_id)

        if query.problem_type is not None:
            conditions.append(A3Case.problem_type == query.problem_type)

        if query.status is not None:
            conditions.append(A3Case.status == query.status)

        if query.created_after is not None:
            conditions.append(A3Case.created_at >= query.created_after)

        if query.created_before is not None:
            conditions.append(A3Case.created_at <= query.created_before)

        # 门店信息过滤（需要 join store_infos）
        if any(
            f is not None
            for f in [
                query.brand_id,
                query.business_type,
                query.store_scale,
                query.franchise_type,
                query.city,
                query.city_tier,
            ]
        ):
            stmt = stmt.join(StoreInfo, A3Case.store_id == StoreInfo.store_id)

            if query.brand_id is not None:
                conditions.append(StoreInfo.brand_id == query.brand_id)
            if query.business_type is not None:
                conditions.append(StoreInfo.business_type == query.business_type)
            if query.store_scale is not None:
                conditions.append(StoreInfo.store_scale == query.store_scale)
            if query.franchise_type is not None:
                conditions.append(StoreInfo.franchise_type == query.franchise_type)
            if query.city is not None:
                conditions.append(StoreInfo.city == query.city)
            if query.city_tier is not None:
                conditions.append(StoreInfo.city_tier == query.city_tier)

        # 应用过滤条件
        if conditions:
            stmt = stmt.where(and_(*conditions))

        # Keyset 分页游标：稳定排序 created_at desc, case_id desc
        # 当 created_at 相同时，用 case_id 作为 tie-breaker
        if query.cursor_created_at is not None and query.cursor_case_id is not None:
            from sqlalchemy import or_ as sqlalchemy_or
            cursor_cond = sqlalchemy_or(
                A3Case.created_at < query.cursor_created_at,
                and_(
                    A3Case.created_at == query.cursor_created_at,
                    A3Case.case_id < query.cursor_case_id
                )
            )
            stmt = stmt.where(cursor_cond)
        elif query.cursor_created_at is not None:
            stmt = stmt.where(A3Case.created_at < query.cursor_created_at)

        # 稳定排序：created_at desc, case_id desc
        stmt = stmt.order_by(A3Case.created_at.desc(), A3Case.case_id.desc())

        # 多取一条用于判断 has_more
        limit = query.limit + 1
        stmt = stmt.limit(limit)

        result = await self._session.execute(stmt)
        cases = result.scalars().all()

        # 判断是否有更多
        has_more = len(cases) > query.limit
        if has_more:
            cases = cases[: query.limit]

        # 构建返回记录
        items = [
            A3CaseRecord.from_orm(case, case.store) for case in cases
        ]

        # 生成下一页游标
        next_cursor_created_at: Optional[datetime] = None
        next_cursor_case_id: Optional[str] = None
        if has_more and items:
            last_item = items[-1]
            next_cursor_created_at = last_item.created_at
            next_cursor_case_id = last_item.case_id

        return KeysetPage(
            items=items,
            limit=query.limit,
            next_cursor_created_at=next_cursor_created_at,
            next_cursor_case_id=next_cursor_case_id,
            has_more=has_more,
            sort="created_at desc, case_id desc",
        )

"""案例业务服务。

编排创建、编辑、删除、详情和列表查询的业务流程。
"""
from datetime import datetime, timezone
from typing import Optional

from app.cases.models import CaseStatus as ModelCaseStatus
from app.cases.repository import (
    A3CaseRecord,
    A3CaseUpdateData,
    CaseListQueryRepo,
    CaseRepository,
)
from app.cases.schemas import (
    CaseDetailResponse,
    CaseListItem,
    CaseListQuery,
    CaseStatus as SchemaCaseStatus,
    CreateCaseRequest,
    DeleteCaseResponse,
    PaginatedCaseListResponse,
    ProblemType as SchemaProblemType,
    StoreInfoSummary,
    UpdateCaseRequest,
)
from app.cases.validators import CaseValidator, FieldError


class CaseValidationError(Exception):
    """案例校验错误。"""

    def __init__(self, errors: list[FieldError]):
        """初始化校验错误。

        Args:
            errors: 字段级错误列表
        """
        self.errors = errors
        super().__init__(str(errors))


class CaseNotFoundError(Exception):
    """案例未找到错误。"""

    def __init__(self, case_id: str):
        """初始化未找到错误。

        Args:
            case_id: 案例标识
        """
        self.case_id = case_id
        super().__init__(f"CASE_NOT_FOUND: case_id '{case_id}' not found")


class CaseStateConflictError(Exception):
    """案例状态冲突错误。"""

    def __init__(self, current_status: str, message: Optional[str] = None):
        """初始化状态冲突错误。

        Args:
            current_status: 当前状态
            message: 可选错误消息
        """
        self.current_status = current_status
        self.message = message or (
            f"CASE_STATE_CONFLICT: case is in '{current_status}' state"
        )
        super().__init__(self.message)


class StoreNotFoundError(Exception):
    """门店不存在错误。"""

    def __init__(self, store_id: str):
        """初始化门店不存在错误。

        Args:
            store_id: 门店标识
        """
        self.store_id = store_id
        super().__init__(
            f"STORE_NOT_FOUND: store_id '{store_id}' not found in store_infos"
        )


# 允许的状态流转映射
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ModelCaseStatus.DRAFT.value: {ModelCaseStatus.ACTIVE.value},
    ModelCaseStatus.ACTIVE.value: {ModelCaseStatus.ARCHIVED.value},
    ModelCaseStatus.ARCHIVED.value: set(),
}


def _record_to_detail_response(record: A3CaseRecord) -> CaseDetailResponse:
    """将案例记录转换为详情响应。"""
    return CaseDetailResponse(
        case_id=record.case_id,
        problem_description=record.problem_description,
        store_id=record.store_id,
        problem_type=SchemaProblemType(record.problem_type)
        if isinstance(record.problem_type, str)
        else record.problem_type,
        context=record.context,
        root_cause=record.root_cause,
        solution_steps=record.solution_steps,
        outcome=record.outcome,
        status=SchemaCaseStatus(record.status)
        if isinstance(record.status, str)
        else record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        store=StoreInfoSummary(
            store_id=record.store.store_id,
            store_name=record.store.store_name,
            brand_id=record.store.brand_id,
            brand_name=record.store.brand_name,
            business_type=record.store.business_type,
            store_scale=record.store.store_scale,
            franchise_type=record.store.franchise_type,
            city=record.store.city,
            city_tier=record.store.city_tier,
            updated_at=record.store.updated_at,
        ),
    )


def _record_to_list_item(record: A3CaseRecord) -> CaseListItem:
    """将案例记录转换为列表项。"""
    return CaseListItem(
        case_id=record.case_id,
        problem_description=record.problem_description,
        store_id=record.store_id,
        problem_type=SchemaProblemType(record.problem_type)
        if isinstance(record.problem_type, str)
        else record.problem_type,
        status=SchemaCaseStatus(record.status)
        if isinstance(record.status, str)
        else record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        store=StoreInfoSummary(
            store_id=record.store.store_id,
            store_name=record.store.store_name,
            brand_id=record.store.brand_id,
            brand_name=record.store.brand_name,
            business_type=record.store.business_type,
            store_scale=record.store.store_scale,
            franchise_type=record.store.franchise_type,
            city=record.store.city,
            city_tier=record.store.city_tier,
            updated_at=record.store.updated_at,
        ),
    )


class CaseService:
    """案例业务服务。

    编排创建、编辑、删除、详情和列表查询的业务流程。

    Responsibilities:
    - 创建时生成稳定 case_id、状态和时间戳
    - 编辑时先加载现有案例，校验状态，再应用允许变更的字段
    - 删除时执行物理删除，支持任意状态的案例
    - 删除不存在的案例返回 CASE_NOT_FOUND
    - 校验失败或状态冲突时保留原案例数据
    - 拒绝把 AI 派生字段写入案例基础模型
    """

    def __init__(self, repository: CaseRepository, validator: CaseValidator) -> None:
        """初始化服务。

        Args:
            repository: 案例仓储实例
            validator: 案例校验器实例
        """
        self._repo = repository
        self._validator = validator

    async def create_case(self, request: CreateCaseRequest) -> CaseDetailResponse:
        """创建新案例。

        创建时生成稳定案例标识、基础状态（draft）和时间戳。
        校验 store_id 在 store_infos 中存在。

        Args:
            request: 创建案例请求

        Returns:
            CaseDetailResponse: 创建的案例详情

        Raises:
            CaseValidationError: 校验失败
            StoreNotFoundError: store_id 不存在
        """
        async def store_exists_check(store_id: str) -> bool:
            """检查 store_id 是否存在的异步函数。"""
            store = await self._repo._get_store_by_id(store_id)
            return store is not None

        errors = self._validator.validate_create(request, store_exists_check)
        if errors:
            raise CaseValidationError(errors)

        # 转换 request 为 repository 可用的数据
        from app.cases.repository import A3CaseCreateData

        def extract_steps(s: UpdateCaseRequest) -> list[dict]:
            """提取步骤数据。"""
            return s.model_dump() if hasattr(s, "model_dump") else s

        create_data = A3CaseCreateData(
            problem_description=request.problem_description,
            store_id=request.store_id,
            problem_type=(
                request.problem_type.value
                if hasattr(request.problem_type, "value")
                else request.problem_type
            ),
            context=(
                request.context.model_dump()
                if hasattr(request.context, "model_dump")
                else request.context
            ),
            root_cause=request.root_cause,
            solution_steps=[extract_steps(s) for s in request.solution_steps],
            outcome=(
                request.outcome.model_dump()
                if hasattr(request.outcome, "model_dump")
                else request.outcome
            ),
        )

        # 调用 repository 创建
        record = await self._repo.create(create_data)

        return _record_to_detail_response(record)

    async def update_case(
        self, case_id: str, request: UpdateCaseRequest
    ) -> CaseDetailResponse:
        """更新案例。

        编辑时先加载现有案例，校验状态，再应用允许变更的字段。
        - 校验案例存在
        - 校验案例状态为 draft 或 active（archived 不可编辑）
        - 校验状态流转是否合法
        - 校验不可变字段（case_id, created_at）未被修改
        - 校验 store_id 存在性（如果提供了新的 store_id）

        Args:
            case_id: 案例标识
            request: 更新案例请求

        Returns:
            CaseDetailResponse: 更新后的案例详情

        Raises:
            CaseNotFoundError: 案例不存在
            CaseStateConflictError: 状态不可编辑或状态流转非法
            CaseValidationError: 校验失败
        """
        # 1. 加载现有案例
        existing = await self._repo.get_by_id(case_id)
        if existing is None:
            raise CaseNotFoundError(case_id)

        current_status = existing.status

        # 2. 校验状态是否可编辑
        if current_status == ModelCaseStatus.ARCHIVED.value:
            raise CaseStateConflictError(
                current_status=current_status,
                message=(
                    f"CASE_STATE_CONFLICT: case is in '{current_status}' "
                    "state and cannot be edited"
                ),
            )

        # 3. 校验状态流转（如果请求修改 status）
        if request.status is not None:
            target_status = (
                request.status.value
                if hasattr(request.status, "value")
                else request.status
            )
            allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())
            if target_status not in allowed:
                raise CaseStateConflictError(
                    current_status=current_status,
                    message=(
                        f"CASE_STATE_CONFLICT: transition from "
                        f"'{current_status}' to '{target_status}' "
                        f"is not allowed. Allowed: {list(allowed) if allowed else 'none'}"
                    ),
                )

        # 4. 使用 validator 校验请求
        async def store_exists_check(store_id: str) -> bool:
            """检查 store_id 是否存在的异步函数。"""
            store = await self._repo._get_store_by_id(store_id)
            return store is not None

        errors = self._validator.validate_update(request, store_exists_check)
        if errors:
            raise CaseValidationError(errors)

        # 5. 构建更新数据
        changes = A3CaseUpdateData()
        if request.problem_description is not None:
            changes.problem_description = request.problem_description
        if request.store_id is not None:
            changes.store_id = request.store_id
        if request.problem_type is not None:
            changes.problem_type = (
                request.problem_type.value
                if hasattr(request.problem_type, "value")
                else request.problem_type
            )
        if request.context is not None:
            changes.context = (
                request.context.model_dump()
                if hasattr(request.context, "model_dump")
                else request.context
            )
        if request.root_cause is not None:
            changes.root_cause = request.root_cause
        if request.solution_steps is not None:
            changes.solution_steps = [
                s.model_dump() if hasattr(s, "model_dump") else s
                for s in request.solution_steps
            ]
        if request.outcome is not None:
            changes.outcome = (
                request.outcome.model_dump()
                if hasattr(request.outcome, "model_dump")
                else request.outcome
            )
        if request.status is not None:
            changes.status = (
                request.status.value
                if hasattr(request.status, "value")
                else request.status
            )

        # 6. 调用 repository 更新
        updated = await self._repo.update(case_id, changes)
        if updated is None:
            raise CaseNotFoundError(case_id)

        return _record_to_detail_response(updated)

    async def delete_case(self, case_id: str) -> DeleteCaseResponse:
        """删除案例。

        执行物理删除，支持任意状态的案例。
        删除不存在的案例返回 CASE_NOT_FOUND。

        Args:
            case_id: 案例标识

        Returns:
            DeleteCaseResponse: 删除响应

        Raises:
            CaseNotFoundError: 案例不存在
        """
        # 执行物理删除
        deleted = await self._repo.delete(case_id)

        if not deleted:
            raise CaseNotFoundError(case_id)

        return DeleteCaseResponse(
            success=True,
            deleted_count=1,
            deleted_at=datetime.now(timezone.utc),
        )

    async def get_case(self, case_id: str) -> CaseDetailResponse:
        """获取案例详情。

        Args:
            case_id: 案例标识

        Returns:
            CaseDetailResponse: 案例详情

        Raises:
            CaseNotFoundError: 案例不存在
        """
        record = await self._repo.get_by_id(case_id)
        if record is None:
            raise CaseNotFoundError(case_id)

        return _record_to_detail_response(record)

    async def list_cases(self, query: CaseListQuery) -> PaginatedCaseListResponse:
        """查询案例列表。

        Args:
            query: 列表查询参数

        Returns:
            PaginatedCaseListResponse: 分页案例列表响应
        """
        # 转换 query 到 repository 层格式
        repo_query = CaseListQueryRepo(
            limit=query.limit,
            cursor_created_at=query.cursor_created_at,
            cursor_case_id=query.cursor_case_id,
            include_archived=query.include_archived,
            brand_id=query.brand_id,
            store_id=query.store_id,
            business_type=query.business_type,
            store_scale=query.store_scale,
            franchise_type=query.franchise_type,
            city=query.city,
            city_tier=query.city_tier,
            problem_type=(
                query.problem_type.value
                if query.problem_type is not None and hasattr(query.problem_type, "value")
                else query.problem_type
            ),
            status=(
                query.status.value
                if query.status is not None and hasattr(query.status, "value")
                else query.status
            ),
            created_after=query.created_after,
            created_before=query.created_before,
        )

        page = await self._repo.list(repo_query)

        return PaginatedCaseListResponse(
            items=[_record_to_list_item(item) for item in page.items],
            limit=page.limit,
            next_cursor_created_at=page.next_cursor_created_at,
            next_cursor_case_id=page.next_cursor_case_id,
            has_more=page.has_more,
            sort=page.sort,
        )
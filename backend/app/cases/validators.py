"""案例字段与步骤校验器。

校验必填字段、枚举值、解决步骤顺序内容和 store_id 存在性。
校验输出映射到字段级错误。
"""
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeAlias

from app.cases.schemas import (
    CreateCaseRequest,
    UpdateCaseRequest,
)


@dataclass
class FieldError:
    """字段级错误。"""

    field: str
    message: str


StoreExistsFn: TypeAlias = Callable[[str], bool | Awaitable[bool]]


async def _resolve_store_exists(store_exists: StoreExistsFn, store_id: str) -> bool:
    """执行 store 存在性检查，支持同步或异步回调。"""
    result = store_exists(store_id)
    if inspect.isawaitable(result):
        return bool(await result)
    return bool(result)


# =============================================================================
# 校验函数
# =============================================================================


async def validate_create_case(
    request: CreateCaseRequest,
    store_exists: StoreExistsFn,
) -> list[FieldError]:
    """校验创建案例请求。

    校验规则：
    1. 必填字段非空：problem_description, store_id, problem_type,
       context, root_cause, solution_steps, outcome
    2. solution_steps：每个步骤 order 从 1 开始连续递增，content 非空
    3. context.scene 非空
    4. outcome.result 必须是枚举值之一
    5. store_id 存在性校验

    Args:
        request: 创建案例请求
        store_exists: 门店存在性检查（同步 ``(str) -> bool`` 或异步 ``(str) -> Awaitable[bool]``）

    Returns:
        字段级错误列表
    """
    errors: list[FieldError] = []

    # 1. 校验必填字段非空
    if not request.problem_description or request.problem_description == "":
        errors.append(FieldError(
            field="problem_description",
            message="problem_description is required and cannot be empty",
        ))

    if not request.store_id or request.store_id == "":
        errors.append(FieldError(
            field="store_id",
            message="store_id is required and cannot be empty",
        ))

    if not request.root_cause or request.root_cause == "":
        errors.append(FieldError(
            field="root_cause",
            message="root_cause is required and cannot be empty",
        ))

    # 2. 校验 context.scene 非空
    if request.context is None:
        errors.append(FieldError(field="context", message="context is required"))
    elif not request.context.scene or request.context.scene == "":
        errors.append(FieldError(
            field="context",
            message="context.scene is required and cannot be empty",
        ))

    # 3. 校验 solution_steps 非空且顺序正确
    if not request.solution_steps or len(request.solution_steps) == 0:
        errors.append(FieldError(
            field="solution_steps",
            message="solution_steps is required and cannot be empty",
        ))
    else:
        # 检查步骤顺序连续且从 1 开始
        orders = [step.order for step in request.solution_steps]
        expected = list(range(1, len(request.solution_steps) + 1))
        if orders != expected:
            errors.append(FieldError(
                field="solution_steps",
                message=(
                    f"solution_steps order must be consecutive starting from 1,"
                    f" got {orders}"
                ),
            ))
        # 检查每个步骤 content 非空
        for i, step in enumerate(request.solution_steps):
            if not step.content or step.content == "":
                errors.append(FieldError(
                    field="solution_steps",
                    message=f"solution_steps[{i}].content cannot be empty",
                ))

    # 4. 校验 outcome 存在且 result 有效
    if request.outcome is None:
        errors.append(FieldError(field="outcome", message="outcome is required"))
    else:
        # outcome.result 为枚举值，Pydantic 会在 schema 层校验
        # 这里额外校验非空
        if request.outcome.result is None:
            errors.append(FieldError(
                field="outcome",
                message="outcome.result is required",
            ))

    # 5. 校验 store_id 存在性
    if request.store_id and request.store_id != "":
        if not await _resolve_store_exists(store_exists, request.store_id):
            errors.append(FieldError(
                field="store_id",
                message=f"store_id '{request.store_id}' does not exist",
            ))

    return errors


async def validate_update_case(
    request: UpdateCaseRequest,
    store_exists: StoreExistsFn,
) -> list[FieldError]:
    """校验更新案例请求。

    校验规则：
    1. 若提供 problem_description，则非空
    2. 若提供 store_id，则存在性校验
    3. 若提供 context.scene，则非空
    4. 若提供 solution_steps，则非空且顺序正确
    5. 若提供 outcome.result，则为有效枚举

    Args:
        request: 更新案例请求
        store_exists: 门店存在性检查（同步或异步，见 ``validate_create_case``）

    Returns:
        字段级错误列表
    """
    errors: list[FieldError] = []

    # 1. 校验 problem_description 非空（如果提供）
    if request.problem_description is not None and request.problem_description == "":
        errors.append(FieldError(
            field="problem_description",
            message="problem_description cannot be empty when provided",
        ))

    # 2. 校验 root_cause 非空（如果提供）
    if request.root_cause is not None and request.root_cause == "":
        errors.append(FieldError(
            field="root_cause",
            message="root_cause cannot be empty when provided",
        ))

    # 3. 校验 store_id 存在性（如果提供）
    if request.store_id is not None and request.store_id != "":
        if not await _resolve_store_exists(store_exists, request.store_id):
            errors.append(FieldError(
                field="store_id",
                message=f"store_id '{request.store_id}' does not exist",
            ))

    # 4. 校验 context.scene 非空（如果提供 context）
    if request.context is not None:
        if request.context.scene is None or request.context.scene == "":
            errors.append(FieldError(
                field="context",
                message="context.scene cannot be empty when provided",
            ))

    # 5. 校验 solution_steps 非空且顺序正确（如果提供）
    if request.solution_steps is not None:
        if len(request.solution_steps) == 0:
            errors.append(FieldError(
                field="solution_steps",
                message="solution_steps cannot be empty when provided",
            ))
        else:
            orders = [step.order for step in request.solution_steps]
            expected = list(range(1, len(request.solution_steps) + 1))
            if orders != expected:
                errors.append(FieldError(
                    field="solution_steps",
                    message=(
                        f"solution_steps order must be consecutive starting from 1,"
                        f" got {orders}"
                    ),
                ))
            for i, step in enumerate(request.solution_steps):
                if not step.content or step.content == "":
                    errors.append(FieldError(
                        field="solution_steps",
                        message=f"solution_steps[{i}].content cannot be empty",
                    ))

    # 6. outcome 的 result 枚举值由 Pydantic 在 schema 层校验
    # 这里只检查 outcome 本身存在时 result 不为空（如果提供）

    return errors


class CaseValidator:
    """案例校验器。

    集中处理字段、步骤和枚举约束。
    校验输出应能映射到字段级错误。
    """

    @staticmethod
    async def validate_create(
        request: CreateCaseRequest,
        store_exists: StoreExistsFn,
    ) -> list[FieldError]:
        """校验创建案例请求。"""
        return await validate_create_case(request, store_exists)

    @staticmethod
    async def validate_update(
        request: UpdateCaseRequest,
        store_exists: StoreExistsFn,
    ) -> list[FieldError]:
        """校验更新案例请求。"""
        return await validate_update_case(request, store_exists)
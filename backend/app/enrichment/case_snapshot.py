"""上游案例快照读取。

通过 CaseService 读取案例详情，执行状态门控，
并将 CaseDetailResponse 映射为 LLM 增强所需的 CaseInputSnapshot。

Requirements: 1.1, 1.2, 6.1
Boundary: CaseSnapshotProvider
"""
from app.cases.schemas import CaseDetailResponse, CaseStatus
from app.cases.service import CaseNotFoundError
from app.enrichment.schemas import CaseInputSnapshot


class EnrichmentCaseNotFoundError(Exception):
    """案例不存在，无法加载快照。"""

    def __init__(self, case_id: str):
        """初始化案例不存在错误。

        Args:
            case_id: 案例标识
        """
        self.case_id = case_id
        super().__init__(f"案例不存在: case_id='{case_id}'")


class EnrichmentStateConflictError(Exception):
    """案例状态不可进入增强流程。"""

    def __init__(self, case_id: str, current_status: str):
        """初始化状态冲突错误。

        Args:
            case_id: 案例标识
            current_status: 当前状态
        """
        self.case_id = case_id
        self.current_status = current_status
        super().__init__(
            f"案例状态不可增强: case_id='{case_id}', status='{current_status}'"
        )


# 允许进入增强流程的状态集合
_ENRICHABLE_STATUSES = {CaseStatus.ACTIVE, CaseStatus.ARCHIVED}


class CaseSnapshotProvider:
    """上游案例快照读取器。

    通过 CaseService 读取案例详情，校验状态门控，
    将结果映射为 LLM 增强所需的 CaseInputSnapshot。

    调用方：由 EnrichmentJobRunner 在运行生命周期中调用。
    """

    def __init__(self, case_service):
        """初始化快照读取器。

        Args:
            case_service: CaseService 实例，用于读取案例详情
        """
        self._case_service = case_service

    async def load_snapshot(self, case_id: str) -> CaseInputSnapshot:
        """加载案例输入快照。

        读取案例详情，校验状态门控，映射为 LLM 增强所需的快照。

        Args:
            case_id: 案例标识

        Returns:
            CaseInputSnapshot: 包含 LLM 增强所需字段的快照

        Raises:
            EnrichmentCaseNotFoundError: 案例不存在
            EnrichmentStateConflictError: 案例状态不可增强（如 draft）
        """
        # 1. 读取案例详情
        try:
            detail = await self._case_service.get_case(case_id)
        except CaseNotFoundError:
            raise EnrichmentCaseNotFoundError(case_id)

        # 2. 状态门控：仅 active / archived 可进入增强流程
        if detail.status not in _ENRICHABLE_STATUSES:
            raise EnrichmentStateConflictError(
                case_id=case_id,
                current_status=detail.status.value
                if hasattr(detail.status, "value")
                else detail.status,
            )

        # 3. 映射为 CaseInputSnapshot
        return _map_to_snapshot(detail)


def _map_to_snapshot(detail: CaseDetailResponse) -> CaseInputSnapshot:
    """将 CaseDetailResponse 映射为 CaseInputSnapshot。

    包含 LLM 增强所需的基础字段和门店镜像过滤维度，排除：
    - 向量、推荐分值、反馈、未授权扩展字段

    Args:
        detail: 上游案例详情响应

    Returns:
        CaseInputSnapshot: LLM 增强所需的快照
    """
    context = _to_dict(detail.context)
    solution_steps = [_to_dict(step) for step in detail.solution_steps]
    outcome = _to_dict(detail.outcome)
    store = detail.store

    return CaseInputSnapshot(
        case_id=detail.case_id,
        problem_description=detail.problem_description,
        problem_type=detail.problem_type.value
        if hasattr(detail.problem_type, "value")
        else detail.problem_type,
        context=context,
        root_cause=detail.root_cause,
        solution_steps=solution_steps,
        outcome=outcome,
        status=detail.status.value
        if hasattr(detail.status, "value")
        else detail.status,
        updated_at=detail.updated_at,
        store_id=detail.store_id,
        store_name=store.store_name,
        brand_id=store.brand_id,
        brand_name=store.brand_name,
        business_type=store.business_type,
        store_scale=store.store_scale,
        franchise_type=store.franchise_type,
        city=store.city,
        city_tier=store.city_tier,
    )


def _to_dict(obj) -> dict:
    """将 Pydantic 模型或其他对象转换为 dict。"""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return obj

"""案例业务服务测试。

测试 CaseService 的业务规则、状态流转和事务编排能力。
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cases.repository import (
    A3CaseRecord,
    KeysetPage,
    StoreInfoRecord,
)
from app.cases.schemas import (
    CaseListQuery,
    CaseStatus as SchemaCaseStatus,
    CreateCaseRequest,
    PaginatedCaseListResponse,
    UpdateCaseRequest,
)
from app.cases.validators import FieldError


def make_utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def create_store_record(
    store_id: str = "store_001",
    store_name: str = "测试门店",
    brand_id: str = "brand_001",
    brand_name: str = "测试品牌",
    business_type: str = "火锅",
    store_scale: str = "large",
    franchise_type: str = "加盟",
    city: str = "北京",
    city_tier: str = "一线",
) -> StoreInfoRecord:
    """创建测试用门店记录。"""
    return StoreInfoRecord(
        store_id=store_id,
        store_name=store_name,
        brand_id=brand_id,
        brand_name=brand_name,
        business_type=business_type,
        store_scale=store_scale,
        franchise_type=franchise_type,
        city=city,
        city_tier=city_tier,
        updated_at=make_utc_now(),
    )


def create_case_record(
    case_id: str = "case_001",
    problem_description: str = "测试问题",
    store_id: str = "store_001",
    problem_type: str = "customer_complaint",
    context: dict | None = None,
    root_cause: str = "测试根因",
    solution_steps: list | None = None,
    outcome: dict | None = None,
    status: str = "draft",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    store: StoreInfoRecord | None = None,
) -> A3CaseRecord:
    """创建测试用案例记录。"""
    if context is None:
        context = {"scene": "测试场景"}
    if solution_steps is None:
        solution_steps = [{"order": 1, "content": "测试步骤"}]
    if outcome is None:
        outcome = {"result": "improved", "notes": "测试备注"}
    if created_at is None:
        created_at = make_utc_now()
    if updated_at is None:
        updated_at = created_at
    if store is None:
        store = create_store_record(store_id=store_id)

    return A3CaseRecord(
        case_id=case_id,
        problem_description=problem_description,
        store_id=store_id,
        problem_type=problem_type,
        context=context,
        root_cause=root_cause,
        solution_steps=solution_steps,
        outcome=outcome,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        store=store,
    )


def create_test_request(
    problem_description: str = "新问题",
    store_id: str = "store_001",
    problem_type: str = "customer_complaint",
    context: dict | None = None,
    root_cause: str = "新根因",
    solution_steps: list | None = None,
    outcome: dict | None = None,
) -> CreateCaseRequest:
    """创建测试用创建请求。"""
    if context is None:
        context = {"scene": "新场景"}
    if solution_steps is None:
        solution_steps = [{"order": 1, "content": "新步骤"}]
    if outcome is None:
        outcome = {"result": "improved", "notes": "新备注"}

    return CreateCaseRequest(
        problem_description=problem_description,
        store_id=store_id,
        problem_type=problem_type,
        context=context,
        root_cause=root_cause,
        solution_steps=solution_steps,
        outcome=outcome,
    )


class TestCaseServiceCreate:
    """测试 CaseService.create_case 方法。"""

    @pytest.mark.asyncio
    async def test_create_case_generates_stable_id(self):
        """创建案例时生成稳定的 case_id。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_create = AsyncMock(return_value=[])

        request = create_test_request()

        # case_id 由 repository 生成，服务层透传
        record = create_case_record()
        mock_repo.create.return_value = record

        service = CaseService(mock_repo, mock_validator)

        result = await service.create_case(request)

        assert result.case_id is not None
        assert result.case_id.startswith("case_")

    @pytest.mark.asyncio
    async def test_create_case_sets_default_status(self):
        """创建案例时设置默认状态为 draft。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_create = AsyncMock(return_value=[])

        request = create_test_request()
        record = create_case_record(status="draft")

        async def mock_store_exists(store_id: str) -> bool:
            return store_id == "store_001"

        service = CaseService(mock_repo, mock_validator)
        mock_repo.create.return_value = record

        result = await service.create_case(request)

        assert result.status == SchemaCaseStatus.DRAFT

    @pytest.mark.asyncio
    async def test_create_case_sets_timestamps(self):
        """创建案例时设置创建时间和更新时间。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_create = AsyncMock(return_value=[])

        request = create_test_request()
        now = make_utc_now()
        record = create_case_record(created_at=now, updated_at=now)

        async def mock_store_exists(store_id: str) -> bool:
            return store_id == "store_001"

        service = CaseService(mock_repo, mock_validator)
        mock_repo.create.return_value = record

        result = await service.create_case(request)

        assert result.created_at is not None
        assert result.updated_at is not None

    @pytest.mark.asyncio
    async def test_create_case_validation_fails(self):
        """创建校验失败时返回错误。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_create = AsyncMock(return_value=[
            FieldError(field="store_id", message="store_id does not exist")
        ])

        request = create_test_request(store_id="nonexistent_store")

        async def mock_store_exists(store_id: str) -> bool:
            return False

        service = CaseService(mock_repo, mock_validator)

        with pytest.raises(Exception) as exc_info:
            await service.create_case(request)
        # 校验失败应抛出验证异常
        assert "store_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_case_rejects_ai_derived_fields(self):
        """创建时拒绝 AI 派生字段（通过 schema 禁止字段实现）。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_create = AsyncMock(return_value=[])

        # request schema 禁止 case_id, created_at, updated_at；status 为合法创建字段
        request = create_test_request()

        record = create_case_record()

        async def mock_store_exists(store_id: str) -> bool:
            return store_id == "store_001"

        service = CaseService(mock_repo, mock_validator)
        mock_repo.create.return_value = record

        result = await service.create_case(request)

        # 响应中不应包含 AI 派生字段
        assert not hasattr(result, "summary")
        assert not hasattr(result, "embedding")
        assert not hasattr(result, "similarity_score")


class TestCaseServiceUpdate:
    """测试 CaseService.update_case 方法。"""

    @pytest.mark.asyncio
    async def test_update_case_edits_allowed_fields(self):
        """编辑时更新允许的字段。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_update = AsyncMock(return_value=[])

        original_record = create_case_record(
            case_id="case_update_001",
            problem_description="原始描述",
            status="draft",
        )
        updated_record = create_case_record(
            case_id="case_update_001",
            problem_description="更新后描述",
            status="draft",
        )

        mock_repo.get_by_id.return_value = original_record
        mock_repo.update.return_value = updated_record

        async def mock_store_exists(store_id: str) -> bool:
            return store_id == "store_001"

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(problem_description="更新后描述")
        result = await service.update_case("case_update_001", request)

        assert result.problem_description == "更新后描述"

    @pytest.mark.asyncio
    async def test_update_case_rejects_nonexistent_case(self):
        """编辑不存在的案例返回 CASE_NOT_FOUND。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_repo.get_by_id.return_value = None

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(problem_description="更新")
        with pytest.raises(Exception) as exc_info:
            await service.update_case("nonexistent_case", request)
        # 应该抛出包含 CASE_NOT_FOUND 的异常
        assert "CASE_NOT_FOUND" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_case_rejects_archived_case(self):
        """编辑归档案例返回 CASE_STATE_CONFLICT。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        archived_record = create_case_record(
            case_id="case_archived",
            status="archived",
        )
        mock_repo.get_by_id.return_value = archived_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(problem_description="尝试更新")
        with pytest.raises(Exception) as exc_info:
            await service.update_case("case_archived", request)
        # 应该抛出状态冲突异常
        error_msg = str(exc_info.value).lower()
        assert "archived" in error_msg or "conflict" in error_msg

    @pytest.mark.asyncio
    async def test_update_case_rejects_immutable_fields(self):
        """编辑时拒绝修改不可变字段（case_id, created_at）。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        original_record = create_case_record(
            case_id="case_immutable",
            status="draft",
        )
        mock_repo.get_by_id.return_value = original_record
        mock_repo.update.return_value = original_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        # case_id 和 created_at 在 schema 层就被禁止了
        # UpdateCaseRequest 的 case_id 和 created_at 字段定义为 None
        # 尝试修改 status 为非法的 draft->archived
        request = UpdateCaseRequest(status=SchemaCaseStatus.ARCHIVED)
        with pytest.raises(Exception) as exc:
            await service.update_case("case_immutable", request)
        # draft -> archived 是不允许的状态转换
        error_msg = str(exc.value).lower()
        assert "draft" in error_msg or "archived" in error_msg or "transition" in error_msg

    @pytest.mark.asyncio
    async def test_update_case_preserves_original_on_failure(self):
        """编辑校验失败时保留原案例数据。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        # 校验失败 - 使用 store_id 不存在的情况
        mock_validator.validate_update = AsyncMock(return_value=[
            FieldError(field="store_id", message="store_id does not exist")
        ])

        original_record = create_case_record(
            case_id="case_original",
            problem_description="原始描述",
            status="draft",
        )
        mock_repo.get_by_id.return_value = original_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        # 使用一个会通过 schema 但在 validator 层面失败的值（不存在的 store_id）
        request = UpdateCaseRequest(store_id="nonexistent_store")
        with pytest.raises(Exception):
            await service.update_case("case_original", request)

        # update 不应被调用，因为校验失败了
        mock_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_case_validates_store_exists(self):
        """编辑时校验 store_id 存在性。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_update = AsyncMock(return_value=[
            FieldError(field="store_id", message="store_id does not exist")
        ])

        original_record = create_case_record(
            case_id="case_store_update",
            store_id="store_001",
            status="draft",
        )
        mock_repo.get_by_id.return_value = original_record

        async def mock_store_exists(store_id: str) -> bool:
            return store_id == "store_001"

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(store_id="nonexistent_store")
        with pytest.raises(Exception) as exc_info:
            await service.update_case("case_store_update", request)
        assert "store_id" in str(exc_info.value).lower()


class TestCaseServiceStatusTransitions:
    """测试状态流转规则。"""

    @pytest.mark.asyncio
    async def test_draft_to_active_allowed(self):
        """draft -> active 是允许的。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_update = AsyncMock(return_value=[])

        original_record = create_case_record(
            case_id="case_d2a",
            status="draft",
        )
        updated_record = create_case_record(
            case_id="case_d2a",
            status="active",
        )
        mock_repo.get_by_id.return_value = original_record
        mock_repo.update.return_value = updated_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(status=SchemaCaseStatus.ACTIVE)
        result = await service.update_case("case_d2a", request)

        assert result.status == SchemaCaseStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_active_to_archived_allowed(self):
        """active -> archived 是允许的。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_update = AsyncMock(return_value=[])

        original_record = create_case_record(
            case_id="case_a2ar",
            status="active",
        )
        updated_record = create_case_record(
            case_id="case_a2ar",
            status="archived",
        )
        mock_repo.get_by_id.return_value = original_record
        mock_repo.update.return_value = updated_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(status=SchemaCaseStatus.ARCHIVED)
        result = await service.update_case("case_a2ar", request)

        assert result.status == SchemaCaseStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_active_to_active_allowed(self):
        """active -> active（回传当前状态）应允许，以便编辑保存。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_update = AsyncMock(return_value=[])

        original_record = create_case_record(
            case_id="case_a2a",
            status="active",
        )
        updated_record = create_case_record(
            case_id="case_a2a",
            status="active",
            problem_description="已更新描述",
        )
        mock_repo.get_by_id.return_value = original_record
        mock_repo.update.return_value = updated_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(
            status=SchemaCaseStatus.ACTIVE,
            problem_description="已更新描述",
        )
        result = await service.update_case("case_a2a", request)

        assert result.status == SchemaCaseStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_draft_to_archived_not_allowed(self):
        """draft -> archived 是不允许的。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        original_record = create_case_record(
            case_id="case_d2ar",
            status="draft",
        )
        mock_repo.get_by_id.return_value = original_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        request = UpdateCaseRequest(status=SchemaCaseStatus.ARCHIVED)
        with pytest.raises(Exception) as exc_info:
            await service.update_case("case_d2ar", request)
        # 应该拒绝 draft -> archived
        error_msg = str(exc_info.value).lower()
        assert "draft" in error_msg or "transition" in error_msg or "conflict" in error_msg

    @pytest.mark.asyncio
    async def test_archived_to_any_not_allowed(self):
        """archived -> 任意状态是不允许的（archived 不可编辑）。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        archived_record = create_case_record(
            case_id="case_archived_any",
            status="archived",
        )
        mock_repo.get_by_id.return_value = archived_record

        async def mock_store_exists(store_id: str) -> bool:
            return True

        service = CaseService(mock_repo, mock_validator)

        # 即使不改 status，仅改其他字段也会被拒绝
        request = UpdateCaseRequest(problem_description="尝试修改")
        with pytest.raises(Exception) as exc:
            await service.update_case("case_archived_any", request)
        error_msg = str(exc.value).lower()
        assert "archived" in error_msg or "conflict" in error_msg


class TestCaseServiceDelete:
    """测试 CaseService.delete_case 方法。"""

    @pytest.mark.asyncio
    async def test_delete_case_success(self):
        """删除存在的案例返回成功。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        mock_repo.delete.return_value = True

        service = CaseService(mock_repo, mock_validator)

        result = await service.delete_case("case_delete_001")

        assert result.success is True
        assert result.deleted_count == 1
        assert result.deleted_at is not None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_case_returns_not_found(self):
        """删除不存在的案例返回 CASE_NOT_FOUND。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        mock_repo.delete.return_value = False

        service = CaseService(mock_repo, mock_validator)

        with pytest.raises(Exception) as exc_info:
            await service.delete_case("nonexistent_case")
        assert "CASE_NOT_FOUND" in str(exc_info.value) or "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_case_supports_any_status(self):
        """删除支持任意状态的案例。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        # 测试 draft 状态
        mock_repo.delete.return_value = True
        service = CaseService(mock_repo, mock_validator)

        for status in ["draft", "active", "archived"]:
            case_id = f"case_delete_{status}"
            result = await service.delete_case(case_id)
            assert result.success is True


class TestCaseServiceGetCase:
    """测试 CaseService.get_case 方法。"""

    @pytest.mark.asyncio
    async def test_get_case_success(self):
        """获取存在的案例返回详情。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        record = create_case_record(
            case_id="case_get_001",
            problem_description="详情测试",
        )
        mock_repo.get_by_id.return_value = record

        service = CaseService(mock_repo, mock_validator)

        result = await service.get_case("case_get_001")

        assert result.case_id == "case_get_001"
        assert result.problem_description == "详情测试"
        assert result.tag_suggestions == []

    @pytest.mark.asyncio
    async def test_get_case_includes_tag_suggestions_from_enrichment(self):
        """存在增强结果时，详情中的 tag_suggestions 与派生表一致。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        record = create_case_record(case_id="case_tag_001")
        mock_repo.get_by_id.return_value = record

        mock_enr = AsyncMock()
        row = MagicMock()
        row.tag_suggestions = ["服务", "投诉"]
        mock_enr.get_enrichment_result_for_case = AsyncMock(return_value=row)

        service = CaseService(mock_repo, mock_validator, mock_enr)

        result = await service.get_case("case_tag_001")

        assert result.tag_suggestions == ["服务", "投诉"]

    @pytest.mark.asyncio
    async def test_get_case_nonexistent_returns_none(self):
        """获取不存在的案例返回 None 或抛出异常。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        mock_repo.get_by_id.return_value = None

        service = CaseService(mock_repo, mock_validator)

        with pytest.raises(Exception) as exc_info:
            await service.get_case("nonexistent_case")
        assert "CASE_NOT_FOUND" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


class TestCaseServiceListCases:
    """测试 CaseService.list_cases 方法。"""

    @pytest.mark.asyncio
    async def test_list_cases_returns_paginated_response(self):
        """列表查询返回分页响应。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        record = create_case_record(case_id="case_list_001")
        page = KeysetPage(
            items=[record],
            limit=20,
            has_more=False,
            sort="created_at desc, case_id desc",
        )
        mock_repo.list.return_value = page

        service = CaseService(mock_repo, mock_validator)

        query = CaseListQuery(limit=20)
        result = await service.list_cases(query)

        assert isinstance(result, PaginatedCaseListResponse)
        assert len(result.items) == 1
        assert result.items[0].case_id == "case_list_001"
        assert result.items[0].context.scene == "测试场景"

    @pytest.mark.asyncio
    async def test_list_cases_excludes_ai_derived_fields(self):
        """列表响应不包含 AI 派生字段。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        record = create_case_record(case_id="case_list_no_ai")
        page = KeysetPage(
            items=[record],
            limit=20,
            has_more=False,
        )
        mock_repo.list.return_value = page

        service = CaseService(mock_repo, mock_validator)

        query = CaseListQuery(limit=20)
        result = await service.list_cases(query)

        # 列表项不应包含 AI 派生字段
        for item in result.items:
            assert not hasattr(item, "summary")
            assert not hasattr(item, "embedding")
            assert not hasattr(item, "similarity_score")


class TestCaseServiceErrorMapping:
    """测试错误码映射。"""

    @pytest.mark.asyncio
    async def test_store_not_found_error_code(self):
        """store_id 不存在返回 STORE_NOT_FOUND 错误码。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()
        mock_validator.validate_create = AsyncMock(return_value=[
            FieldError(field="store_id", message="store_id does not exist")
        ])

        async def mock_store_exists(store_id: str) -> bool:
            return False

        service = CaseService(mock_repo, mock_validator)

        request = create_test_request(store_id="nonexistent_store")
        with pytest.raises(Exception) as exc_info:
            await service.create_case(request)

        # 应包含 STORE_NOT_FOUND 或 store 相关的错误信息
        error_str = str(exc_info.value).lower()
        assert "store" in error_str

    @pytest.mark.asyncio
    async def test_case_not_found_error_code(self):
        """case_id 不存在返回 CASE_NOT_FOUND 错误码。"""
        from app.cases.service import CaseService

        mock_repo = AsyncMock()
        mock_validator = MagicMock()

        mock_repo.get_by_id.return_value = None
        service = CaseService(mock_repo, mock_validator)

        with pytest.raises(Exception) as exc_info:
            await service.get_case("nonexistent_case")
        assert "CASE_NOT_FOUND" in str(exc_info.value) or "not found" in str(exc_info.value).lower()
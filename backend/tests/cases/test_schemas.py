"""案例请求响应 Schema 测试。

验证 CreateCaseRequest, UpdateCaseRequest, CaseDetailResponse,
CaseListItem, PaginatedCaseListResponse, DeleteCaseRequest,
DeleteCaseResponse, CascadeDeleteRequest, CascadeDeleteResponse 等契约。
"""
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.cases.schemas import (
    CaseDetailResponse,
    CaseListItem,
    CaseListQuery,
    CreateCaseRequest,
    DeleteCaseReason,
    DeleteCaseRequest,
    DeleteCaseResponse,
    CascadeDeleteRequest,
    CascadeDeleteResponse,
    OutcomeSchema,
    PaginatedCaseListResponse,
    SolutionStepSchema,
    StoreInfoSummary,
    UpdateCaseRequest,
)


class TestCreateCaseRequest:
    """验证 CreateCaseRequest 契约。"""

    def test_required_fields_present(self):
        """必填字段齐全时应通过校验。"""
        request = CreateCaseRequest(
            problem_description="顾客投诉服务员态度差",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "service_counter"},
            root_cause="服务员情绪管理不足",
            solution_steps=[
                {"order": 1, "content": "安抚顾客情绪"},
                {"order": 2, "content": "记录投诉详情"},
            ],
            outcome={"result": "improved", "notes": "顾客满意"},
        )
        assert request.problem_description == "顾客投诉服务员态度差"
        assert request.store_id == "store_001"
        assert request.problem_type == "customer_complaint"

    def test_excludes_case_id(self):
        """不应包含 case_id。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                case_id="case_001",  # 不应存在
                problem_description="test",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "test"},
                root_cause="test",
                solution_steps=[{"order": 1, "content": "test"}],
                outcome={"result": "improved", "notes": "test"},
            )
        errors = exc_info.value.errors()
        assert any("case_id" in str(e) for e in errors)

    def test_excludes_status(self):
        """不应包含 status。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="test",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "test"},
                root_cause="test",
                solution_steps=[{"order": 1, "content": "test"}],
                outcome={"result": "improved", "notes": "test"},
                status="active",  # 不应存在
            )
        errors = exc_info.value.errors()
        assert any("status" in str(e) for e in errors)

    def test_excludes_created_at(self):
        """不应包含 created_at。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="test",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "test"},
                root_cause="test",
                solution_steps=[{"order": 1, "content": "test"}],
                outcome={"result": "improved", "notes": "test"},
                created_at=datetime.now(),  # 不应存在
            )
        errors = exc_info.value.errors()
        assert any("created_at" in str(e) for e in errors)

    def test_excludes_updated_at(self):
        """不应包含 updated_at。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="test",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "test"},
                root_cause="test",
                solution_steps=[{"order": 1, "content": "test"}],
                outcome={"result": "improved", "notes": "test"},
                updated_at=datetime.now(),  # 不应存在
            )
        errors = exc_info.value.errors()
        assert any("updated_at" in str(e) for e in errors)

    def test_context_minimal_keys(self):
        """context 应包含 scene 最小键。"""
        request = CreateCaseRequest(
            problem_description="test",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "service"},  # scene 是最小键
            root_cause="test",
            solution_steps=[{"order": 1, "content": "test"}],
            outcome={"result": "improved", "notes": "test"},
        )
        assert request.context.scene == "service"

    def test_solution_steps_minimal_keys(self):
        """solution_steps 数组元素应包含 order 和 content 最小键。"""
        request = CreateCaseRequest(
            problem_description="test",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "test"},
            root_cause="test",
            solution_steps=[
                {"order": 1, "content": "步骤1"},
                {"order": 2, "content": "步骤2"},
            ],
            outcome={"result": "improved", "notes": "test"},
        )
        assert len(request.solution_steps) == 2
        assert request.solution_steps[0].order == 1
        assert request.solution_steps[0].content == "步骤1"

    def test_outcome_minimal_keys(self):
        """outcome 应包含 result 和 notes 最小键。"""
        request = CreateCaseRequest(
            problem_description="test",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "test"},
            root_cause="test",
            solution_steps=[{"order": 1, "content": "test"}],
            outcome={"result": "improved", "notes": "已改善"},
        )
        assert request.outcome.result.value == "improved"
        assert request.outcome.notes == "已改善"


class TestUpdateCaseRequest:
    """验证 UpdateCaseRequest 契约。"""

    def test_allows_editable_fields(self):
        """可编辑字段应允许存在。"""
        request = UpdateCaseRequest(
            problem_description="更新后的描述",
            store_id="store_002",
            problem_type="service_quality",
            context={"scene": "updated_scene"},
            root_cause="更新后的根因",
            solution_steps=[{"order": 1, "content": "新步骤"}],
            outcome={"result": "no_change", "notes": "无变化"},
            status="active",
        )
        assert request.problem_description == "更新后的描述"
        assert request.store_id == "store_002"
        assert request.status.value == "active"

    def test_forbids_case_id(self):
        """禁止包含 case_id。"""
        with pytest.raises(ValidationError) as exc_info:
            UpdateCaseRequest(
                case_id="case_forbidden",
                problem_description="test",
                root_cause="test",
                solution_steps=[{"order": 1, "content": "test"}],
                outcome={"result": "improved", "notes": "test"},
                context={"scene": "test"},
            )
        errors = exc_info.value.errors()
        assert any("case_id" in str(e) for e in errors)

    def test_forbids_created_at(self):
        """禁止包含 created_at。"""
        with pytest.raises(ValidationError) as exc_info:
            UpdateCaseRequest(
                problem_description="test",
                root_cause="test",
                solution_steps=[{"order": 1, "content": "test"}],
                outcome={"result": "improved", "notes": "test"},
                context={"scene": "test"},
                created_at=datetime.now(),
            )
        errors = exc_info.value.errors()
        assert any("created_at" in str(e) for e in errors)

    def test_optional_fields(self):
        """所有字段均为可选（仅禁止不可变字段）。"""
        request = UpdateCaseRequest(
            problem_description="仅更新描述",
        )
        assert request.problem_description == "仅更新描述"
        # 其他字段默认为 None
        assert request.store_id is None
        assert request.status is None


class TestCaseDetailResponse:
    """验证 CaseDetailResponse 契约。"""

    def test_contains_base_fields(self):
        """应包含全部基础字段。"""
        response = CaseDetailResponse(
            case_id="case_001",
            problem_description="顾客投诉",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "service"},
            root_cause="服务态度问题",
            solution_steps=[{"order": 1, "content": "道歉"}],
            outcome={"result": "improved", "notes": "已解决"},
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            store=StoreInfoSummary(
                store_id="store_001",
                store_name="测试门店",
                brand_id="brand_001",
                brand_name="测试品牌",
                business_type="火锅",
                store_scale="large",
                franchise_type="加盟",
                city="成都",
                city_tier="一线",
                updated_at=datetime.now(),
            ),
        )
        assert response.case_id == "case_001"
        assert response.problem_description == "顾客投诉"
        assert response.status.value == "active"

    def test_excludes_derived_fields(self):
        """应排除派生字段。"""
        # 验证 CaseDetailResponse 不包含这些字段
        fields = {f for f in CaseDetailResponse.model_fields.keys()}
        excluded = {
            "embedding",
            "summary",
            "recommendation_reason",
            "similarity_score",
            "feedback",
        }
        assert len(fields & excluded) == 0, f"不应包含派生字段: {fields & excluded}"

    def test_includes_store_info(self):
        """应包含关联的 StoreInfo 字段。"""
        response = CaseDetailResponse(
            case_id="case_001",
            problem_description="test",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "test"},
            root_cause="test",
            solution_steps=[{"order": 1, "content": "test"}],
            outcome={"result": "improved", "notes": "test"},
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            store=StoreInfoSummary(
                store_id="store_001",
                store_name="门店A",
                brand_id="brand_001",
                brand_name="品牌A",
                business_type="火锅",
                store_scale="large",
                franchise_type="加盟",
                city="成都",
                city_tier="一线",
                updated_at=datetime.now(),
            ),
        )
        assert response.store is not None
        assert response.store.store_name == "门店A"
        assert response.store.brand_name == "品牌A"


class TestCaseListItem:
    """验证 CaseListItem 契约。"""

    def test_contains_summary_fields(self):
        """应包含足够摘要字段供前端展示。"""
        item = CaseListItem(
            case_id="case_001",
            problem_description="顾客投诉服务员态度",
            store_id="store_001",
            problem_type="customer_complaint",
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            store=StoreInfoSummary(
                store_id="store_001",
                store_name="测试门店",
                brand_id="brand_001",
                brand_name="测试品牌",
                business_type="火锅",
                store_scale="large",
                franchise_type="加盟",
                city="成都",
                city_tier="一线",
                updated_at=datetime.now(),
            ),
        )
        assert item.case_id == "case_001"
        assert item.problem_description == "顾客投诉服务员态度"
        assert item.store.store_name == "测试门店"

    def test_excludes_derived_fields(self):
        """应排除派生字段。"""
        fields = {f for f in CaseListItem.model_fields.keys()}
        excluded = {"embedding", "summary", "recommendation_reason", "similarity_score", "feedback"}
        assert len(fields & excluded) == 0, f"不应包含派生字段: {fields & excluded}"


class TestPaginatedCaseListResponse:
    """验证 PaginatedCaseListResponse 契约。"""

    def test_pagination_structure(self):
        """分页结构应完整。"""
        response = PaginatedCaseListResponse(
            items=[],
            limit=20,
            next_cursor_created_at=None,
            next_cursor_case_id=None,
            has_more=False,
            sort="created_at desc, case_id desc",
        )
        assert response.limit == 20
        assert response.has_more is False
        assert response.sort == "created_at desc, case_id desc"

    def test_with_items(self):
        """包含列表项时结构正确。"""
        item = CaseListItem(
            case_id="case_001",
            problem_description="test",
            store_id="store_001",
            problem_type="customer_complaint",
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            store=StoreInfoSummary(
                store_id="store_001",
                store_name="测试门店",
                brand_id="brand_001",
                brand_name="测试品牌",
                business_type="火锅",
                store_scale="large",
                franchise_type="加盟",
                city="成都",
                city_tier="一线",
                updated_at=datetime.now(),
            ),
        )
        response = PaginatedCaseListResponse(
            items=[item],
            limit=20,
            next_cursor_created_at=None,
            next_cursor_case_id=None,
            has_more=False,
            sort="created_at desc, case_id desc",
        )
        assert len(response.items) == 1
        assert response.items[0].case_id == "case_001"


class TestDeleteCaseRequest:
    """验证 DeleteCaseRequest 契约。"""

    def test_required_fields(self):
        """必填字段：case_id, reason, requested_by。"""
        request = DeleteCaseRequest(
            case_id="case_001",
            reason=DeleteCaseReason.USER_REQUESTED,
            requested_by="user_001",
        )
        assert request.case_id == "case_001"
        assert request.reason == DeleteCaseReason.USER_REQUESTED
        assert request.requested_by == "user_001"

    def test_reason_enum_values(self):
        """reason 应为删除原因枚举。"""
        for reason in DeleteCaseReason:
            request = DeleteCaseRequest(
                case_id="case_001",
                reason=reason,
                requested_by="user_001",
            )
            assert request.reason == reason


class TestDeleteCaseResponse:
    """验证 DeleteCaseResponse 契约。"""

    def test_required_fields(self):
        """必填字段：success, deleted_count, deleted_at。"""
        response = DeleteCaseResponse(
            success=True,
            deleted_count=1,
            deleted_at=datetime.now(),
        )
        assert response.success is True
        assert response.deleted_count == 1
        assert response.deleted_at is not None


class TestCascadeDeleteRequest:
    """验证 CascadeDeleteRequest 契约。"""

    def test_required_fields(self):
        """必填字段：case_id, requested_by。"""
        request = CascadeDeleteRequest(
            case_id="case_001",
            requested_by="user_001",
        )
        assert request.case_id == "case_001"
        assert request.requested_by == "user_001"


class TestCascadeDeleteResponse:
    """验证 CascadeDeleteResponse 契约。"""

    def test_required_fields(self):
        """应包含各步骤删除状态和 partial_failures。"""
        response = CascadeDeleteResponse(
            success=True,
            case_id="case_001",
            case_deleted=True,
            enrichment_deleted=True,
            vector_deleted=False,
            feedback_deleted=True,
            case_deleted_count=1,
            enrichment_deleted_count=0,
            vector_deleted_count=0,
            feedback_deleted_count=0,
            partial_failures=[
                {"service": "case-vector-indexing", "error": "service unavailable"}
            ],
        )
        assert response.success is True
        assert response.case_id == "case_001"
        assert response.case_deleted is True
        assert response.vector_deleted is False
        assert len(response.partial_failures) == 1

    def test_partial_failures_empty(self):
        """部分失败可为空列表。"""
        response = CascadeDeleteResponse(
            success=True,
            case_id="case_001",
            case_deleted=True,
            enrichment_deleted=True,
            vector_deleted=True,
            feedback_deleted=True,
            case_deleted_count=1,
            enrichment_deleted_count=1,
            vector_deleted_count=1,
            feedback_deleted_count=1,
            partial_failures=[],
        )
        assert response.partial_failures == []


class TestCaseListQuery:
    """验证 CaseListQuery 契约。"""

    def test_default_values(self):
        """默认分页和排序值。"""
        query = CaseListQuery()
        assert query.limit == 20
        assert query.include_archived is False
        assert query.cursor_created_at is None
        assert query.cursor_case_id is None

    def test_cursor_must_be_pair(self):
        """cursor_created_at 和 cursor_case_id 必须成对提供。"""
        # 单独提供 cursor_created_at 应失败
        with pytest.raises(ValidationError) as exc_info:
            CaseListQuery(cursor_created_at=datetime.now())
        errors = exc_info.value.errors()
        assert any("cursor" in str(e).lower() for e in errors)

    def test_filter_fields(self):
        """应支持过滤字段。"""
        query = CaseListQuery(
            brand_id="brand_001",
            store_id="store_001",
            business_type="火锅",
            store_scale="large",
            franchise_type="加盟",
            city="成都",
            city_tier="一线",
            problem_type="customer_complaint",
            status="active",
        )
        assert query.brand_id == "brand_001"
        assert query.store_id == "store_001"
        assert query.business_type == "火锅"


class TestSolutionStepSchema:
    """验证 SolutionStepSchema 契约。"""

    def test_order_must_be_positive(self):
        """order 必须为正整数。"""
        step = SolutionStepSchema(order=1, content="步骤内容")
        assert step.order == 1

    def test_content_required(self):
        """content 必须非空。"""
        step = SolutionStepSchema(order=1, content="有效内容")
        assert step.content == "有效内容"


class TestOutcomeSchema:
    """验证 OutcomeSchema 契约。"""

    def test_result_enum_values(self):
        """result 应为效果结果枚举。"""
        for result in ["improved", "no_change", "unknown"]:
            outcome = OutcomeSchema(result=result, notes="test")
            assert outcome.result.value == result

    def test_notes_optional(self):
        """notes 可为空字符串。"""
        outcome = OutcomeSchema(result="improved", notes="")
        assert outcome.notes == ""


class TestDeleteCaseReason:
    """验证 DeleteCaseReason 枚举。"""

    def test_reason_values(self):
        """删除原因枚举应包含预期值。"""
        expected = {
            "user_requested",
            "store_closed",
            "data_corrected",
            "duplicate",
            "policy_violation",
            "other",
        }
        actual = {r.value for r in DeleteCaseReason}
        assert actual == expected

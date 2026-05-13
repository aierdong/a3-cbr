"""案例字段与步骤校验器测试。

验证 CaseValidator 对业务逻辑校验的能力。

注意：Schema 层（Pydantic）处理基础结构校验（空字符串、枚举值、步骤顺序）。
CaseValidator 处理业务逻辑校验（store_id 存在性）。

某些校验由 Schema 层和 Validator 共同完成：
- solution_steps 顺序：Schema 校验格式，Validator 可校验业务规则
- store_id 存在性：仅 Validator 校验（需要注入 store_exists 函数）
"""
import pytest
from pydantic import ValidationError

from app.cases.schemas import (
    CreateCaseRequest,
    UpdateCaseRequest,
)
from app.cases.validators import (
    CaseValidator,
    validate_create_case,
    validate_update_case,
)


class TestSchemaValidationLayer:
    """Schema 层校验：Pydantic 处理基础结构校验。"""

    def test_problem_description_empty_rejected(self):
        """problem_description 为空字符串时 Pydantic 校验失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("problem_description" in str(e) for e in errors)

    def test_store_id_empty_rejected(self):
        """store_id 为空字符串时 Pydantic 校验失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("store_id" in str(e) for e in errors)

    def test_problem_type_invalid_enum_rejected(self):
        """无效的 problem_type 枚举值被 Pydantic 校验拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="invalid_type",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("problem_type" in str(e) for e in errors)

    def test_outcome_result_invalid_enum_rejected(self):
        """无效的 outcome.result 枚举值被 Pydantic 校验拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "invalid_result", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("result" in str(e) for e in errors)

    def test_root_cause_empty_rejected(self):
        """root_cause 为空字符串时 Pydantic 校验失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("root_cause" in str(e) for e in errors)

    def test_context_scene_empty_rejected(self):
        """context.scene 为空字符串时 Pydantic 校验失败。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": ""},
                root_cause="原因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("context" in str(e) for e in errors)

    def test_solution_steps_order_invalid_rejected_at_schema(self):
        """步骤顺序不从 1 开始时 Schema 层拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[
                    {"order": 2, "content": "第二步"},
                    {"order": 3, "content": "第三步"},
                ],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("solution_steps" in str(e) for e in errors)

    def test_solution_steps_content_empty_rejected_at_schema(self):
        """步骤内容为空时 Schema 层拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[
                    {"order": 1, "content": ""},
                ],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("solution_steps" in str(e) for e in errors)

    def test_solution_steps_gap_rejected_at_schema(self):
        """步骤顺序有间隔时 Schema 层拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[
                    {"order": 1, "content": "第一步"},
                    {"order": 3, "content": "第三步"},
                ],
                outcome={"result": "improved", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("solution_steps" in str(e) for e in errors)


class TestCaseValidatorStoreId:
    """校验 store_id 存在性（业务逻辑校验）。"""

    @pytest.mark.asyncio
    async def test_store_id_must_exist(self):
        """store_id 必须在 store_infos 中存在。"""
        request = CreateCaseRequest(
            problem_description="问题描述",
            store_id="nonexistent_store",
            problem_type="customer_complaint",
            context={"scene": "service"},
            root_cause="原因",
            solution_steps=[{"order": 1, "content": "步骤"}],
            outcome={"result": "improved", "notes": "备注"},
        )

        def store_exists(sid: str) -> bool:
            return sid == "store_001"

        errors = await validate_create_case(request, store_exists)
        field_names = [e.field for e in errors]
        assert "store_id" in field_names

    @pytest.mark.asyncio
    async def test_store_id_exists_passes(self):
        """存在的 store_id 应通过校验。"""
        request = CreateCaseRequest(
            problem_description="问题描述",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "service"},
            root_cause="原因",
            solution_steps=[{"order": 1, "content": "步骤"}],
            outcome={"result": "improved", "notes": "备注"},
        )

        def store_exists(sid: str) -> bool:
            return sid == "store_001"

        errors = await validate_create_case(request, store_exists)
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_valid_request_passes(self):
        """所有字段有效时通过校验。"""
        request = CreateCaseRequest(
            problem_description="问题描述",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "service"},
            root_cause="原因",
            solution_steps=[
                {"order": 1, "content": "第一步"},
                {"order": 2, "content": "第二步"},
                {"order": 3, "content": "第三步"},
            ],
            outcome={"result": "improved", "notes": "备注"},
        )

        def store_exists(sid: str) -> bool:
            return sid == "store_001"

        errors = await validate_create_case(request, store_exists)
        assert len(errors) == 0


class TestCaseValidatorUpdate:
    """校验 UpdateCaseRequest（业务逻辑校验）。"""

    @pytest.mark.asyncio
    async def test_update_valid_request_passes(self):
        """有效的更新请求应通过校验。"""
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

        def store_exists(sid: str) -> bool:
            return sid in ("store_001", "store_002")

        errors = await validate_update_case(request, store_exists)
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_update_empty_request_passes(self):
        """空更新请求应通过校验（所有字段可选）。"""
        request = UpdateCaseRequest()
        errors = await validate_update_case(request, lambda sid: True)
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_update_store_id_not_exists_fails(self):
        """更新的 store_id 不存在时失败。"""
        request = UpdateCaseRequest(
            store_id="nonexistent_store",
        )

        def store_exists(sid: str) -> bool:
            return False

        errors = await validate_update_case(request, store_exists)
        field_names = [e.field for e in errors]
        assert "store_id" in field_names

    def test_update_problem_type_invalid_rejected_at_schema(self):
        """更新时无效的 problem_type 在 Schema 层被拒绝。"""
        with pytest.raises(ValidationError):
            UpdateCaseRequest(
                problem_type="invalid_type",
            )

    def test_update_problem_description_empty_rejected_at_schema(self):
        """更新时 problem_description 为空在 Schema 层被拒绝。"""
        with pytest.raises(ValidationError):
            UpdateCaseRequest(
                problem_description="",
            )

    def test_update_context_scene_empty_rejected_at_schema(self):
        """更新时 context.scene 为空在 Schema 层被拒绝。"""
        with pytest.raises(ValidationError):
            UpdateCaseRequest(
                context={"scene": ""},
            )

    def test_update_solution_steps_invalid_rejected_at_schema(self):
        """更新时无效的 solution_steps 在 Schema 层被拒绝。"""
        with pytest.raises(ValidationError):
            UpdateCaseRequest(
                solution_steps=[
                    {"order": 2, "content": "第二步"},
                ],
            )

    def test_update_empty_solution_steps_rejected_at_schema(self):
        """更新时空的 solution_steps 在 Schema 层被拒绝。"""
        with pytest.raises(ValidationError):
            UpdateCaseRequest(
                solution_steps=[],
            )


class TestCaseValidatorFieldErrorFormat:
    """校验 FieldError 格式。"""

    @pytest.mark.asyncio
    async def test_field_error_has_field_and_message(self):
        """FieldError 应包含 field 和 message。"""
        request = CreateCaseRequest(
            problem_description="问题描述",
            store_id="nonexistent_store",
            problem_type="customer_complaint",
            context={"scene": "service"},
            root_cause="原因",
            solution_steps=[{"order": 1, "content": "步骤"}],
            outcome={"result": "improved", "notes": "备注"},
        )

        def store_exists(sid: str) -> bool:
            return False

        errors = await validate_create_case(request, store_exists)
        assert len(errors) > 0
        error = errors[0]
        assert hasattr(error, "field")
        assert hasattr(error, "message")
        assert isinstance(error.field, str)
        assert isinstance(error.message, str)
        assert error.field == "store_id"

    @pytest.mark.asyncio
    async def test_multiple_field_errors(self):
        """可返回多个字段错误。"""
        request = CreateCaseRequest(
            problem_description="问题描述",
            store_id="nonexistent_store",
            problem_type="customer_complaint",
            context={"scene": "service"},
            root_cause="原因",
            solution_steps=[{"order": 1, "content": "步骤"}],
            outcome={"result": "improved", "notes": "备注"},
        )

        def store_exists(sid: str) -> bool:
            return False

        errors = await validate_create_case(request, store_exists)
        # 只有 store_id 错误，因为其他字段都通过了 Schema 层校验
        assert len(errors) >= 1


class TestCaseValidatorClass:
    """CaseValidator 类封装测试。"""

    @pytest.mark.asyncio
    async def test_validate_create_static_method(self):
        """CaseValidator.validate_create 为异步静态方法。"""
        request = CreateCaseRequest(
            problem_description="问题描述",
            store_id="store_001",
            problem_type="customer_complaint",
            context={"scene": "service"},
            root_cause="原因",
            solution_steps=[{"order": 1, "content": "步骤"}],
            outcome={"result": "improved", "notes": "备注"},
        )

        def store_exists(sid: str) -> bool:
            return True

        errors = await CaseValidator.validate_create(request, store_exists)
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_validate_update_static_method(self):
        """CaseValidator.validate_update 为异步静态方法。"""
        request = UpdateCaseRequest(
            problem_description="更新描述",
        )

        def store_exists(sid: str) -> bool:
            return True

        errors = await CaseValidator.validate_update(request, store_exists)
        assert len(errors) == 0


class TestCaseValidatorOutcomeResult:
    """校验 outcome.result 枚举值。"""

    @pytest.mark.asyncio
    async def test_valid_outcome_results(self):
        """所有有效的 outcome.result 枚举值应通过校验。"""
        for result_value in ["improved", "no_change", "unknown"]:
            request = CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": result_value, "notes": "备注"},
            )
            errors = await validate_create_case(request, lambda sid: True)
            assert len(errors) == 0, f"result={result_value} should pass"

    def test_invalid_outcome_result_rejected_at_schema(self):
        """无效的 outcome.result 在 Schema 层被拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            CreateCaseRequest(
                problem_description="问题描述",
                store_id="store_001",
                problem_type="customer_complaint",
                context={"scene": "service"},
                root_cause="原因",
                solution_steps=[{"order": 1, "content": "步骤"}],
                outcome={"result": "invalid", "notes": "备注"},
            )
        errors = exc_info.value.errors()
        assert any("result" in str(e) for e in errors)
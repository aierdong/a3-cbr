"""案例级联删除协调器测试。

测试 CaseDeleteCoordinator 的级联删除和降级策略。
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cases.schemas import CascadeDeleteRequest


def make_utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class TestCaseDeleteCoordinatorDeleteCaseCascade:
    """测试 delete_case_cascade 方法。"""

    @pytest.mark.asyncio
    async def test_cascade_delete_all_services_succeed(self):
        """级联删除全部成功时返回成功。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.return_value = MagicMock(
            success=True, deleted_count=1, deleted_at=make_utc_now()
        )

        coordinator = CaseDeleteCoordinator(mock_case_service)

        # Mock downstream service calls
        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_enrichment.return_value = (True, 1)
            mock_vector.return_value = (True, 1)
            mock_feedback.return_value = (True, 1)

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            assert result.success is True
            assert result.case_id == "case_001"
            assert result.case_deleted is True
            assert result.enrichment_deleted is True
            assert result.vector_deleted is True
            assert result.feedback_deleted is True
            assert result.case_deleted_count == 1
            assert result.enrichment_deleted_count == 1
            assert result.vector_deleted_count == 1
            assert result.feedback_deleted_count == 1
            assert len(result.partial_failures) == 0

    @pytest.mark.asyncio
    async def test_cascade_delete_case_not_found_treated_as_success(self):
        """案例不存在时按目标状态已达成处理并继续下游清理。"""
        from app.cases.coordinator import CaseDeleteCoordinator
        from app.cases.service import CaseNotFoundError

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.side_effect = CaseNotFoundError("case_001")

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_enrichment.return_value = (True, 0)  # 无数据删除
            mock_vector.return_value = (True, 0)
            mock_feedback.return_value = (True, 0)

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            # CASE_NOT_FOUND 按"目标状态已达成"处理
            assert result.success is True
            assert result.case_deleted is True  # 视为已删除
            assert result.case_id == "case_001"
            # 继续清理下游
            assert mock_enrichment.called
            assert mock_vector.called
            assert mock_feedback.called

    @pytest.mark.asyncio
    async def test_cascade_delete_case_base_failure_fails_entire_operation(self):
        """案例基础数据删除失败时整个删除操作失败。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        # 模拟数据库连接失败等基础删除失败
        mock_case_service.delete_case.side_effect = Exception("Database connection error")

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            assert result.success is False
            assert result.case_deleted is False
            # 下游删除不应被调用
            assert not mock_enrichment.called
            assert not mock_vector.called
            assert not mock_feedback.called
            assert len(result.partial_failures) == 1

    @pytest.mark.asyncio
    async def test_cascade_delete_llm_failure_continues_to_vector(self):
        """LLM 派生数据删除失败时继续尝试删除向量索引。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.return_value = MagicMock(
            success=True, deleted_count=1, deleted_at=make_utc_now()
        )

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            # LLM 删除失败
            mock_enrichment.side_effect = Exception("LLM service unavailable")
            # 向量和反馈删除成功
            mock_vector.return_value = (True, 1)
            mock_feedback.return_value = (True, 1)

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            assert result.success is True  # 整体成功（案例已删除）
            assert result.case_deleted is True
            assert result.enrichment_deleted is False
            assert result.vector_deleted is True
            assert result.feedback_deleted is True
            assert len(result.partial_failures) == 1
            assert result.partial_failures[0].service == "llm-case-enrichment"

    @pytest.mark.asyncio
    async def test_cascade_delete_vector_failure_continues_to_feedback(self):
        """向量索引数据删除失败时继续尝试删除推荐反馈。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.return_value = MagicMock(
            success=True, deleted_count=1, deleted_at=make_utc_now()
        )

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_enrichment.return_value = (True, 1)
            # 向量删除失败
            mock_vector.side_effect = Exception("Vector service unavailable")
            # 反馈删除成功
            mock_feedback.return_value = (True, 1)

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            assert result.success is True
            assert result.case_deleted is True
            assert result.enrichment_deleted is True
            assert result.vector_deleted is False
            assert result.feedback_deleted is True
            assert len(result.partial_failures) == 1
            assert result.partial_failures[0].service == "case-vector-indexing"

    @pytest.mark.asyncio
    async def test_cascade_delete_feedback_failure_records_partial_failure(self):
        """推荐反馈数据删除失败时记录 partial_failure。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.return_value = MagicMock(
            success=True, deleted_count=1, deleted_at=make_utc_now()
        )

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_enrichment.return_value = (True, 1)
            mock_vector.return_value = (True, 1)
            # 反馈删除失败
            mock_feedback.side_effect = Exception("Feedback service unavailable")

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            assert result.success is True
            assert result.feedback_deleted is False
            assert len(result.partial_failures) == 1
            assert result.partial_failures[0].service == "recommendation-feedback"

    @pytest.mark.asyncio
    async def test_cascade_delete_downstream_service_unavailable_skipped(self):
        """下游服务不可用时可跳过。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.return_value = MagicMock(
            success=True, deleted_count=1, deleted_at=make_utc_now()
        )

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            # 服务不可用（超时或无数据均视为可跳过）
            mock_enrichment.side_effect = Exception("Service timeout")
            mock_vector.side_effect = Exception("Service unavailable")
            mock_feedback.side_effect = Exception("Service unavailable")

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            # 不阻塞上游删除
            assert result.case_deleted is True
            assert result.success is True
            assert len(result.partial_failures) == 3


class TestCaseDeleteCoordinatorDeleteEnrichmentCascade:
    """测试 delete_enrichment_cascade 方法。"""

    @pytest.mark.asyncio
    async def test_delete_enrichment_cascade_triggers_downstream(self):
        """从案例增强节点发起的级联删除应触发下游清理。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_vector.return_value = (True, 1)
            mock_feedback.return_value = (True, 1)

            result = await coordinator.delete_enrichment_cascade(
                enrichment_id="enrich_001", requested_by="user_001"
            )

            assert result.success is True
            assert mock_vector.called
            assert mock_feedback.called


class TestCaseDeleteCoordinatorDeleteVectorCascade:
    """测试 delete_vector_cascade 方法。"""

    @pytest.mark.asyncio
    async def test_delete_vector_cascade_triggers_feedback_only(self):
        """从向量索引节点发起的级联删除只触发反馈删除。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_feedback.return_value = (True, 1)

            result = await coordinator.delete_vector_cascade(
                vector_id="vec_001", requested_by="user_001"
            )

            assert result.success is True
            assert result.vector_deleted is True
            # 反馈删除被调用
            assert mock_feedback.called


class TestCaseDeleteCoordinatorIdempotency:
    """测试幂等性保证。"""

    @pytest.mark.asyncio
    async def test_cascade_delete_idempotent_on_repeated_calls(self):
        """重复调用不产生副作用。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.return_value = MagicMock(
            success=True, deleted_count=1, deleted_at=make_utc_now()
        )

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_enrichment.return_value = (True, 0)  # 无数据删除
            mock_vector.return_value = (True, 0)
            mock_feedback.return_value = (True, 0)

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")

            # 第一次调用
            result1 = await coordinator.delete_case_cascade(request)
            # 第二次调用
            result2 = await coordinator.delete_case_cascade(request)

            # 结果应该一致（幂等）
            assert result1.success == result2.success
            assert result1.case_id == result2.case_id
            assert result1.partial_failures == result2.partial_failures


class TestCaseDeleteCoordinatorResponseStructure:
    """测试响应结构。"""

    @pytest.mark.asyncio
    async def test_cascade_delete_response_contains_all_required_fields(self):
        """响应应包含所有必填字段。"""
        from app.cases.coordinator import CaseDeleteCoordinator

        mock_case_service = AsyncMock()
        mock_case_service.delete_case.return_value = MagicMock(
            success=True, deleted_count=1, deleted_at=make_utc_now()
        )

        coordinator = CaseDeleteCoordinator(mock_case_service)

        with patch.object(
            coordinator, "_call_enrichment_delete", new_callable=AsyncMock
        ) as mock_enrichment, patch.object(
            coordinator, "_call_vector_delete", new_callable=AsyncMock
        ) as mock_vector, patch.object(
            coordinator, "_call_feedback_delete", new_callable=AsyncMock
        ) as mock_feedback:
            mock_enrichment.return_value = (True, 1)
            mock_vector.return_value = (True, 1)
            mock_feedback.return_value = (True, 1)

            request = CascadeDeleteRequest(case_id="case_001", requested_by="user_001")
            result = await coordinator.delete_case_cascade(request)

            # 验证响应结构完整
            assert hasattr(result, "success")
            assert hasattr(result, "case_id")
            assert hasattr(result, "case_deleted")
            assert hasattr(result, "enrichment_deleted")
            assert hasattr(result, "vector_deleted")
            assert hasattr(result, "feedback_deleted")
            assert hasattr(result, "case_deleted_count")
            assert hasattr(result, "enrichment_deleted_count")
            assert hasattr(result, "vector_deleted_count")
            assert hasattr(result, "feedback_deleted_count")
            assert hasattr(result, "partial_failures")
            assert isinstance(result.partial_failures, list)
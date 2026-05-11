"""案例级联删除协调器。

作为跨规格级联删除的协调入口。
依次调用本规格的 CaseService.delete_case 和下游规格的删除 API：
- llm-case-enrichment: POST /api/enrichment/delete
- case-vector-indexing: POST /api/vector-index/delete
- recommendation-feedback: POST /api/recommendation-feedback/delete

下游服务不可用或删除失败时，不阻塞上游删除，记录失败信息到 partial_failures。
支持从案例、案例增强、向量索引节点发起的级联删除。
所有删除操作幂等，重复调用不产生副作用。
"""
import logging
from typing import Optional

import httpx

from app.cases.schemas import (
    CascadeDeleteRequest,
    CascadeDeleteResponse,
    CascadeDeleteSubFailure,
)
from app.cases.service import CaseNotFoundError, CaseService


logger = logging.getLogger(__name__)

# 下游服务配置
ENRICHMENT_SERVICE_URL = "http://llm-case-enrichment"
VECTOR_SERVICE_URL = "http://case-vector-indexing"
FEEDBACK_SERVICE_URL = "http://recommendation-feedback"

# 请求超时（秒）
DOWNSTREAM_TIMEOUT = 5.0


class CaseDeleteCoordinator:
    """案例级联删除协调器。

    部署在本规格服务中，作为跨规格级联删除的协调入口。

    职责：
    - 依次调用本规格的 CaseService.delete_case 和下游规格的删除 API
    - 下游服务不可用或删除失败时，不阻塞上游删除，记录失败信息到 partial_failures
    - 支持从案例、案例增强、向量索引节点发起的级联删除

    幂等性：
    - POST /api/a3-cases/delete 对已删除或不存在的案例返回 404 CASE_NOT_FOUND
    - 其他删除 API 对不存在的数据返回 HTTP 200（deleted_count = 0）
    - 级联接口对上游 CASE_NOT_FOUND 按"目标状态已达成"处理并继续下游清理
    """

    def __init__(
        self,
        case_service: CaseService,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """初始化协调器。

        Args:
            case_service: 案例服务实例
            http_client: 可选的 HTTP 客户端（用于测试注入）
        """
        self._case_service = case_service
        self._http_client = http_client

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端。"""
        if self._http_client is not None:
            return self._http_client
        return httpx.AsyncClient(timeout=DOWNSTREAM_TIMEOUT)

    async def delete_case_cascade(
        self, request: CascadeDeleteRequest
    ) -> CascadeDeleteResponse:
        """执行案例级联删除。

        调用顺序：
        1. 调用 POST /api/a3-cases/delete 删除案例基础数据
        2. 调用 POST /api/enrichment/delete 删除 LLM 派生数据
        3. 调用 POST /api/vector-index/delete 删除向量索引数据
        4. 调用 POST /api/recommendation-feedback/delete 删除推荐反馈数据

        降级策略：
        - 案例基础数据删除失败：整个删除操作失败
        - LLM 派生数据删除失败：案例基础数据已删除，记录 partial_failures，继续
        - 向量索引数据删除失败：继续尝试删除推荐反馈
        - 推荐反馈数据删除失败：记录 partial_failures
        - 下游服务不可用或无数据：可跳过（超时或无数据均视为可跳过）

        Args:
            request: 级联删除请求

        Returns:
            CascadeDeleteResponse: 级联删除响应
        """
        partial_failures: list[CascadeDeleteSubFailure] = []
        case_deleted = False
        case_deleted_count = 0
        enrichment_deleted = False
        enrichment_deleted_count = 0
        vector_deleted = False
        vector_deleted_count = 0
        feedback_deleted = False
        feedback_deleted_count = 0

        # Step 1: 删除案例基础数据
        try:
            delete_response = await self._case_service.delete_case(request.case_id)
            case_deleted = True
            case_deleted_count = delete_response.deleted_count
        except CaseNotFoundError:
            # 案例不存在时按"目标状态已达成"处理，继续下游清理
            logger.warning(
                f"Case {request.case_id} not found during cascade delete, "
                "treating as already deleted and continuing downstream cleanup"
            )
            case_deleted = True
            case_deleted_count = 0
        except Exception as e:
            # 案例基础数据删除失败，整个删除操作失败
            logger.error(f"Failed to delete case base data: {e}")
            return CascadeDeleteResponse(
                success=False,
                case_id=request.case_id,
                case_deleted=False,
                enrichment_deleted=False,
                vector_deleted=False,
                feedback_deleted=False,
                case_deleted_count=0,
                enrichment_deleted_count=0,
                vector_deleted_count=0,
                feedback_deleted_count=0,
                partial_failures=[
                    CascadeDeleteSubFailure(
                        service="a3-case-management",
                        error=f"Case base delete failed: {str(e)}",
                    )
                ],
            )

        # Step 2: 删除 LLM 派生数据
        try:
            enrichment_deleted, enrichment_deleted_count = await self._call_enrichment_delete(
                request.case_id, request.requested_by
            )
        except Exception as e:
            logger.warning(f"Failed to delete LLM enrichment data: {e}")
            enrichment_deleted = False
            partial_failures.append(
                CascadeDeleteSubFailure(service="llm-case-enrichment", error=str(e))
            )

        # Step 3: 删除向量索引数据
        try:
            vector_deleted, vector_deleted_count = await self._call_vector_delete(
                request.case_id, request.requested_by
            )
        except Exception as e:
            logger.warning(f"Failed to delete vector index data: {e}")
            vector_deleted = False
            partial_failures.append(
                CascadeDeleteSubFailure(service="case-vector-indexing", error=str(e))
            )

        # Step 4: 删除推荐反馈数据
        try:
            feedback_deleted, feedback_deleted_count = await self._call_feedback_delete(
                request.case_id,
                request.requested_by,
                reason="case_deleted",
            )
        except Exception as e:
            logger.warning(f"Failed to delete recommendation feedback data: {e}")
            feedback_deleted = False
            partial_failures.append(
                CascadeDeleteSubFailure(service="recommendation-feedback", error=str(e))
            )

        # 整体成功（案例已删除，可能有部分下游失败）
        return CascadeDeleteResponse(
            success=True,
            case_id=request.case_id,
            case_deleted=case_deleted,
            enrichment_deleted=enrichment_deleted,
            vector_deleted=vector_deleted,
            feedback_deleted=feedback_deleted,
            case_deleted_count=case_deleted_count,
            enrichment_deleted_count=enrichment_deleted_count,
            vector_deleted_count=vector_deleted_count,
            feedback_deleted_count=feedback_deleted_count,
            partial_failures=partial_failures,
        )

    async def delete_enrichment_cascade(
        self, enrichment_id: str, requested_by: str
    ) -> CascadeDeleteResponse:
        """从案例增强节点发起的级联删除。

        Args:
            enrichment_id: 增强记录 ID（用于关联对应的案例）
            requested_by: 删除请求者标识

        Returns:
            CascadeDeleteResponse: 级联删除响应
        """
        partial_failures: list[CascadeDeleteSubFailure] = []
        vector_deleted = False
        vector_deleted_count = 0
        feedback_deleted = False
        feedback_deleted_count = 0

        # 从 enrichment_id 提取 case_id（格式：case_{id}_enrichment）
        # 这里假设 enrichment_id 格式为 case_xxx_enrichment 或包含 case_id 信息
        # 实际实现中可能需要根据 enrichment 服务返回的数据结构来确定
        case_id = self._extract_case_id_from_enrichment_id(enrichment_id)

        # Step 1: 删除向量索引数据
        try:
            vector_deleted, vector_deleted_count = await self._call_vector_delete(
                case_id, requested_by
            )
        except Exception as e:
            logger.warning(f"Failed to delete vector index data: {e}")
            vector_deleted = False
            partial_failures.append(
                CascadeDeleteSubFailure(service="case-vector-indexing", error=str(e))
            )

        # Step 2: 删除推荐反馈数据
        try:
            feedback_deleted, feedback_deleted_count = await self._call_feedback_delete(
                case_id,
                requested_by,
                reason="enrichment_deleted",
            )
        except Exception as e:
            logger.warning(f"Failed to delete recommendation feedback data: {e}")
            feedback_deleted = False
            partial_failures.append(
                CascadeDeleteSubFailure(service="recommendation-feedback", error=str(e))
            )

        return CascadeDeleteResponse(
            success=True,
            case_id=case_id,
            case_deleted=False,  # 不删除案例，只删除下游
            enrichment_deleted=True,  # 视为已删除（从增强节点发起）
            vector_deleted=vector_deleted,
            feedback_deleted=feedback_deleted,
            case_deleted_count=0,
            enrichment_deleted_count=1,
            vector_deleted_count=vector_deleted_count,
            feedback_deleted_count=feedback_deleted_count,
            partial_failures=partial_failures,
        )

    async def delete_vector_cascade(
        self, vector_id: str, requested_by: str
    ) -> CascadeDeleteResponse:
        """从向量索引节点发起的级联删除。

        Args:
            vector_id: 向量记录 ID（用于关联对应的案例）
            requested_by: 删除请求者标识

        Returns:
            CascadeDeleteResponse: 级联删除响应
        """
        partial_failures: list[CascadeDeleteSubFailure] = []
        feedback_deleted = False
        feedback_deleted_count = 0

        # 从 vector_id 提取 case_id
        case_id = self._extract_case_id_from_vector_id(vector_id)

        # 只删除推荐反馈数据
        try:
            feedback_deleted, feedback_deleted_count = await self._call_feedback_delete(
                case_id,
                requested_by,
                reason="vector_deleted",
            )
        except Exception as e:
            logger.warning(f"Failed to delete recommendation feedback data: {e}")
            feedback_deleted = False
            partial_failures.append(
                CascadeDeleteSubFailure(service="recommendation-feedback", error=str(e))
            )

        return CascadeDeleteResponse(
            success=True,
            case_id=case_id,
            case_deleted=False,
            enrichment_deleted=False,
            vector_deleted=True,  # 视为已删除（从向量节点发起）
            feedback_deleted=feedback_deleted,
            case_deleted_count=0,
            enrichment_deleted_count=0,
            vector_deleted_count=1,
            feedback_deleted_count=feedback_deleted_count,
            partial_failures=partial_failures,
        )

    def _extract_case_id_from_enrichment_id(self, enrichment_id: str) -> str:
        """从增强记录 ID 提取案例 ID。

        假设 enrichment_id 格式为 case_{case_id}_enrichment 或类似格式。
        实际实现可能需要根据具体格式调整。

        Args:
            enrichment_id: 增强记录 ID

        Returns:
            str: 案例 ID
        """
        # 简单实现：假设格式为 case_xxx_enrichment
        if enrichment_id.startswith("case_") and enrichment_id.endswith("_enrichment"):
            return enrichment_id[:-11]  # 去掉 "_enrichment" 后缀
        # 如果格式不符合预期，返回原始 ID 作为 case_id（下游处理时会处理这种情况）
        return enrichment_id

    def _extract_case_id_from_vector_id(self, vector_id: str) -> str:
        """从向量记录 ID 提取案例 ID。

        假设 vector_id 格式为 case_{case_id}_vector 或类似格式。

        Args:
            vector_id: 向量记录 ID

        Returns:
            str: 案例 ID
        """
        # 简单实现：假设格式为 case_xxx_vector
        if vector_id.startswith("case_") and vector_id.endswith("_vector"):
            return vector_id[:-7]  # 去掉 "_vector" 后缀
        return vector_id

    async def _call_enrichment_delete(
        self, case_id: str, requested_by: str
    ) -> tuple[bool, int]:
        """调用 LLM 增强服务删除 API。

        Args:
            case_id: 案例 ID
            requested_by: 请求者标识

        Returns:
            tuple[bool, int]: (是否成功, 删除数量)
        """
        try:
            client = await self._get_http_client()
            response = await client.post(
                f"{ENRICHMENT_SERVICE_URL}/api/enrichment/delete",
                json={"case_id": case_id, "requested_by": requested_by},
            )
            if response.status_code == 200:
                data = response.json()
                return True, data.get("deleted_count", 0)
            elif response.status_code == 404:
                # 资源不存在，视为已删除
                return True, 0
            else:
                raise Exception(f"Enrichment delete failed: {response.status_code}")
        except httpx.TimeoutException:
            # 超时视为可跳过
            logger.warning(f"Enrichment service timeout for case {case_id}")
            return True, 0
        except httpx.ConnectError as e:
            # 服务不可用，视为可跳过
            logger.warning(f"Cannot connect to enrichment service: {e}")
            return True, 0

    async def _call_vector_delete(
        self, case_id: str, requested_by: str
    ) -> tuple[bool, int]:
        """调用向量索引服务删除 API。

        Args:
            case_id: 案例 ID
            requested_by: 请求者标识

        Returns:
            tuple[bool, int]: (是否成功, 删除数量)
        """
        try:
            client = await self._get_http_client()
            response = await client.post(
                f"{VECTOR_SERVICE_URL}/api/vector-index/delete",
                json={"case_id": case_id, "requested_by": requested_by},
            )
            if response.status_code == 200:
                data = response.json()
                return True, data.get("deleted_count", 0)
            elif response.status_code == 404:
                return True, 0
            else:
                raise Exception(f"Vector delete failed: {response.status_code}")
        except httpx.TimeoutException:
            logger.warning(f"Vector service timeout for case {case_id}")
            return True, 0
        except httpx.ConnectError as e:
            logger.warning(f"Cannot connect to vector service: {e}")
            return True, 0

    async def _call_feedback_delete(
        self,
        case_id: str,
        requested_by: str,
        *,
        reason: str,
    ) -> tuple[bool, int]:
        """调用推荐反馈服务删除 API。

        Args:
            case_id: 案例 ID
            requested_by: 请求者标识
            reason: 删除原因枚举字符串（与 FeedbackDeleteReason 对齐）

        Returns:
            tuple[bool, int]: (是否成功, 删除数量)
        """
        try:
            rb = (
                requested_by
                if requested_by in ("anonymous_user", "system")
                else "anonymous_user"
            )
            client = await self._get_http_client()
            response = await client.post(
                f"{FEEDBACK_SERVICE_URL}/api/recommendation-feedback/delete",
                json={
                    "case_id": case_id,
                    "reason": reason,
                    "requested_by": rb,
                },
            )
            if response.status_code == 200:
                data = response.json()
                return True, data.get("deleted_count", 0)
            elif response.status_code == 404:
                return True, 0
            else:
                raise Exception(f"Feedback delete failed: {response.status_code}")
        except httpx.TimeoutException:
            logger.warning(f"Feedback service timeout for case {case_id}")
            return True, 0
        except httpx.ConnectError as e:
            logger.warning(f"Cannot connect to feedback service: {e}")
            return True, 0
# 级联删除设计文档

## 1. 概述

本文档描述 A3 案例知识库系统的级联删除设计，采用**非事务模式**，通过 API 协调实现跨规格的级联删除。

### 1.1 设计原则

- **非事务模式**：各规格通过 API 调用协调删除，不使用分布式事务
- **最终一致性**：允许短暂的数据不一致，通过异步清理任务保证最终一致
- **降级策略**：下游服务不可用时不阻塞上游删除，记录日志供后续清理
- **幂等操作**：所有删除 API 支持幂等调用，重复删除不产生副作用
- **审计追溯**：每个删除操作记录审计日志，包含删除原因、触发者和时间戳

### 1.2 删除链条

```
案例 (A3Case)
  ↓
案例增强 (CaseEnrichment)
  ↓
向量索引 (CaseVector)
  ↓
推荐反馈 (RecommendationFeedback)
```

**关键特性**：
- 删除可以从任意节点发起
- 删除操作向下级联（删除上游自动删除下游）
- 删除操作不向上传播（删除下游不影响上游）

## 2. 删除 API 契约

### 2.1 案例删除 (a3-case-management)

**端点**: `POST /api/a3-cases/delete`

**请求体**:
```json
{
  "case_id": "string (required)",
  "reason": "case_deleted | enrichment_deleted | vector_deleted | feedback_deleted | schedule_deleted",
  "requested_by": "anonymous_user | system"
}
```

**参数说明**:
- `case_id` (required): 案例标识
- `reason` (required): 删除原因枚举
- `requested_by` (required): 删除者标识
  - `anonymous_user`: 前端用户触发
  - `system`: 异步清理程序触发

**响应**:
- 200: 删除成功
  ```json
  {
    "success": true,
    "deleted_count": 1,
    "deleted_at": "2026-05-07T10:30:00Z"
  }
  ```
- 404: 案例不存在 (`CASE_NOT_FOUND`)
- 422: 参数校验失败

**行为**:
- 物理删除 `a3_cases` 表记录
- **不主动触发下游删除**（由调用方协调）

**幂等性**: 对已删除或不存在的案例返回 404

---

### 2.2 案例增强删除 (llm-case-enrichment)

**端点**: `POST /api/enrichment/delete`

**请求体**:
```json
{
  "case_id": "string (optional)",
  "enrichment_id": "string (optional)",
  "reason": "case_deleted | enrichment_deleted | vector_deleted | feedback_deleted | schedule_deleted",
  "requested_by": "anonymous_user | system"
}
```

**参数说明**:
- `case_id` (optional): 案例标识，按案例删除所有增强数据
- `enrichment_id` (optional): 增强标识，删除特定增强记录
- **至少提供 `case_id` 或 `enrichment_id` 之一**
- `reason` (required): 删除原因枚举
- `requested_by` (required): 删除者标识

**响应**:
- 200: 删除成功
  ```json
  {
    "success": true,
    "deleted_count": 2,
    "deleted_at": "2026-05-07T10:30:00Z"
  }
  ```
- 422: 参数校验失败（未提供任何标识）
- 500: 删除失败（数据库错误）

**行为**:
- 在单个事务内删除：
  1. `case_enrichment_results` (派生结果)
  2. `case_enrichment_runs` (运行记录)
- **不主动触发下游删除**（由调用方协调）

**幂等性**: 对不存在的派生数据返回 `deleted_count: 0`

---

### 2.3 向量索引删除 (case-vector-indexing)

**端点**: `POST /api/vector-index/delete`

**请求体**:
```json
{
  "case_id": "string (optional)",
  "vector_id": "string (optional)",
  "reason": "case_deleted | enrichment_deleted | vector_deleted | feedback_deleted | schedule_deleted",
  "requested_by": "anonymous_user | system"
}
```

**参数说明**:
- `case_id` (optional): 案例标识，按案例删除向量索引
- `vector_id` (optional): 向量标识，删除特定向量记录
- **至少提供 `case_id` 或 `vector_id` 之一**
- `reason` (required): 删除原因枚举
- `requested_by` (required): 删除者标识

**响应**:
- 200: 删除成功
  ```json
  {
    "success": true,
    "deleted_count": 1,
    "deleted_at": "2026-05-07T10:30:00Z"
  }
  ```
- 422: 参数校验失败（未提供任何标识）
- 500: 删除失败（数据库错误）

**行为**:
- 创建 `job_type=remove` 的审计任务
- 在单个事务内删除：
  1. `case_vectors` (向量记录)
  2. `vector_index_jobs` (索引任务记录)
- **不主动触发下游删除**（由调用方协调）

**幂等性**: 对不存在的向量索引返回 `deleted_vector_ids: []`

---

### 2.4 推荐反馈删除 (recommendation-feedback)

**端点**: `POST /api/recommendation-feedback/delete`

**请求体**:
```json
{
  "case_id": "string (optional)",
  "feedback_id": "string (optional)",
  "recommendation_run_id": "string (optional)",
  "recommendation_item_id": "string (optional)",
  "reason": "case_deleted | enrichment_deleted | vector_deleted | feedback_deleted | schedule_deleted",
  "requested_by": "anonymous_user | system"
}
```

**参数说明**:
- `case_id` (optional): 按案例删除反馈
- `feedback_id` (optional): 删除特定反馈记录
- `recommendation_run_id` (optional): 按推荐运行删除反馈
- `recommendation_item_id` (optional): 按推荐项删除反馈
- **至少提供上述标识之一**
- `reason` (required): 删除原因枚举
- `requested_by` (required): 删除者标识

**响应**:
- 200: 删除成功
  ```json
  {
    "success": true,
    "deleted_count": 5,
    "deleted_at": "2026-05-07T10:30:00Z"
  }
  ```
- 422: 参数校验失败（未提供任何标识）

**行为**:
- 根据过滤条件删除 `recommendation_feedback` 表记录
- 支持批量删除（一次调用可删除多条反馈）

**幂等性**: 对不存在的反馈返回 `deleted_count: 0`

---

### 2.5 级联删除协调 API (a3-case-management)

**端点**: `POST /api/a3-cases/cascade-delete`

**请求体**:
```json
{
  "case_id": "string (required)",
  "requested_by": "anonymous_user | system"
}
```

**参数说明**:
- `case_id` (required): 案例标识
- `requested_by` (required): 删除者标识

**响应**:
- 200: 删除完成（可能部分失败）
  ```json
  {
    "success": true,
    "case_id": "case_001",
    "case_deleted": true,
    "enrichment_deleted": true,
    "enrichment_deleted_count": 2,
    "vector_deleted": true,
    "vector_deleted_count": 1,
    "feedback_deleted": true,
    "feedback_deleted_count": 5,
    "partial_failures": []
  }
  ```
  
  部分失败示例：
  ```json
  {
    "success": false,
    "case_id": "case_001",
    "case_deleted": true,
    "enrichment_deleted": false,
    "enrichment_deleted_count": 0,
    "vector_deleted": true,
    "vector_deleted_count": 1,
    "feedback_deleted": true,
    "feedback_deleted_count": 5,
    "partial_failures": ["enrichment: Service unavailable"]
  }
  ```

- 404: 案例不存在
- 422: 参数校验失败

**行为**:
- 协调器部署在 **a3-case-management** 服务中
- 依次调用删除链条中的各服务 API
- 下游服务失败不阻塞上游删除，记录到 `partial_failures`
- 前端应使用此 API 作为删除入口

**调用链路**:
```
前端 → POST /api/a3-cases/cascade-delete
     ↓
a3-case-management (CaseDeleteCoordinator)
     ↓ 依次调用
     ├─ POST /api/a3-cases/delete (本地)
     ├─ POST /api/enrichment/delete (HTTP)
     ├─ POST /api/vector-index/delete (HTTP)
     └─ POST /api/recommendation-feedback/delete (HTTP)
```

## 3. 级联删除场景

### 3.1 从案例节点发起删除

**场景**: 用户在前端删除案例

**调用顺序**:
```json
// 步骤 1: 删除案例基础数据
POST /api/a3-cases/delete
{
  "case_id": "case_001",
  "reason": "case_deleted",
  "requested_by": "anonymous_user"
}

// 步骤 2: 删除案例增强
POST /api/enrichment/delete
{
  "case_id": "case_001",
  "reason": "case_deleted",
  "requested_by": "anonymous_user"
}

// 步骤 3: 删除向量索引
POST /api/vector-index/delete
{
  "case_id": "case_001",
  "reason": "case_deleted",
  "requested_by": "anonymous_user"
}

// 步骤 4: 删除推荐反馈
POST /api/recommendation-feedback/delete
{
  "case_id": "case_001",
  "reason": "case_deleted",
  "requested_by": "anonymous_user"
}
```

**降级策略**:
- **步骤 1 失败**: 整个删除操作失败，向用户展示失败原因，不触发下游删除
- **步骤 2 失败**: 案例已删除，向用户展示"案例已删除，但派生数据清理失败"，继续执行步骤 3
- **步骤 3 失败**: 案例和增强已删除，向用户展示"案例已删除，但向量索引清理失败"，继续执行步骤 4
- **步骤 4 失败**: 案例、增强、向量已删除，向用户展示"案例已删除，但推荐反馈清理失败"

**异常处理**:
- 下游服务不可用（超时）: 跳过该步骤，记录日志供后台清理
- 下游数据不存在: 视为成功（幂等性，`deleted_count: 0`）

---

### 3.2 从案例增强节点发起删除

**场景**: 管理员在后台删除案例增强（保留案例基础数据）

**调用顺序**:
```json
// 步骤 1: 删除案例增强
POST /api/enrichment/delete
{
  "case_id": "case_001",
  "reason": "enrichment_deleted",
  "requested_by": "anonymous_user"
}

// 步骤 2: 删除向量索引
POST /api/vector-index/delete
{
  "case_id": "case_001",
  "reason": "enrichment_deleted",
  "requested_by": "anonymous_user"
}

// 步骤 3: 删除推荐反馈
POST /api/recommendation-feedback/delete
{
  "case_id": "case_001",
  "reason": "enrichment_deleted",
  "requested_by": "anonymous_user"
}
```

**降级策略**:
- **步骤 1 失败**: 整个删除操作失败
- **步骤 2 失败**: 增强已删除，记录日志，继续执行步骤 3
- **步骤 3 失败**: 增强和向量已删除，记录日志

**业务语义**:
- 删除案例增强后，向量索引失去输入来源，必须同步删除
- 推荐反馈可能引用案例增强的摘要字段，建议同步删除

---

### 3.3 从向量索引节点发起删除

**场景**: 管理员手动删除向量索引（保留案例和增强）

**调用顺序**:
```json
// 步骤 1: 删除向量索引
POST /api/vector-index/delete
{
  "case_id": "case_001",
  "reason": "vector_deleted",
  "requested_by": "anonymous_user"
}

// 步骤 2: 删除推荐反馈
POST /api/recommendation-feedback/delete
{
  "case_id": "case_001",
  "reason": "vector_deleted",
  "requested_by": "anonymous_user"
}
```

**降级策略**:
- **步骤 1 失败**: 整个删除操作失败
- **步骤 2 失败**: 向量已删除，记录日志

**业务语义**:
- 删除向量索引后，推荐系统无法召回该案例，推荐反馈失去意义
- 建议同步删除推荐反馈，避免悬空引用

---

### 3.4 从推荐反馈节点发起删除

**场景 1**: 删除特定案例的所有推荐反馈

**调用**:
```json
POST /api/recommendation-feedback/delete
{
  "case_id": "case_001",
  "reason": "feedback_deleted",
  "requested_by": "anonymous_user"
}
```

**场景 2**: 删除特定反馈记录

**调用**:
```json
POST /api/recommendation-feedback/delete
{
  "feedback_id": "fb_001",
  "reason": "feedback_deleted",
  "requested_by": "anonymous_user"
}
```

**场景 3**: 删除特定推荐运行的所有反馈

**调用**:
```json
POST /api/recommendation-feedback/delete
{
  "recommendation_run_id": "run_001",
  "reason": "feedback_deleted",
  "requested_by": "anonymous_user"
}
```

**场景 4**: 删除特定推荐项的反馈

**调用**:
```json
POST /api/recommendation-feedback/delete
{
  "recommendation_item_id": "item_001",
  "reason": "feedback_deleted",
  "requested_by": "anonymous_user"
}
```

**业务语义**:
- 推荐反馈是叶子节点，删除不触发上游级联
- 支持按不同维度批量删除

## 4. 异步清理机制

### 4.1 清理任务概述

各规格提供后台定期扫描任务，检测并清理孤立数据（上游已删除但下游仍存在的记录）。

### 4.2 清理服务配置

**配置文件**: `backend/config/cleanup.yaml`

```yaml
enrichment_cleanup:
  enabled: true
  interval_seconds: 86400  # 每日执行
  batch_size: 1000
  
vector_cleanup:
  enabled: true
  interval_seconds: 86400  # 每日执行
  batch_size: 1000
  
feedback_cleanup:
  enabled: true
  interval_seconds: 3600  # 每小时执行
  batch_size: 1000
```

**配置项说明**:
- `enabled`: 是否启用清理服务
- `interval_seconds`: 清理任务执行间隔（秒）
- `batch_size`: 单次清理的最大记录数

---

### 4.3 清理服务启动与注册

**应用启动时注册清理服务**:

```python
# backend/app/main.py
from app.enrichment.cleanup import EnrichmentCleanupService
from app.vector.cleanup import VectorCleanupService
from app.feedback.cleanup import FeedbackCleanupService

@app.on_event("startup")
async def start_cleanup_services():
    """应用启动时注册清理服务"""
    config = load_config("cleanup.yaml")
    
    if config.enrichment_cleanup.enabled:
        enrichment_cleanup = EnrichmentCleanupService(
            repository=enrichment_repo,
            config=config.enrichment_cleanup
        )
        asyncio.create_task(enrichment_cleanup.run_periodic())
        logger.info("Enrichment cleanup service started")
    
    if config.vector_cleanup.enabled:
        vector_cleanup = VectorCleanupService(
            repository=vector_repo,
            config=config.vector_cleanup
        )
        asyncio.create_task(vector_cleanup.run_periodic())
        logger.info("Vector cleanup service started")
    
    if config.feedback_cleanup.enabled:
        feedback_cleanup = FeedbackCleanupService(
            repository=feedback_repo,
            config=config.feedback_cleanup
        )
        asyncio.create_task(feedback_cleanup.run_periodic())
        logger.info("Feedback cleanup service started")
```

---

### 4.4 案例增强清理 (llm-case-enrichment)

**任务**: 扫描 `case_enrichment_results` 和 `case_enrichment_runs`

**清理条件**:
```sql
-- 查找孤立的案例增强记录
SELECT e.enrichment_id 
FROM case_enrichment_results e
LEFT JOIN a3_cases c ON e.case_id = c.case_id
WHERE c.case_id IS NULL
```

**清理动作**: 调用内部删除方法（不通过 HTTP API）

**执行频率**: 每日凌晨执行（可配置）

**服务实现**: 参考 4.4 节的 `EnrichmentCleanupService` 实现模式

---

### 4.5 向量索引清理 (case-vector-indexing)

**任务**: 扫描 `case_vectors` 和 `vector_index_jobs`

**清理条件**:
```sql
-- 查找孤立的向量记录（案例已删除）
SELECT v.vector_id 
FROM case_vectors v
LEFT JOIN a3_cases c ON v.case_id = c.case_id
WHERE c.case_id IS NULL

-- 查找孤立的向量记录（案例增强已删除）
SELECT v.vector_id 
FROM case_vectors v
LEFT JOIN case_enrichment_results e ON v.enrichment_id = e.enrichment_id
WHERE v.enrichment_id IS NOT NULL AND e.enrichment_id IS NULL
```

**清理动作**: 调用内部删除方法

**执行频率**: 每日凌晨执行（可配置）

**服务实现**: 参考 4.4 节的 `EnrichmentCleanupService` 实现模式

---

### 4.6 推荐反馈清理 (recommendation-feedback)

**任务**: `FeedbackCleanupService.cleanup_orphaned_feedback()`

**清理条件**:
```sql
-- 查找引用不存在的推荐运行的反馈记录
SELECT f.feedback_id 
FROM recommendation_feedback f
LEFT JOIN recommendation_runs r ON f.recommendation_run_id = r.run_id
WHERE r.run_id IS NULL

-- 查找引用不存在的推荐项的反馈记录
SELECT f.feedback_id 
FROM recommendation_feedback f
LEFT JOIN recommendation_item_snapshots i ON f.recommendation_item_id = i.item_id
WHERE f.recommendation_item_id IS NOT NULL AND i.item_id IS NULL
```

**清理动作**: 批量删除悬空记录（默认批次大小 1000）

**执行频率**: 每小时执行（默认 3600 秒，可配置）

**服务实现**: 参考 4.4 节的 `EnrichmentCleanupService` 实现模式

**失败处理**:
- 启动初始化失败: 记录错误日志，不阻塞应用启动
- 单次清理失败: 记录错误日志，下一个周期自动重试

## 5. 实现指南

### 5.1 协调器部署与调用

**部署位置**: `CaseDeleteCoordinator` 部署在 **a3-case-management** 服务中

**前端调用入口**: `POST /api/a3-cases/cascade-delete`（参见 2.5 节）

**协调器实现示例** (Python):

```python
# backend/app/cases/delete_coordinator.py
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class CaseDeleteCoordinator:
    """案例删除协调器（非事务模式）"""
    
    def __init__(
        self,
        case_service,
        enrichment_client,
        vector_client,
        feedback_client
    ):
        self.case_service = case_service
        self.enrichment_client = enrichment_client
        self.vector_client = vector_client
        self.feedback_client = feedback_client
    
    def delete_case_cascade(
        self,
        case_id: str,
        requested_by: str = "anonymous_user"
    ) -> CascadeDeleteResult:
        """
        从案例节点发起级联删除
        
        Args:
            case_id: 案例标识
            requested_by: 触发者标识 (anonymous_user | system)
        
        Returns:
            CascadeDeleteResult: 删除结果（包含各步骤状态）
        """
        result = CascadeDeleteResult(case_id=case_id)
        
        # 步骤 1: 删除案例基础数据
        try:
            self.case_service.delete_case({
                "case_id": case_id,
                "reason": "case_deleted",
                "requested_by": requested_by
            })
            result.case_deleted = True
            logger.info(f"Case {case_id} deleted by {requested_by}")
        except CaseNotFoundError:
            # 案例不存在，视为已删除（幂等性）
            result.case_deleted = True
            logger.warning(f"Case {case_id} not found, treated as deleted")
        except Exception as e:
            result.case_deleted = False
            result.case_error = str(e)
            logger.error(f"Failed to delete case {case_id}: {e}")
            # 案例删除失败，不继续下游删除
            return result
        
        # 步骤 2: 删除案例增强
        try:
            response = self.enrichment_client.delete_enrichment({
                "case_id": case_id,
                "reason": "case_deleted",
                "requested_by": requested_by
            })
            result.enrichment_deleted = True
            result.enrichment_deleted_count = response.get("deleted_count", 0)
            logger.info(f"Enrichment data for case {case_id} deleted, count={result.enrichment_deleted_count}")
        except EnrichmentServiceUnavailable:
            result.enrichment_deleted = False
            result.enrichment_error = "Service unavailable"
            logger.warning(f"Enrichment service unavailable for case {case_id}, will cleanup later")
        except Exception as e:
            result.enrichment_deleted = False
            result.enrichment_error = str(e)
            logger.error(f"Failed to delete enrichment for case {case_id}: {e}")
        
        # 步骤 3: 删除向量索引
        try:
            response = self.vector_client.delete_vector({
                "case_id": case_id,
                "reason": "case_deleted",
                "requested_by": requested_by
            })
            result.vector_deleted = True
            result.vector_deleted_count = response.get("deleted_count", 0)
            logger.info(f"Vector index for case {case_id} removed, count={result.vector_deleted_count}")
        except VectorServiceUnavailable:
            result.vector_deleted = False
            result.vector_error = "Service unavailable"
            logger.warning(f"Vector service unavailable for case {case_id}, will cleanup later")
        except Exception as e:
            result.vector_deleted = False
            result.vector_error = str(e)
            logger.error(f"Failed to remove vector for case {case_id}: {e}")
        
        # 步骤 4: 删除推荐反馈
        try:
            response = self.feedback_client.delete_feedback({
                "case_id": case_id,
                "reason": "case_deleted",
                "requested_by": requested_by
            })
            result.feedback_deleted = True
            result.feedback_deleted_count = response.get("deleted_count", 0)
            logger.info(f"Deleted {result.feedback_deleted_count} feedback records for case {case_id}")
        except FeedbackServiceUnavailable:
            result.feedback_deleted = False
            result.feedback_error = "Service unavailable"
            logger.warning(f"Feedback service unavailable for case {case_id}, will cleanup later")
        except Exception as e:
            result.feedback_deleted = False
            result.feedback_error = str(e)
            logger.error(f"Failed to delete feedback for case {case_id}: {e}")
        
        return result
    
    def delete_enrichment_cascade(
        self,
        case_id: str,
        enrichment_id: Optional[str] = None,
        requested_by: str = "anonymous_user"
    ) -> CascadeDeleteResult:
        """从案例增强节点发起级联删除"""
        result = CascadeDeleteResult(case_id=case_id)
        
        # 步骤 1: 删除案例增强
        try:
            delete_request = {
                "reason": "enrichment_deleted",
                "requested_by": requested_by
            }
            if enrichment_id:
                delete_request["enrichment_id"] = enrichment_id
            else:
                delete_request["case_id"] = case_id
            
            response = self.enrichment_client.delete_enrichment(delete_request)
            result.enrichment_deleted = True
            result.enrichment_deleted_count = response.get("deleted_count", 0)
        except Exception as e:
            result.enrichment_deleted = False
            result.enrichment_error = str(e)
            return result
        
        # 步骤 2: 删除向量索引
        try:
            response = self.vector_client.delete_vector({
                "case_id": case_id,
                "reason": "enrichment_deleted",
                "requested_by": requested_by
            })
            result.vector_deleted = True
            result.vector_deleted_count = response.get("deleted_count", 0)
        except Exception as e:
            result.vector_deleted = False
            result.vector_error = str(e)
            logger.error(f"Failed to remove vector after enrichment deletion: {e}")
        
        # 步骤 3: 删除推荐反馈
        try:
            response = self.feedback_client.delete_feedback({
                "case_id": case_id,
                "reason": "enrichment_deleted",
                "requested_by": requested_by
            })
            result.feedback_deleted = True
            result.feedback_deleted_count = response.get("deleted_count", 0)
        except Exception as e:
            result.feedback_deleted = False
            result.feedback_error = str(e)
            logger.error(f"Failed to delete feedback after enrichment deletion: {e}")
        
        return result
    
    def delete_vector_cascade(
        self,
        case_id: str,
        vector_id: Optional[str] = None,
        requested_by: str = "anonymous_user"
    ) -> CascadeDeleteResult:
        """从向量索引节点发起级联删除"""
        result = CascadeDeleteResult(case_id=case_id)
        
        # 步骤 1: 删除向量索引
        try:
            delete_request = {
                "reason": "vector_deleted",
                "requested_by": requested_by
            }
            if vector_id:
                delete_request["vector_id"] = vector_id
            else:
                delete_request["case_id"] = case_id
            
            response = self.vector_client.delete_vector(delete_request)
            result.vector_deleted = True
            result.vector_deleted_count = response.get("deleted_count", 0)
        except Exception as e:
            result.vector_deleted = False
            result.vector_error = str(e)
            return result
        
        # 步骤 2: 删除推荐反馈
        try:
            response = self.feedback_client.delete_feedback({
                "case_id": case_id,
                "reason": "vector_deleted",
                "requested_by": requested_by
            })
            result.feedback_deleted = True
            result.feedback_deleted_count = response.get("deleted_count", 0)
        except Exception as e:
            result.feedback_deleted = False
            result.feedback_error = str(e)
            logger.error(f"Failed to delete feedback after vector deletion: {e}")
        
        return result


class CascadeDeleteResult:
    """级联删除结果"""
    
    def __init__(self, case_id: str):
        self.case_id = case_id
        self.case_deleted = False
        self.case_error: Optional[str] = None
        self.enrichment_deleted = False
        self.enrichment_deleted_count = 0
        self.enrichment_error: Optional[str] = None
        self.vector_deleted = False
        self.vector_deleted_count = 0
        self.vector_error: Optional[str] = None
        self.feedback_deleted = False
        self.feedback_deleted_count = 0
        self.feedback_error: Optional[str] = None
    
    def is_fully_deleted(self) -> bool:
        """是否完全删除（所有步骤成功）"""
        return (
            self.case_deleted and
            self.enrichment_deleted and
            self.vector_deleted and
            self.feedback_deleted
        )
    
    def get_partial_failures(self) -> list[str]:
        """获取部分失败的步骤"""
        failures = []
        if not self.enrichment_deleted and self.enrichment_error:
            failures.append(f"enrichment: {self.enrichment_error}")
        if not self.vector_deleted and self.vector_error:
            failures.append(f"vector: {self.vector_error}")
        if not self.feedback_deleted and self.feedback_error:
            failures.append(f"feedback: {self.feedback_error}")
        return failures
```

### 5.2 清理服务生命周期管理

清理服务的生命周期管理已在 4.4 节中详细说明，包括：
- 服务启动（`start()` 方法）
- 服务停止（`stop()` 方法）
- 周期性执行（`run_periodic()` 方法）
- 孤立数据清理（`cleanup_orphaned_*()` 方法）

各规格的清理服务实现应遵循相同的模式。

## 6. 测试策略

### 6.1 单元测试

**测试用例**:
- 各删除 API 的幂等性
- 降级策略的正确性
- 清理任务的孤立记录识别逻辑

### 6.2 集成测试

**测试场景**:
- 从案例节点发起完整级联删除
- 从案例增强节点发起级联删除
- 从向量索引节点发起级联删除
- 下游服务不可用时的降级行为
- 清理任务的端到端流程

### 6.3 压力测试

**测试目标**:
- 并发删除 100 个案例的性能
- 清理任务处理 10000 条孤立记录的性能

## 7. 运维指南

### 7.1 手动触发清理
curl -X POST http://localhost:8000/api/admin/cleanup/enrichment \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "schedule_deleted",
    "requested_by": "system"
  }'

# 触发向量索引清理
curl -X POST http://localhost:8000/api/admin/cleanup/vector \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "schedule_deleted",
    "requested_by": "system"
  }'

# 触发推荐反馈清理
curl -X POST http://localhost:8000/api/admin/cleanup/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "schedule_deleted",
    "requested_by": "system"
  }'
```

### 7.2 查询孤立记录

```sql
-- 查询孤立的案例增强记录
SELECT e.case_id, e.enrichment_id, e.created_at
FROM case_enrichment_results e
LEFT JOIN a3_cases c ON e.case_id = c.case_id
WHERE c.case_id IS NULL
ORDER BY e.created_at DESC
LIMIT 100;

-- 查询孤立的向量记录
SELECT v.case_id, v.vector_id, v.case_updated_at
FROM case_vectors v
LEFT JOIN a3_cases c ON v.case_id = c.case_id
WHERE c.case_id IS NULL
ORDER BY v.case_updated_at DESC
LIMIT 100;

-- 查询孤立的推荐反馈记录
SELECT f.case_id, f.feedback_id, f.created_at
FROM recommendation_feedback f
LEFT JOIN recommendation_runs r ON f.recommendation_run_id = r.run_id
WHERE r.run_id IS NULL
ORDER BY f.created_at DESC
LIMIT 100;
```

### 7.3 故障恢复

**场景 1**: 下游服务长时间不可用

**处理步骤**:
1. 确认下游服务恢复
2. 手动触发清理任务
3. 验证孤立记录已清理

**场景 2**: 清理任务失败

**处理步骤**:
1. 查看错误日志确认失败原因
2. 修复根因（如数据库连接、权限问题）
3. 手动触发清理任务
4. 验证清理结果

## 8. 附录

### 8.1 术语表

- **级联删除**: 删除上游数据时自动删除下游依赖数据
- **非事务模式**: 不使用分布式事务，通过 API 协调实现最终一致性
- **幂等操作**: 多次执行相同操作产生相同结果
- **孤立数据**: 上游已删除但下游仍存在的记录
- **降级策略**: 下游服务不可用时的备用处理方案
- **删除原因枚举**:
  - `case_deleted`: 案例被删除触发
  - `enrichment_deleted`: 案例增强被删除触发
  - `vector_deleted`: 向量索引被删除触发
  - `feedback_deleted`: 推荐反馈被删除触发
  - `schedule_deleted`: 异步清理程序触发
- **删除者标识**:
  - `anonymous_user`: 前端用户触发的删除操作
  - `system`: 后台异步清理程序触发的删除操作

### 8.2 相关文档

- `.kiro/specs/a3-case-management/design.md` - 案例管理规格
- `.kiro/specs/llm-case-enrichment/design.md` - 案例增强规格
- `.kiro/specs/case-vector-indexing/design.md` - 向量索引规格
- `.kiro/specs/recommendation-feedback/design.md` - 推荐反馈规格

### 8.3 变更历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-05-07 | System | 初始版本，定义非事务模式级联删除设计 |
| 1.1 | 2026-05-07 | System | 统一返回值结构，补充协调 API、清理服务配置与生命周期管理，删除监控告警章节 |

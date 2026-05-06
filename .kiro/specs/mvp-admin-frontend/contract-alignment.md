# 前端设计与后端契约对齐验证

**验证日期**: 2026-05-06  
**契约来源**: `docs/contracts/`  
**前端规格**: `.kiro/specs/mvp-admin-frontend/`

## 验证摘要

前端设计文档已与后端 OpenAPI 契约完成对齐验证，所有 API 端点、请求/响应字段、枚举值和错误码均已确认一致。

## 契约对齐情况

### 1. 案例管理 API（a3-case-management.openapi.yaml）

| 端点 | 前端设计 | 后端契约 | 状态 |
|------|---------|---------|------|
| `POST /api/a3-cases` | ✓ | ✓ | ✅ 已对齐 |
| `GET /api/a3-cases` | ✓ | ✓ | ✅ 已对齐 |
| `GET /api/a3-cases/{case_id}` | ✓ | ✓ | ✅ 已对齐 |
| `PUT /api/a3-cases/{case_id}` | ✓ | ✓ | ✅ 已对齐 |

**关键字段验证**:
- ✅ `problem_description_preview`: 后端返回截断后的预览文本（列表接口）
- ✅ `store_profile`: 嵌套对象，包含 9 个必填字段
- ✅ `context`: 对象类型，包含 `scene` 必填字段和可选扩展字段
- ✅ `solution_steps`: 对象数组，每个元素包含 `order`、`content` 和可选 `extra`
- ✅ `outcome`: 对象类型，包含 `result` 枚举和 `notes` 字段
- ✅ `status`: 枚举值 `draft`, `active`, `archived`
- ✅ `problem_type`: 枚举值 `service`, `quality`, `operation`, `hygiene`, `staffing`, `other`

**分页机制**:
- ✅ Keyset 分页：`cursor_created_at` + `cursor_case_id` 成对提供
- ✅ 响应包含 `next_cursor_created_at`、`next_cursor_case_id`、`has_more`

### 2. 推荐检索 API（cbr-retrieval-recommendation.openapi.yaml）

| 端点 | 前端设计 | 后端契约 | 状态 |
|------|---------|---------|------|
| `POST /api/recommendations/similar-cases` | ✓ | ✓ | ✅ 已对齐 |
| `GET /api/recommendations/runs/{run_id}` | - | ✓ | ⚠️ 前端未使用（可选） |

**关键字段验证**:
- ✅ `recommendation_item_id`: nullable，null 表示运行级推荐
- ✅ `case_reference`: 后端返回预处理的引用对象，包含 `title_preview`、`description_preview`、`brand_summary`、`store_summary`、`filter_summary`、`case_updated_at`
- ✅ `semantic_similarity_score`: nullable，降级时为 null
- ✅ `structured_similarity_score`: nullable，降级时为 null
- ✅ `final_score`: 降级路径下可为 0.0
- ✅ `score_breakdown.final_score_source`: 枚举值 `aggregated`, `default_zero_not_aggregated`
- ✅ `explanation_status`: 枚举值 `generated`, `fallback`, `unavailable`
- ✅ `status`: 枚举值 `succeeded`, `empty`, `degraded`, `failed`
- ✅ `degraded_reason`: 枚举值包含 8 种降级场景

**过滤条件**:
- ✅ `filters` 对象包含 12 个可选字段，与案例管理的查询参数对齐

### 3. 推荐反馈 API（recommendation-feedback.openapi.yaml）

| 端点 | 前端设计 | 后端契约 | 状态 |
|------|---------|---------|------|
| `POST /api/recommendation-feedback` | ✓ | ✓ | ✅ 已对齐 |
| `DELETE /api/recommendation-feedback` | - | ✓ | ⚠️ 前端未使用（可选） |
| `GET /api/recommendation-feedback` | - | ✓ | ⚠️ 前端未使用（可选） |
| `GET /api/recommendation-feedback/runs/{run_id}` | - | ✓ | ⚠️ 前端未使用（可选） |
| `GET /api/recommendation-feedback/stats` | - | ✓ | ⚠️ 前端未使用（可选） |

**关键字段验证**:
- ✅ `recommendation_item_id`: nullable，null 表示运行级反馈
- ✅ `usefulness`: 枚举值 `useful`, `not_useful`, `unknown`
- ✅ `source_channel`: 枚举值 `admin_web`, `api`, `system`（前端固定使用 `admin_web`）
- ✅ `actor_id`: 必填，MVP 阶段使用匿名占位符
- ✅ `target_scope`: 枚举值 `run`, `item`（后端自动推断）
- ⚠️ **字段移除**: 前端设计中的 `rating`（1-5 评分）和 `adoption_status`（采纳状态）在后端契约中不存在，已从需求和设计中移除

## 字段命名规范

所有 API 契约统一使用 **snake_case** 命名规范：
- ✅ 路径参数：`case_id`, `run_id`
- ✅ 查询参数：`brand_id`, `store_id`, `problem_type`, `created_from`, `created_to`
- ✅ 请求/响应字段：`recommendation_run_id`, `recommendation_item_id`, `case_reference`, `final_score`

前端 TypeScript 类型定义应保持 snake_case，不转换为 camelCase，以确保与后端契约完全一致。

## 错误处理对齐

### 案例管理错误码
- ✅ `VALIDATION_ERROR` (422): 字段校验失败
- ✅ `STORE_NOT_FOUND` (400): 门店不存在
- ✅ `CASE_NOT_FOUND` (404): 案例不存在
- ✅ `CASE_STATE_CONFLICT` (409): 状态流转冲突
- ✅ `INTERNAL_ERROR` (500): 系统内部异常

### 推荐检索错误码
- ✅ `VALIDATION_ERROR` (422): 请求校验失败
- ✅ `QUERY_SUMMARIZATION_FAILED` (503): 查询理解失败
- ✅ `VECTOR_SEARCH_FAILED` (503): 向量搜索失败
- ✅ `RECOMMENDATION_RUN_NOT_FOUND` (404): 推荐运行不存在
- ✅ `INTERNAL_ERROR` (500): 系统内部异常

### 推荐反馈错误码
- ✅ `VALIDATION_ERROR` (422): 请求校验失败
- ✅ `FEEDBACK_TARGET_NOT_FOUND` (404): 推荐目标不存在
- ✅ `FEEDBACK_TARGET_MISMATCH` (409): 推荐项不属于指定运行
- ✅ `INTERNAL_ERROR` (500): 系统内部异常

## 契约测试建议

### 单元测试
1. **类型定义测试**: 验证前端 TypeScript 类型与 OpenAPI schema 的一致性
2. **枚举值测试**: 验证所有枚举类型的值集合完全匹配
3. **必填字段测试**: 验证请求/响应的必填字段约束

### 集成测试
1. **Mock Server**: 使用 OpenAPI 规格生成 mock server（如 Prism）进行前端集成测试
2. **契约测试**: 使用 Pact 或类似工具验证前端请求与后端契约的兼容性
3. **错误场景测试**: 验证前端对所有错误码的处理逻辑

## 未来扩展字段

以下字段在前端设计中提及但后端契约中不存在，标记为未来扩展：
- ⚠️ `rating` (1-5 评分): 反馈表单中的评分字段
- ⚠️ `adoption_status` (采纳状态): 反馈表单中的采纳状态字段
- ⚠️ `idempotency_key`: 反馈提交的幂等键（前端可生成但后端契约未定义）

若产品需要这些字段，需先更新后端契约和实现，再同步到前端设计。

## 验证结论

✅ **前端设计与后端契约已完成对齐**，所有核心 API 端点、字段、枚举值和错误码均已验证一致。前端实施可基于 `docs/contracts/` 目录下的 OpenAPI 规格文件生成 TypeScript 类型定义，确保类型安全和契约一致性。

**建议工具**:
- `openapi-typescript`: 从 OpenAPI 规格生成 TypeScript 类型
- `@hey-api/openapi-ts`: 生成类型安全的 API 客户端
- `prism`: 基于 OpenAPI 规格的 mock server

**下一步**:
1. 使用 `openapi-typescript` 生成前端类型定义
2. 在 `frontend/src/api/` 中实现类型安全的 API 客户端
3. 编写契约测试验证前端请求与后端契约的兼容性

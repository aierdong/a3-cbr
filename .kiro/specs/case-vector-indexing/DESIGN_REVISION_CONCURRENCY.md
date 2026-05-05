# 设计修订：并发控制策略调整

## 修订日期
2026-05-05

## 修订原因
原设计错误地将"并发冲突"理解为数据库层面的竞态问题，引入了不必要的复杂性：
- 复杂的任务状态机（`queued` → `running` → `retryable`）
- VectorJobRunner 的排队和重试逻辑
- publish_vector 的数据库唯一约束冲突处理

实际上，正常流程完全异步串行，无并发问题。并发问题仅发生在用户多次点击"重试"按钮的场景。

## 核心调整

### 1. 并发假设与防抖策略（Overview）
- **新增**：在 Overview 部分明确说明并发假设与防抖策略
- **链接**：补充链接到 `llm-case-enrichment/design.md` L57-59，说明异步触发流程
- **明确**：本设计不实现数据库层并发控制，假设 Router 层防抖已保证顺序执行

### 2. Router 层防抖机制（VectorRouter）
- **新增**：在 Implementation Notes 中增加防抖机制说明
- **实现**：使用内存 set 记录正在进行的刷新任务（`case_id`）
- **超时**：120 秒后自动清理过期请求
- **错误码**：返回 409 错误（`VECTOR_REFRESH_IN_PROGRESS`）
- **未来**：MVP 阶段使用内存 set，未来可替换为 redis

### 3. 简化 VectorIndexJob 状态机（System Flows）
- **去掉**：`queued`、`retryable`、`cancelled` 状态
- **保留**：`running`、`succeeded`、`failed`
- **说明**：MVP 阶段刷新任务在请求线程内同步执行，状态直接从 `running` 转换为 `succeeded` 或 `failed`

### 4. 简化 VectorIndexJob 数据模型（Data Models）
- **去掉**：`job_type` 中的 `retry` 枚举值
- **去掉**：`status` 中的 `queued`、`retryable`、`cancelled` 枚举值
- **去掉**：`next_retry_at` 字段
- **保留**：`retry_count` 字段（用户手动重试时递增）

### 5. 简化 VectorRepository.publish_vector（VectorRepository）
- **去掉**：并发冲突处理逻辑（409 重试）
- **新增**：并发说明——Router 层防抖机制已保证同一案例不会并发刷新
- **简化**：若因代码逻辑错误触发唯一约束冲突，直接抛出异常，不实现重试逻辑

### 6. 简化 VectorIndexService（VectorIndexService）
- **去掉**：Postconditions 中的"重试状态"说明
- **新增**：Preconditions 中增加"Router 层防抖已保证同一案例不会并发刷新"

### 7. 更新错误码（Error Handling）
- **新增**：`VECTOR_REFRESH_IN_PROGRESS`（409）
- **去掉**：`VECTOR_CONFLICT`（409）
- **去掉**：Business Logic Errors 中的"不可重试任务"、"状态冲突"、"并发向量发布冲突"

### 8. 新增文件与测试（File Structure）
- **新增**：`backend/app/vector_indexing/deduplicator.py`（Router 层防抖机制）
- **去掉**：`backend/app/vector_indexing/jobs.py`（不再需要排队和重试逻辑）
- **新增**：`tests/vector_indexing/test_deduplicator.py`（防抖机制、超时清理测试）

### 9. 更新组件表（Components and Interfaces）
- **新增**：`RefreshDeduplicator` 组件（API Support 层）
- **去掉**：`VectorJobRunner` 组件
- **更新**：`VectorRouter` 的 Key Dependencies 增加 `RefreshDeduplicator P0`

### 10. 更新集成测试（Testing Strategy）
- **新增**：Router 层防抖测试（并发刷新请求、防抖锁释放）
- **新增**：防抖锁超时测试（120 秒自动清理）
- **去掉**：状态响应中的 `queued`、`retryable` 状态测试
- **简化**：重试端点测试（只允许失败任务重试，不区分"可重试"和"不可重试"）

## 设计原则确认
- **防抖粒度**：当前仅针对"刷新"操作（用户侧发起，不可预测性）
- **超时释放**：120 秒后自动清理过期请求
- **未来扩展**：MVP 阶段不需要为 redis 预留设计

## 影响范围
- **不影响**：上游 `a3-case-management` 和 `llm-case-enrichment` 的契约
- **不影响**：下游 `cbr-retrieval-recommendation` 的向量搜索契约
- **简化**：内部实现复杂度，去掉不必要的状态机和并发控制逻辑

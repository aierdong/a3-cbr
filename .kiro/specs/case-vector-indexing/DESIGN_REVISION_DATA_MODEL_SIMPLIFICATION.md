# 设计修订：数据模型简化 - 移除冗余状态字段

## 修订日期
2026-05-05

## 修订原因
原设计在 `case_vectors` 表中使用双重状态标记，导致数据冗余和逻辑复杂：

1. **双重状态标记**：
   - `is_current` 字段标记哪个是当前有效向量
   - `searchable` 字段标记是否可搜索
   - 搜索需要同时满足 `is_current=true AND searchable=true`

2. **历史向量堆积**：
   - 每次刷新保留旧向量（`is_current=false`）
   - 标记不可检索的向量也保留（`searchable=false`）
   - 向量数据较大（1024 维），存储成本高

3. **逻辑复杂度**：
   - `publish_vector` 需要先更新旧记录再插入新记录
   - 查询需要多个过滤条件
   - 状态组合增加理解成本

## 核心调整

### 1. 数据模型简化

**移除字段**：
- ❌ `is_current` - 不再需要，一个案例只保留一个向量
- ❌ `searchable` - 不再需要，不存在即不可搜索

**索引调整**：
- ❌ 移除 `Partial unique: (case_id) WHERE is_current = true`
- ❌ 移除 `Composite: (case_id, is_current, input_content_hash)`
- ❌ 移除 B-tree 索引：`is_current`, `searchable`
- ✅ 添加 `UNIQUE (case_id)` - 确保一个案例只有一个向量记录
- ✅ 简化复合索引：`(case_id, input_content_hash)` 用于去重检查

### 2. 操作语义调整

**刷新操作**（`refresh_case_vector` 替换 `publish_vector`）：
- 在事务内先删除旧向量（如果存在），再插入新向量
- 返回新向量记录和旧向量 ID（用于审计）
- 事务保证原子性：插入失败时旧向量不会被删除

**删除操作**（`remove_case_vector` 替换 `mark_unsearchable`）：
- 物理删除向量记录
- 返回被删除的 `vector_id`（用于审计）
- 幂等操作：删除不存在的记录返回成功

### 3. 审计日志增强

**`vector_index_jobs` 表新增字段**：
- `old_vector_id` - 刷新或删除时记录被替换/删除的向量 ID
- `old_content_hash` - 记录旧向量的内容哈希，用于追溯
- `new_vector_id` - 刷新成功时记录新向量 ID

### 4. API 调整

**端点重命名**：
```
❌ POST /api/a3-cases/{case_id}/vector-index/unsearchable
✅ POST /api/a3-cases/{case_id}/vector-index/remove
```

**请求/响应调整**：
- `MarkVectorUnsearchableRequest` → `RemoveVectorIndexRequest`
- 删除端点返回 `VectorIndexJobResponse`（不再返回 `VectorIndexStatusResponse`）

### 5. Service 层调整

**`VectorIndexService` 方法变更**：
- ❌ 移除 `mark_case_unsearchable()`
- ✅ 新增 `remove_case_vector()`
- ✅ 更新 `refresh_case_index()` 内部调用 `repository.refresh_case_vector()`

### 6. 查询逻辑简化

**搜索查询**：
```python
# ❌ 原逻辑
# WHERE is_current = true AND searchable = true AND ...

# ✅ 新逻辑
# WHERE ... (只需要业务过滤条件)
# 向量存在即可搜索
```

## 影响的文档

### 已修订文档

1. **design.md**：
   - Goals, This Spec Owns, Manual Revalidation Triggers
   - 向量任务与索引状态流（标题和描述）
   - Requirements Traceability 表格
   - Components 表格
   - VectorRouter API Contract
   - VectorIndexService, VectorRepository 接口
   - CaseVectorRecord, VectorIndexJob 数据模型
   - Physical Data Model（表结构和索引）
   - Data Contracts
   - Error Strategy
   - Unit Tests, Integration Tests, Database Tests

2. **requirements.md**：
   - Boundary Context
   - Req 3.2, 3.4, 4.2, 4.5, 5.2, 6.2

3. **tasks.md**：
   - Task 1.2, 1.3, 2.4, 3.1, 3.2, 3.3, 3.4, 4.2, 5.1, 5.2, 5.3

## 优势总结

✅ **简化了数据模型**：移除 2 个冗余字段，减少状态组合  
✅ **节省了存储空间**：不保留历史向量（1024 维 × N 个版本）  
✅ **降低了查询复杂度**：搜索不需要状态过滤  
✅ **保留了审计能力**：`vector_index_jobs` 记录完整的操作历史  
✅ **提升了语义清晰度**：物理删除比逻辑标记更直观  
✅ **保持了并发安全**：事务保证原子性，防抖机制继续有效

## 迁移策略

对于已有数据（如果存在）：

```sql
-- 1. 清理历史向量，只保留 is_current=true 的记录
DELETE FROM case_vectors WHERE is_current = false;

-- 2. 删除 searchable=false 的记录（已标记不可检索）
DELETE FROM case_vectors WHERE searchable = false;

-- 3. 移除字段
ALTER TABLE case_vectors DROP COLUMN is_current;
ALTER TABLE case_vectors DROP COLUMN searchable;

-- 4. 添加唯一约束
CREATE UNIQUE INDEX idx_case_vectors_case_id_unique ON case_vectors(case_id);

-- 5. 移除旧的 partial unique 索引
DROP INDEX IF EXISTS idx_case_vectors_case_id_is_current_unique;

-- 6. 简化复合索引
DROP INDEX IF EXISTS idx_case_vectors_case_id_is_current_hash;
CREATE INDEX idx_case_vectors_case_id_hash ON case_vectors(case_id, input_content_hash);

-- 7. 增强审计表
ALTER TABLE vector_index_jobs 
  ADD COLUMN old_vector_id VARCHAR(64),
  ADD COLUMN old_content_hash VARCHAR(128),
  ADD COLUMN new_vector_id VARCHAR(64);
```

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 历史数据丢失 | 中 | `vector_index_jobs` 保留完整审计，包括 `old_vector_id` 和 `old_content_hash` |
| 误删除无法恢复 | 低 | 删除操作需要显式调用，有审计记录；可从案例重新生成 |
| 刷新失败后无向量 | 低 | 事务回滚保证原子性；失败时旧向量不会被删除 |
| 并发删除-插入冲突 | 低 | Router 层防抖机制已覆盖 |

## 实施建议

1. **优先级**: P0 - 应在 MVP 实现前调整
2. **原因**: 数据模型变更越早越好，避免后期迁移成本
3. **验证**: 所有单元测试和集成测试需要更新并通过
4. **文档**: 三个核心文档（design.md, requirements.md, tasks.md）已同步更新

## 审批记录

- **提出者**: 用户
- **修订者**: Claude (Opus 4.6)
- **修订日期**: 2026-05-05
- **状态**: 已完成文档修订，待实施

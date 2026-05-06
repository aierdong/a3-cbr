# Research & Design Decisions

## Summary

- **Feature**: `recommendation-feedback`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 上游 `cbr-retrieval-recommendation` 已明确提供 `recommendation_run_id` 和 `recommendation_item_id`，是反馈关联的唯一稳定锚点。
  - 面向一线使用负担，本规格将用户反馈收敛为有用/无用 + 可选备注；评分与采纳不纳入 MVP 采集，不要求自动调权、复杂看板或反馈学习排序。
  - 当前仓库尚无后端代码，设计需要以 planned backend 结构为准，保持 Python + FastAPI + PostgreSQL 的文档契约一致。
  - MVP 简化数据模型，不保存查询快照、过滤条件快照、分值快照或解释状态，只保留核心反馈字段。
  - 运行级反馈使用 `recommendation_item_id = NULL`，推荐项级反馈使用非 NULL 标识。
  - PostgreSQL 15+ 使用 `UNIQUE NULLS NOT DISTINCT` 约束；15 以下版本使用两个部分唯一索引替代。

## Research Log

### 上游推荐契约

- **Context**: 本规格依赖 `cbr-retrieval-recommendation`，必须精确对齐其输出契约。
- **Sources Consulted**: `.kiro/specs/cbr-retrieval-recommendation/requirements.md`、`.kiro/specs/cbr-retrieval-recommendation/design.md`。
- **Findings**:
  - 推荐响应返回 `recommendation_run_id` 和 `recommendation_item_id`，用于下游反馈引用。
  - 推荐运行和推荐项快照保存在上游，本规格只读标识并校验存在性与一致性。
- **Implications**:
  - 反馈表应引用推荐运行和推荐项标识，不复制推荐快照或重新计算推荐结果。
  - MVP 简化数据模型，不保存查询哈希、过滤条件、分值快照或解释状态。

### 产品与路线边界

- **Context**: 反馈闭环容易扩展为学习排序、运营分析和前端体验，需要收敛 MVP 边界。
- **Sources Consulted**: `docs/product-overview.md`、`.kiro/steering/roadmap.md`、`brief.md`。
- **Findings**:
  - MVP 本次收敛后的基础反馈记录：有用/无用、可选备注、推荐运行/项关联、案例关联和审计字段。
  - Roadmap 将反馈闭环放在推荐之后、前端后台之前，说明反馈依赖推荐结果但不拥有 UI。
  - 复杂学习排序、A/B 实验、行业库审核和质量评分回写均在当前边界外。
  - 上游推荐快照允许被删除，本规格需提供删除反馈的 API 和 service。
- **Implications**:
  - 设计只提供提交、删除、查询、基础统计和数据出口。
  - 不新增自动调权任务，不修改推荐排序契约。
  - 不保存查询快照、过滤条件快照、分值快照或解释状态（简化 MVP 数据模型）。

### 现有代码与实现结构

- **Context**: 需要判断是修改现有系统还是为后续实现提供文件结构计划。
- **Sources Consulted**: workspace glob for `backend/**`、前置规格设计文档。
- **Findings**:
  - 当前仓库没有已落地的 `backend` 代码。
  - 前置规格统一规划 `backend/app/<domain>`、FastAPI、Pydantic、SQLAlchemy、Alembic、pytest。
- **Implications**:
  - 本规格应新增 `backend/app/feedback` 模块，并只通过上游公开服务或 repository 读取推荐快照。
  - 文件结构计划需要标注将来创建与集成点，不假设现有实现已存在。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 反馈作为推荐模块子功能 | 在 `retrieval` 内追加反馈表和 API | 距离上游数据近 | 容易把反馈学习排序、推荐运行和反馈写入混在一起 | 拒绝，边界不清 |
| 独立 `feedback` 模块 | 单独拥有反馈实体、提交、删除、查询和统计 | 边界清晰，便于后续分析消费 | 需要读取上游推荐运行和推荐项标识 | 采用 |
| 事件式反馈采集 | 提交反馈后发布事件给分析管道 | 后续扩展强 | MVP 增加基础设施复杂度 | 当前不采用，仅保留数据出口 |

## Design Decisions

### Decision: 独立反馈聚合根

- **Context**: 反馈既关联推荐运行，也可能关联单条推荐项。
- **Alternatives Considered**:
  1. 只在推荐项快照上追加反馈字段。
  2. 建立独立反馈记录，引用推荐运行和推荐项。
- **Selected Approach**: 建立 `RecommendationFeedback` 聚合根，运行级反馈的 `recommendation_item_id` 为 NULL，推荐项级反馈必须引用同一运行下的项。
- **Rationale**: 独立聚合根避免修改上游推荐记录，也支持同一运行下多条推荐项反馈。
- **Trade-offs**: 查询时需要 join 或二次读取推荐标识，但边界更稳定。
- **Follow-up**: 实现时验证推荐项与运行一致性，并设置唯一约束。

### Decision: 简化数据模型，不保存快照

- **Context**: MVP 需要验证推荐是否有用，但不要求复杂质量分析。
- **Alternatives Considered**:
  1. 反馈保存查询哈希、过滤条件、分值快照和解释状态。
  2. 反馈只保存核心字段，不复制推荐快照。
- **Selected Approach**: 反馈只保存推荐运行/项标识、案例标识、有用性、备注和审计字段，不保存查询快照、过滤条件、分值快照或解释状态。
- **Rationale**: 简化 MVP 数据模型，降低存储成本和实现复杂度；后续质量分析可从上游推荐记录读取快照。
- **Trade-offs**: 若上游推荐记录被删除，反馈失去完整上下文；但 MVP 阶段可接受。
- **Follow-up**: 提供删除反馈的 API 和 service，支持案例删除触发和定时清理无效记录。

### Decision: Router 层防抖，不使用幂等键

- **Context**: 需要防止并发重复提交，但不要求复杂幂等机制。
- **Alternatives Considered**:
  1. 使用 `idempotency_key` 字段和数据库唯一约束。
  2. 在 Router 层使用防抖机制（MVP 用 set，未来用 redis）。
- **Selected Approach**: 在 Router 层使用防抖机制，按 `(recommendation_run_id, recommendation_item_id)` 防止并发重复提交。
- **Rationale**: 简化数据模型，避免客户端管理幂等键；Router 层防抖足够满足 MVP 需求。
- **Trade-offs**: MVP 单节点部署使用 set，未来多节点部署需要 redis。
- **Follow-up**: 实现时验证防抖键生成、并发冲突检测和释放机制。

### Decision: PostgreSQL 15+ 唯一约束，15 以下使用部分索引

- **Context**: 运行级反馈的 `recommendation_item_id` 为 NULL，需要唯一约束支持 NULL 值。
- **Alternatives Considered**:
  1. 使用 `recommendation_item_id = NULL` 表示运行级反馈。
  2. 使用 PostgreSQL 15+ 的 `UNIQUE NULLS NOT DISTINCT` 约束。
  3. 使用两个部分唯一索引（15 以下版本）。
- **Selected Approach**: PostgreSQL 15+ 使用 `UNIQUE NULLS NOT DISTINCT`；15 以下使用两个部分唯一索引。
- **Rationale**: NULL 语义清晰，避免哨兵值混淆；PostgreSQL 15+ 原生支持，15 以下使用部分索引替代。
- **Trade-offs**: 15 以下版本需要两个索引，但语义更清晰。
- **Follow-up**: 在 migration 中根据 PostgreSQL 版本选择约束策略。

**PostgreSQL 15 以下版本唯一约束替代方案**:

```sql
-- 1. 处理 recommendation_item_id 不为 NULL 的情况
CREATE UNIQUE INDEX idx_feedback_item_not_null 
ON recommendation_feedback (actor_id, recommendation_run_id, recommendation_item_id)
WHERE recommendation_item_id IS NOT NULL;

-- 2. 处理 recommendation_item_id 为 NULL 的情况（确保每个 run 只有一个 NULL）
CREATE UNIQUE INDEX idx_feedback_run_only 
ON recommendation_feedback (actor_id, recommendation_run_id)
WHERE recommendation_item_id IS NULL;
```

这两个部分唯一索引组合实现了与 `UNIQUE NULLS NOT DISTINCT` 相同的语义：
- 第一个索引确保同一用户对同一推荐运行的同一推荐项只有一条反馈。
- 第二个索引确保同一用户对同一推荐运行只有一条运行级反馈（`recommendation_item_id` 为 NULL）。

### Decision: MVP 只提供基础统计

- **Context**: 产品需要验证推荐是否有用，但不要求复杂看板。
- **Alternatives Considered**:
  1. 只提供明细查询。
  2. 增加轻量聚合 API。
  3. 引入分析看板或实验平台。
- **Selected Approach**: 提供反馈明细、运行反馈查询和基础统计 API。
- **Rationale**: 满足产品验证闭环，同时避免吸收前端 UI 和实验平台职责。
- **Trade-offs**: 复杂维度分析需后续规格扩展。
- **Follow-up**: 统计口径保持简单：数量、有用率与有用性分布。

## Risks & Mitigations

- 上游推荐项标识契约变更 — 将其列为 revalidation trigger，并在提交时校验运行与推荐项一致性。
- 反馈备注泄露敏感门店信息 — 限制长度、日志脱敏，统计接口不返回完整备注。
- 重复提交产生脏数据 — 使用 Router 层防抖机制（MVP 用 set，未来用 redis）和数据库唯一约束。
- 反馈链路影响推荐体验 — 失败返回稳定错误，不触发推荐流程回滚或重排。
- 上游推荐记录被删除 — 提供删除反馈的 API 和 service，支持案例删除触发和定时清理无效记录。

## References

- `.kiro/specs/recommendation-feedback/brief.md` — 反馈闭环发现上下文。
- `.kiro/specs/cbr-retrieval-recommendation/requirements.md` — 上游推荐运行和推荐项标识要求。
- `.kiro/specs/cbr-retrieval-recommendation/design.md` — 推荐运行与推荐项快照契约。
- `docs/mvp-product.md` — MVP 反馈流程和技术栈边界（补充来源）。
- `.kiro/steering/roadmap.md` — 规格依赖顺序和边界策略。

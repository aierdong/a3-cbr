# Research & Design Decisions

## Summary

- **Feature**: `recommendation-feedback`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 上游 `cbr-retrieval-recommendation` 已明确提供 `recommendation_run_id` 和 `recommendation_item_id`，并保存推荐运行与推荐项快照，是反馈关联的唯一稳定锚点。
  - MVP 产品文档只要求有用/无用、简单评分、是否采纳和查询命中记录，不要求自动调权、复杂看板或反馈学习排序。
  - 当前仓库尚无后端代码，设计需要以 planned backend 结构为准，保持 Python + FastAPI + PostgreSQL 的文档契约一致。

## Research Log

### 上游推荐契约

- **Context**: 本规格依赖 `cbr-retrieval-recommendation`，必须精确对齐其输出契约。
- **Sources Consulted**: `.kiro/specs/cbr-retrieval-recommendation/requirements.md`、`.kiro/specs/cbr-retrieval-recommendation/design.md`。
- **Findings**:
  - 推荐响应返回 `recommendation_run_id` 和 `recommendation_item_id`，用于下游反馈引用。
  - 推荐运行保存查询哈希、应用过滤条件、候选数量、返回数量、降级状态和模型元数据。
  - 推荐项快照保存 `case_id`、`vector_id`、排序、向量相似度、语义相似度、结构化局部相似度、业务参数分、最终聚合分、解释状态和候选案例版本。
- **Implications**:
  - 反馈表应引用推荐运行和推荐项，不直接重新计算或解释推荐结果。
  - 为后续分析需要复制必要查询与命中快照，避免上游记录变更后反馈失去上下文。

### 产品与路线边界

- **Context**: 反馈闭环容易扩展为学习排序、运营分析和前端体验，需要收敛 MVP 边界。
- **Sources Consulted**: `docs/product-overview.md`、`.kiro/steering/roadmap.md`、`brief.md`。
- **Findings**:
  - MVP 明确要求基础反馈记录：有用/无用、简单评分、是否采纳、查询文本、命中案例和反馈结果。
  - Roadmap 将反馈闭环放在推荐之后、前端后台之前，说明反馈依赖推荐结果但不拥有 UI。
  - 复杂学习排序、A/B 实验、行业库审核和质量评分回写均在当前边界外。
- **Implications**:
  - 设计只提供提交、查询、基础统计和数据出口。
  - 不新增自动调权任务，不修改推荐排序契约。

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
| 独立 `feedback` 模块 | 单独拥有反馈实体、提交、查询和统计 | 边界清晰，便于后续分析消费 | 需要读取上游推荐运行和推荐项快照 | 采用 |
| 事件式反馈采集 | 提交反馈后发布事件给分析管道 | 后续扩展强 | MVP 增加基础设施复杂度 | 当前不采用，仅保留数据出口 |

## Design Decisions

### Decision: 独立反馈聚合根

- **Context**: 反馈既关联推荐运行，也可能关联单条推荐项。
- **Alternatives Considered**:
  1. 只在推荐项快照上追加反馈字段。
  2. 建立独立反馈记录，引用推荐运行和推荐项。
- **Selected Approach**: 建立 `RecommendationFeedback` 聚合根，运行级反馈允许推荐项为空，推荐项级反馈必须引用同一运行下的项。
- **Rationale**: 独立聚合根避免修改上游推荐记录，也支持同一运行下多条推荐项反馈。
- **Trade-offs**: 查询时需要 join 或二次读取推荐快照，但边界更稳定。
- **Follow-up**: 实现时验证推荐项与运行一致性，并设置幂等约束。

### Decision: 保存分析所需快照，不回写上游

- **Context**: 后续召回质量分析需要知道当时查询、过滤、排序和分值。
- **Alternatives Considered**:
  1. 反馈只保存标识，分析时实时读取推荐运行。
  2. 反馈保存必要查询与命中快照。
- **Selected Approach**: 反馈保存查询哈希、可选脱敏或截断查询摘要、应用过滤条件、候选数量、命中案例、排序、向量相似度、语义相似度、结构化局部相似度、业务参数分、最终聚合分和解释状态。
- **Rationale**: 分析结果不受上游记录清理或推荐项版本变化影响，同时不要求上游持久化完整查询原文。
- **Trade-offs**: 存储增加，但 MVP 数据量可控；完整查询原文、完整案例正文和向量数组仍不复制。
- **Follow-up**: 通过隐私测试确认日志和统计不暴露敏感内容。

### Decision: MVP 只提供基础统计

- **Context**: 产品需要验证推荐是否有用，但不要求复杂看板。
- **Alternatives Considered**:
  1. 只提供明细查询。
  2. 增加轻量聚合 API。
  3. 引入分析看板或实验平台。
- **Selected Approach**: 提供反馈明细、运行反馈查询和基础统计 API。
- **Rationale**: 满足产品验证闭环，同时避免吸收前端 UI 和实验平台职责。
- **Trade-offs**: 复杂维度分析需后续规格扩展。
- **Follow-up**: 统计口径保持简单：数量、有用率、平均评分、采纳率。

## Risks & Mitigations

- 上游推荐项标识契约变更 — 将其列为 revalidation trigger，并在提交时校验运行与推荐项一致性。
- 反馈备注泄露敏感门店信息 — 限制长度、日志脱敏，统计接口不返回完整备注。
- 重复提交产生脏数据 — 使用幂等键或同一用户同一推荐目标唯一约束。
- 反馈链路影响推荐体验 — 失败返回稳定错误，不触发推荐流程回滚或重排。

## References

- `.kiro/specs/recommendation-feedback/brief.md` — 反馈闭环发现上下文。
- `.kiro/specs/cbr-retrieval-recommendation/requirements.md` — 上游推荐运行和推荐项标识要求。
- `.kiro/specs/cbr-retrieval-recommendation/design.md` — 推荐运行与推荐项快照契约。
- `docs/mvp-product.md` — MVP 反馈流程和技术栈边界（补充来源）。
- `.kiro/steering/roadmap.md` — 规格依赖顺序和边界策略。

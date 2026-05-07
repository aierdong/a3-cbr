# Research & Design Decisions

## Summary

- **Feature**: `a3-case-management`
- **Discovery Scope**: Simple Addition / New Feature Foundation
- **Key Findings**:
  - 仓库当前没有 `backend/`、`frontend/` 应用代码，案例管理要先搭建后端项目骨架和案例域基础契约。
  - `docs/product-overview.md` 已明确 A3 案例字段与总体方向；`docs/mvp-product.md` 仅补充 MVP 阶段的技术收敛与交付边界。本规格只覆盖案例基础数据，不承接向量、LLM、CBR 和反馈。
  - `roadmap.md` 把本规格列为后续 5 个规格的无依赖前置项，所以字段命名、状态和 API 结果结构必须保持稳定。
  - 门店名称、品牌标识、品牌名称及业态、门店规模、加盟类型、城市、城市规模等检索维度应沉淀为独立门店信息实体。

## Research Log

### 产品与范围边界

- **Context**: brief 要求聚焦 A3 案例数据模型、校验、创建、编辑、详情和列表 API。
- **Sources Consulted**: `.kiro/specs/a3-case-management/brief.md`、`.kiro/steering/roadmap.md`、`docs/product-overview.md`
- **Findings**:
  - A3 案例至少要包含问题描述、门店/品牌、问题类型、上下文、根因、解决步骤、效果、创建时间。
  - 门店/品牌信息同时承担检索过滤职责，完整门店画像还包括业态、门店规模、加盟类型、城市和城市规模等维度。
  - 后续 LLM、embedding、CBR 推荐和反馈规格都依赖案例基础契约。
  - 自动触发、行业库入库、脱敏、质量评分、向量生成和推荐反馈均不属于本规格。
- **Implications**:
  - 设计上要把案例基础数据和 AI 派生字段分开。
  - 门店画像应独立建模，A3 案例通过门店信息关联复用这些基本稳定的检索维度。
  - API 响应要给下游保留稳定标识、过滤字段、状态和更新时间。

### 代码库现状

- **Context**: 设计阶段需要先确定文件结构和实施前置条件。
- **Sources Consulted**: 仓库文件结构检查。
- **Findings**:
  - 目前没有后端应用目录，也没有可复用的既有 API、模型或迁移模式。
  - `.kiro/steering/product.md`、`tech.md`、`structure.md` 未创建，现有 steering 只有 `roadmap.md`。
- **Implications**:
  - 任务计划必须明确包含后端项目骨架、依赖配置、数据库迁移和测试基础。
  - 文件结构按 FastAPI + 分层案例域模块设计，不假设已有应用宿主。

### 技术约束

- **Context**: MVP 文档已经指定技术路线，但本规格不负责下游 AI 或检索职责。
- **Sources Consulted**: `docs/product-overview.md`、`.kiro/steering/roadmap.md`
- **Findings**:
  - 后端采用 Python + FastAPI。
  - 数据层采用 PostgreSQL；pgvector 是后续向量索引规格的约束，不是本规格的数据写入内容。
  - 前端采用 Vue 3，但本规格只定义后端案例 API，页面实现属于 `mvp-admin-frontend`。
- **Implications**:
  - 本设计采用 FastAPI 路由、Pydantic 校验、SQLAlchemy/迁移脚本和 PostgreSQL 表。
  - 不在本规格中创建向量表、embedding 字段、推荐分值或反馈表。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 分层 FastAPI 模块 | Router → Service → Repository → PostgreSQL | 简单、贴合 CRUD、便于任务拆分 | 后续领域变复杂时，需要补充更严格的领域层 | 适合当前基础案例管理 |
| Hexagonal | 以端口和适配器隔离核心领域 | 边界清晰，适合多适配器 | 对当前无既有代码的 MVP 偏重 | 暂不采用完整形态 |
| 单文件 CRUD | 用少量文件快速实现 | 初期速度快 | 字段、校验、API、持久化容易耦合，下游复用成本高 | 不采用 |

## Design Decisions

### Decision: 采用轻量分层模块

- **Context**: 当前功能是案例管理底座，需要稳定契约但避免过度设计。
- **Alternatives Considered**:
  1. 完整 Hexagonal 架构 — 边界强但启动成本高。
  2. 单文件 CRUD — 快但会弱化下游契约稳定性。
- **Selected Approach**: 使用 FastAPI Router、Pydantic Schema、Service、Repository、SQLAlchemy Model 和迁移脚本分层。
- **Rationale**: 这套分层能把输入校验、业务约束、事务持久化和 API 契约清楚分开，同时保持轻量。
- **Trade-offs**: 早期文件数量会比单文件 CRUD 多，但可测试性和下游复用性更好。
- **Follow-up**: 实施时避免为未来 AI 或推荐提前创建空抽象。

### Decision: 案例基础表不包含 AI 派生字段

- **Context**: 后续规格会处理摘要、向量、推荐理由和反馈。
- **Alternatives Considered**:
  1. 在案例表预留 embedding、similarity、feedback 字段。
  2. 仅保存基础业务字段和状态。
- **Selected Approach**: 本规格只保存基础案例字段，保留稳定 `case_id` 和过滤字段供下游关联。
- **Rationale**: 避免上游案例管理被下游检索实现反向影响。
- **Trade-offs**: 下游规格需要建立自己的表或关联记录。
- **Follow-up**: 若下游要求新增基础字段，必须触发本规格和依赖规格重新校验。

### Decision: 将门店检索维度抽为独立门店信息实体

- **Context**: A3 案例原本直接包含门店名称、品牌标识和品牌名称，但列表检索还需要业态、门店规模、加盟类型、城市和城市规模等门店画像字段。这些字段基本稳定，适合按门店维度统一维护。
- **Alternatives Considered**:
  1. 继续把所有门店和品牌字段放在 `A3Case` 表中 — 查询直接但字段会持续膨胀，多个案例会重复保存同一门店画像。
  2. 抽出 `StoreInfo` 独立实体，由 `A3Case` 关联 — 模型边界清晰，过滤字段可扩展，适合后续列表检索。
- **Selected Approach**: 新增 `StoreInfo`（本库**只读镜像表**），保存门店名称、品牌标识、品牌名称、业态、门店规模、加盟类型、城市和城市规模；`A3Case` 只保存 `store_id` 关联；案例创建请求**仅提交 `store_id`**，镜像行由外部同步写入。
- **Rationale**: 门店画像是可复用的基础维度，不属于单个案例内容，且权威归属外部系统。独立镜像表能减少案例表宽度并支撑列表过滤，同时避免案例 API 承担门店主数据写入。
- **Trade-offs**: 列表查询需要关联门店信息表；依赖外部同步及时性；实施时要补齐存在性校验、`STORE_NOT_FOUND` 与集成测试夹具中的镜像种子数据。
- **Follow-up**: 本规格不考虑历史快照；少量门店画像变化按外部同步更新镜像即可。

### Decision: 状态保持 MVP 最小集合

- **Context**: brief 明确不提前承接完整知识库发布审核流。
- **Alternatives Considered**:
  1. 设计完整审核、发布、归档、行业库状态流。
  2. 只提供 `draft`、`active`、`archived` 等基础状态。
- **Selected Approach**: 使用基础可编辑和可用性状态，表达能否编辑、查看和供后续处理。
- **Rationale**: 既能满足案例管理和下游输入需求，也能避免把行业库审核提前塞进本规格。
- **Trade-offs**: 后续审核流需要在独立规格中扩展状态或引入新实体。
- **Follow-up**: 实施时用枚举和状态校验集中维护语义。

### Decision: 级联删除采用协调器非事务模式

- **Context**: 案例删除会影响案例增强、向量索引和推荐反馈，跨规格无法使用单库事务。
- **Alternatives Considered**:
  1. 前端逐个调用各服务删除接口 — 实现分散，失败语义不一致。
  2. 在 `a3-case-management` 内提供统一协调器入口并顺序调用下游清理 API。
- **Selected Approach**: 采用协调器入口 `POST /api/a3-cases/cascade-delete`，由服务端统一编排删除链路与部分失败结果。
- **Rationale**: 统一幂等语义与降级策略，降低联调复杂度，并保持前端删除入口稳定。
- **Trade-offs**: 协调器需要维护下游客户端与可观测日志；短时允许部分失败，通过异步清理达成最终一致。
- **Follow-up**: 与 `docs/cascade-deletion-design.md` 保持同一删除契约（`POST /api/a3-cases/delete`、`POST /api/enrichment/delete`、`POST /api/vector-index/delete`、`POST /api/recommendation-feedback/delete`）。

## Risks & Mitigations

- 字段过早扩张会导致边界漂移 — 以 requirements 的 out-of-scope 和 design 的 Boundary Commitments 作为评审依据。
- 没有既有应用骨架会让任务带上隐含前置条件 — tasks 中显式包含后端项目骨架、配置和迁移基础。
- 下游依赖字段如果不稳定会影响联调 — API 响应固定案例标识、状态、门店信息过滤字段和更新时间，并把变更列为重校验触发器。
  - 问题类型枚举后续可能演进 — 设计为受控枚举或可配置字典，但本规格只交付基础校验。

## References

- `docs/product-overview.md` — 产品愿景、A3 标准步骤和知识沉淀方向。
- `docs/mvp-product.md` — MVP 交付边界与阶段性技术收敛（补充来源）。
- `.kiro/steering/roadmap.md` — 规格拆分、依赖顺序和技术约束。
- `.kiro/specs/a3-case-management/brief.md` — 本功能的问题、范围和边界。

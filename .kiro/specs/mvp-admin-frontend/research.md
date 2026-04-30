# Research & Design Decisions

## Summary

- **Feature**: `mvp-admin-frontend`
- **Discovery Scope**: Simple Addition / Extension
- **Key Findings**:
  - 当前仓库没有 `frontend/` 应用代码，本规格需要规划 Vue 3 前端基础结构。
  - 上游规格已稳定定义案例、推荐和反馈 API；前端应严格消费这些契约，不反向扩大后端数据模型。
  - MVP 验证目标是闭环可操作，不是完整运营后台，因此采用轻量页面、轻量状态和基础表单交互。

## Research Log

### 产品与路线图边界

- **Context**: `docs/product-overview.md` 作为产品权威入口，`docs/mvp-product.md` 在 MVP 阶段收敛“案例入库、结构化、向量检索、相似案例推荐、基础反馈”闭环，并约束前端采用 Vue。
- **Sources Consulted**: `docs/product-overview.md`、`.kiro/steering/roadmap.md`、`.kiro/specs/mvp-admin-frontend/brief.md`。
- **Findings**:
  - 前端后台是 MVP 最后一层验证入口。
  - 经营看板、消息推送、复杂权限、行业库审核和移动端深度适配明确不在范围内。
  - 前端需要展示推荐理由和相似度分值，同时收集基础反馈。
- **Implications**: 设计聚焦三个用户路径：案例管理、检索推荐、反馈提交；不引入复杂菜单体系或设计系统。

### 上游案例管理契约

- **Context**: 前端需要创建、编辑、查看和筛选 A3 案例。
- **Sources Consulted**: `.kiro/specs/a3-case-management/requirements.md`、`.kiro/specs/a3-case-management/design.md`。
- **Findings**:
  - 案例 API 路径为 `POST /api/a3-cases`、`PUT /api/a3-cases/{case_id}`、`GET /api/a3-cases/{case_id}`、`GET /api/a3-cases`。
  - 案例基础字段包括 `case_id`、`problem_description`、品牌/门店字段、`problem_type`、`context`、`root_cause`、`solution_steps`、`outcome`、`tags`、`status`、`created_at`、`updated_at`。
  - 响应不包含向量、推荐分值或反馈信息。
- **Implications**: 前端表单和详情页只映射基础案例字段；编辑表单必须禁止修改 `case_id` 和 `created_at`。

### 推荐与反馈契约

- **Context**: 前端需要提交相似案例检索并对推荐结果反馈。
- **Sources Consulted**: `.kiro/specs/cbr-retrieval-recommendation/requirements.md`、`.kiro/specs/cbr-retrieval-recommendation/design.md`、`.kiro/specs/recommendation-feedback/requirements.md`、`.kiro/specs/recommendation-feedback/design.md`。
- **Findings**:
  - 推荐入口为 `POST /api/recommendations/similar-cases`，响应包含 `recommendation_run_id`、状态、实际过滤条件、查询元数据和有序 `RecommendationItem`。
  - 推荐项包含 `recommendation_item_id`、`case_id`、排序、案例引用、核心步骤、效果摘要、向量相似度、语义相似度、业务参数分、最终聚合分、推荐理由、注意事项和解释状态。
  - 反馈入口为 `POST /api/recommendation-feedback`，支持运行级和推荐项级反馈，字段包括有用性、评分、采纳状态、备注、来源渠道和幂等键。
- **Implications**: 前端展示必须保持后端排序，不本地重排；反馈失败不能隐藏或破坏推荐结果。

### 技术形态与实现约束

- **Context**: 仓库还没有前端实现，需要给任务生成提供可执行结构。
- **Sources Consulted**: `roadmap.md`、上游设计文档和仓库结构搜索结果。
- **Findings**:
  - 前端采用 Vue 3；当前无既有 UI 框架约束。
  - MVP 优先清晰可验证，避免重型组件体系。
  - API 客户端需要统一处理 loading、empty、validation、not found、conflict、degraded 和 system error 状态。
- **Implications**: 采用 Vue 3 + TypeScript + Vite + Vue Router 的最小结构；状态管理以页面组合式函数和轻量 store 为主，只有跨页面共享的推荐结果使用集中状态。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 单页 Vue 3 后台 + 轻量 API 客户端 | 在 `frontend/` 新建 Vue 3 应用，按页面和 domain API 分层 | 快速覆盖 MVP，契约清晰，测试成本适中 | 需要后续权限和设计系统时再扩展 | Selected |
| 引入完整后台框架 | 使用成熟 admin template 和组件体系 | 页面搭建快，内置布局较多 | 过早绑定重型依赖，可能引入权限/菜单复杂度 | Rejected for MVP |
| 后端模板渲染页面 | 由 FastAPI 服务直接渲染 HTML | 前后端部署简单 | 不符合 Vue 3 约束，交互测试和扩展性较弱 | Rejected |

## Design Decisions

### Decision: 使用轻量 Vue 3 应用承载后台闭环

- **Context**: MVP 需要可操作页面，但不需要完整后台平台能力。
- **Alternatives Considered**:
  1. 重型 admin 框架。
  2. 自建轻量 Vue 3 + Router + TypeScript 应用。
- **Selected Approach**: 新建 `frontend/`，使用 Vue 3、TypeScript、Vite、Vue Router 和轻量 CSS。
- **Rationale**: 满足路线图技术栈，降低复杂度，任务可按页面边界并行拆分。
- **Trade-offs**: 视觉一致性和组件丰富度有限，但适合 MVP 验证。
- **Follow-up**: 实施时再根据项目包管理方式锁定具体依赖版本。

### Decision: API 契约以类型定义和 service 层集中表达

- **Context**: 前端必须精确消费三个后端规格，避免页面散落字段映射。
- **Alternatives Considered**:
  1. 每个页面直接调用 `fetch` 并内联字段。
  2. 统一 `apiClient`、domain service 和 TypeScript 类型。
- **Selected Approach**: 在 `frontend/src/api/` 集中定义案例、推荐和反馈类型与服务函数。
- **Rationale**: 上游契约变化时能集中重校验，也便于测试错误和状态映射。
- **Trade-offs**: 初始文件略多，但减少页面耦合。
- **Follow-up**: 若后端后续提供 OpenAPI，可用生成类型替换手写类型。

### Decision: 推荐展示与反馈提交解耦

- **Context**: brief 明确反馈失败不影响推荐结果可见性。
- **Alternatives Considered**:
  1. 反馈提交后刷新整次推荐。
  2. 反馈控件本地显示提交状态，不改变推荐列表。
- **Selected Approach**: 推荐结果按后端响应只读展示，反馈控件独立提交并显示局部状态。
- **Rationale**: 保持推荐排序和展示来源可信，避免用户因反馈失败丢失推荐上下文。
- **Trade-offs**: 反馈状态与推荐结果之间需要清楚提示，不做复杂反馈历史管理。
- **Follow-up**: 后续可在反馈查询能力成熟后补充历史反馈展示。

## Risks & Mitigations

- 上游 API 尚未实现或字段变化 — 前端以本规格列出的 API 契约为准，实施时用 mock/fake service 验证，联调前做契约检查。
- 表单字段较多导致页面复杂 — 采用分区表单和可读 JSON 编辑区域承载 `context`、`outcome` 等结构字段，避免过早设计复杂表单构建器。
- 推荐解释或反馈失败影响验证体验 — 使用明确降级、空状态和局部错误提示，保证核心推荐结果可见。
- 敏感内容泄漏到错误或浏览器持久化 — 不在 localStorage 保存完整案例和查询正文，错误提示只展示用户可理解消息和稳定错误码。

## References

- `docs/mvp-product.md` — MVP 范围与技术栈（补充来源）。
- `docs/product-overview.md` — 产品愿景和用户场景。
- `.kiro/steering/roadmap.md` — 规格拆分、依赖顺序和边界策略。
- `.kiro/specs/a3-case-management/design.md` — 案例 API 和字段契约。
- `.kiro/specs/cbr-retrieval-recommendation/design.md` — 推荐 API、响应和降级契约。
- `.kiro/specs/recommendation-feedback/design.md` — 反馈 API、字段和失败边界。

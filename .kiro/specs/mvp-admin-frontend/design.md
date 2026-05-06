# Design Document

## Overview

`mvp-admin-frontend` 提供 Vue 3 基础后台页面，让业务、产品、督导和后台验证人员可以完成案例录入、案例查看、相似案例检索、推荐结果观察和反馈提交。该前端是 MVP 闭环的操作入口，不拥有任何后端业务规则、持久化、检索排序、LLM 生成或反馈学习职责。

当前仓库没有 `frontend/` 应用代码。本设计新建一个轻量 Vue 3 + TypeScript 前端应用，集中封装上游案例、推荐和反馈 API 契约，并按页面边界组织案例管理、推荐展示和反馈控件。

### Goals

- 建立 Vue 3 MVP 后台应用结构、路由、布局和基础状态处理。
- 提供案例列表、详情、创建和编辑页面。
- 提供相似案例检索页面，展示后端返回的 Top-K 推荐、分值、解释和降级状态。
- 提供运行级和推荐项级反馈控件，反馈失败不影响推荐结果可见性。
- 用 TypeScript 类型和 API service 集中对齐上游契约。

### Non-Goals

- 不实现后端 API、数据库、向量索引、CBR 重排、LLM 文案生成或反馈持久化。
- 不实现复杂权限、品牌多租户、经营数据看板、消息推送、邮件推送或行业库审核。
- 不引入重型后台模板、复杂设计系统、离线缓存或移动端专属流程。
- 不在前端重新排序推荐、重新计算相似度或生成推荐理由。

## Boundary Commitments

### This Spec Owns

- `frontend/` Vue 3 应用脚手架、路由、基础布局和页面导航。
- 案例管理页面：列表、详情、创建、编辑和字段级错误展示。
- 检索推荐页面：查询表单、过滤条件、推荐响应展示、空结果和降级状态。
- 推荐反馈控件：运行级反馈和推荐项级反馈的提交状态。
- 前端 API 客户端、TypeScript 数据契约、基础错误/加载/空状态组件。

### Out of Boundary

- 案例基础数据模型、校验规则和持久化。
- LLM 摘要、结构化提取、标签建议、推荐文案生成和审核。
- embedding、pgvector、向量搜索、CBRKit 编排、reranker 调用和推荐运行持久化。
- 推荐反馈保存、幂等规则、统计查询和学习排序。
- 复杂权限、菜单配置平台、经营指标看板、消息渠道和移动端深度适配。

### Allowed Dependencies

- `a3-case-management` API：`/api/a3-cases` 创建、编辑、详情和列表查询。
- `cbr-retrieval-recommendation` API：`/api/recommendations/similar-cases` 推荐检索。
- `recommendation-feedback` API：`/api/recommendation-feedback` 反馈提交。
- `llm-case-enrichment` 只通过推荐响应中的解释字段间接展示，不由前端直接生成。
- Vue 3、TypeScript、Vite、Vue Router；可选轻量状态管理库仅用于跨页面状态。

### Revalidation Triggers

- 上游 API 路径、请求字段、响应字段、枚举、状态或错误结构变化。
- 推荐响应中 `recommendation_run_id`、`recommendation_item_id`、分值或解释状态语义变化。
- 反馈提交字段、有用性、评分、采纳状态或幂等规则变化。
- 产品要求新增权限、多租户、看板、消息推送或移动端优先体验。
- 前端技术栈从 Vue 3、Vite 或 TypeScript 迁移到其它方案。

## Architecture

### Existing Architecture Analysis

仓库当前尚无`backend/` 实现目录。上游规格已经规划 FastAPI 后端 API，本规格以前端消费者身份对齐这些契约。由于没有既有前端模式可继承，本设计采用最小可验证 Vue 3 单页后台应用。

### Architecture Pattern & Boundary Map

```mermaid
flowchart TB
    User[User] --> Router[VueRouter]
    Router --> Layout[AdminLayout]
    Layout --> CasePages[CasePages]
    Layout --> RetrievalPage[RetrievalPage]
    CasePages --> CaseService[CaseApiService]
    RetrievalPage --> RecommendationService[RecommendationApiService]
    RetrievalPage --> FeedbackControls[FeedbackControls]
    FeedbackControls --> FeedbackService[FeedbackApiService]
    CaseService --> ApiClient[ApiClient]
    RecommendationService --> ApiClient
    FeedbackService --> ApiClient
    ApiClient --> Backend[BackendAPI]
```

**Architecture Integration**:
- Selected pattern: Vue 3 单页应用 + 页面组件 + 领域 API service。页面负责交互，service 负责契约映射，通用组件负责状态展示。
- Domain/feature boundaries: 案例页面只消费案例 API；推荐页面只展示推荐响应；反馈控件只提交反馈，不改变推荐结果。
- Existing patterns preserved: 延续 roadmap 的 Vue 3 前端约束和 MVP 轻量原则。
- New components rationale: 需要集中 API 客户端和类型定义，避免页面直接散落后端字段。
- Dependency direction: `types → apiClient → domain api services → composables/stores → pages/components → router/app`。页面不得绕过 service 直接拼接上游契约。

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| Frontend | Vue 3 + TypeScript | 后台页面与组件开发 | 满足 roadmap |
| Build | Vite | 前端开发、构建和测试集成 | 新建轻量应用 |
| Routing | Vue Router | 案例、详情、表单、推荐页面路由 | MVP 基础导航 |
| State | Composition API + 可选轻量 store | 管理页面请求状态和当前推荐结果 | 避免复杂全局状态 |
| Styling | 原生 CSS 或轻量 scoped CSS | 基础布局、表单、表格和状态提示 | 不引入重型设计系统 |
| Testing | Vitest + Vue Test Utils | 组件、API 映射和页面交互测试 | E2E 可后续接入 Playwright |

## File Structure Plan

### Directory Structure

```text
frontend/
├── package.json                         # 前端依赖、脚本和测试命令
├── index.html                           # Vite 入口 HTML
├── tsconfig.json                        # TypeScript 配置
├── vite.config.ts                       # Vite、测试和代理配置
├── src/
│   ├── main.ts                          # Vue 应用启动和路由注册
│   ├── App.vue                          # 根组件和全局布局挂载点
│   ├── router/
│   │   └── index.ts                     # 后台路由定义
│   ├── api/
│   │   ├── client.ts                    # fetch 封装、错误映射和请求配置
│   │   ├── errors.ts                    # API 错误类型、字段错误和状态分类
│   │   ├── cases.ts                     # 案例 API 类型和 service
│   │   ├── recommendations.ts           # 推荐检索 API 类型和 service
│   │   └── feedback.ts                  # 推荐反馈 API 类型和 service
│   ├── components/
│   │   ├── layout/
│   │   │   └── AdminLayout.vue          # 案例与推荐导航、页面容器
│   │   ├── common/
│   │   │   ├── LoadingState.vue         # 加载状态展示
│   │   │   ├── EmptyState.vue           # 空结果展示
│   │   │   └── ErrorNotice.vue          # 错误和重试提示
│   │   ├── cases/
│   │   │   ├── CaseFilterBar.vue        # 案例列表筛选
│   │   │   ├── CaseTable.vue            # 案例列表
│   │   │   ├── CaseForm.vue             # 创建和编辑表单
│   │   │   └── CaseDetailPanel.vue      # 案例详情展示
│   │   ├── recommendations/
│   │   │   ├── RecommendationSearchForm.vue # 检索输入和过滤条件
│   │   │   ├── RecommendationSummary.vue    # 运行元数据和降级状态
│   │   │   └── RecommendationCard.vue       # 单条推荐项展示
│   │   └── feedback/
│   │       └── FeedbackControls.vue      # 运行级和推荐项级反馈控件
│   ├── composables/
│   │   ├── useAsyncState.ts             # loading/error/data 通用状态
│   │   ├── useCases.ts                  # 案例列表、详情和表单用例
│   │   ├── useRecommendations.ts        # 检索推荐用例
│   │   └── useFeedback.ts               # 反馈提交用例
│   ├── pages/
│   │   ├── CaseListPage.vue             # 案例列表页
│   │   ├── CaseCreatePage.vue           # 案例创建页
│   │   ├── CaseEditPage.vue             # 案例编辑页
│   │   ├── CaseDetailPage.vue           # 案例详情页
│   │   └── RecommendationPage.vue       # 相似案例检索与反馈页
│   └── styles/
│       └── base.css                     # 基础布局、表单、表格和状态样式
└── tests/
    ├── api/
    │   ├── cases.test.ts                # 案例 API 映射测试
    │   ├── recommendations.test.ts      # 推荐响应映射测试
    │   └── feedback.test.ts             # 反馈请求映射测试
    ├── components/
    │   ├── CaseForm.test.ts             # 案例表单校验和错误展示
    │   ├── RecommendationCard.test.ts   # 推荐项展示和降级提示
    │   └── FeedbackControls.test.ts     # 反馈提交成功和失败状态
    └── pages/
        └── RecommendationPage.test.ts   # 检索到反馈的页面流程
```

### Modified Files

- 当前没有既有前端文件需要修改；实施阶段应新建上述 `frontend/` 结构。
- 根级配置文件是否需要纳入 monorepo 脚本，由实施阶段根据已有包管理方式决定。

## System Flows

### 案例管理流程

```mermaid
sequenceDiagram
    participant User
    participant CasePage
    participant CaseService
    participant Backend
    User->>CasePage: open list or form
    CasePage->>CaseService: load or submit case data
    CaseService->>Backend: call case api
    Backend-->>CaseService: case data or error
    CaseService-->>CasePage: typed result
    CasePage-->>User: render data or field errors
```

### 推荐与反馈流程

```mermaid
sequenceDiagram
    participant User
    participant RecommendationPage
    participant RecommendationService
    participant FeedbackControls
    participant FeedbackService
    participant Backend
    User->>RecommendationPage: submit query
    RecommendationPage->>RecommendationService: recommend similar cases
    RecommendationService->>Backend: POST similar cases
    Backend-->>RecommendationService: recommendation response
    RecommendationService-->>RecommendationPage: ordered items
    RecommendationPage-->>User: render recommendations
    User->>FeedbackControls: submit feedback
    FeedbackControls->>FeedbackService: submit feedback target
    FeedbackService->>Backend: POST feedback
    Backend-->>FeedbackService: feedback response or error
    FeedbackService-->>FeedbackControls: local feedback status
```

反馈提交只更新控件状态，不刷新或重排推荐列表。

## Requirements Traceability

| Requirement | Summary | Components | Interfaces | Flows |
|-------------|---------|------------|------------|-------|
| 1.1 | 基础导航入口 | AdminLayout, Router | route config | 案例管理流程 |
| 1.2 | 页面切换和返回路径 | AdminLayout, Router | route meta | 案例管理流程 |
| 1.3 | 不展示越界菜单 | AdminLayout | navigation model | None |
| 1.4 | 页面加载失败提示 | ErrorNotice, useAsyncState | ApiError | 案例管理流程 |
| 1.5 | 桌面后台验证场景 | base.css, AdminLayout | layout contract | None |
| 2.1 | 案例列表字段 | CaseTable, CaseApiService | CaseListItem | 案例管理流程 |
| 2.2 | 案例筛选 | CaseFilterBar, useCases | CaseListQuery | 案例管理流程 |
| 2.3 | 空列表分页 | EmptyState, CaseTable | PaginatedCaseListResponse | 案例管理流程 |
| 2.4 | 案例详情 | CaseDetailPanel | CaseDetailResponse | 案例管理流程 |
| 2.5 | 排除内部字段 | CaseApiService, CaseDetailPanel | UI field mapping | 案例管理流程 |
| 3.1 | 新建案例表单 | CaseForm | CreateCaseRequest | 案例管理流程 |
| 3.2 | 编辑字段保护 | CaseForm, CaseEditPage | UpdateCaseRequest | 案例管理流程 |
| 3.3 | 提交成功展示 | useCases, CaseForm | CaseDetailResponse | 案例管理流程 |
| 3.4 | 字段级错误 | ErrorNotice, CaseForm | ValidationError | 案例管理流程 |
| 3.5 | 不等待 AI 或推荐 | CaseForm, CaseApiService | module boundary | 案例管理流程 |
| 4.1 | 检索输入 | RecommendationSearchForm | RecommendationRequest | 推荐与反馈流程 |
| 4.2 | 推荐元数据展示 | RecommendationSummary | RecommendationResponse | 推荐与反馈流程 |
| 4.3 | 推荐项展示 | RecommendationCard | RecommendationItem | 推荐与反馈流程 |
| 4.4 | 空结果和降级 | RecommendationSummary, EmptyState | degraded status | 推荐与反馈流程 |
| 4.5 | 不本地排序或生成 | useRecommendations | module boundary | 推荐与反馈流程 |
| 5.1 | 运行级反馈 | FeedbackControls | FeedbackCreateRequest | 推荐与反馈流程 |
| 5.2 | 推荐项级反馈 | FeedbackControls | FeedbackCreateRequest | 推荐与反馈流程 |
| 5.3 | 反馈成功状态 | useFeedback, FeedbackControls | FeedbackResponse | 推荐与反馈流程 |
| 5.4 | 反馈失败不影响推荐 | FeedbackControls, ErrorNotice | ApiError | 推荐与反馈流程 |
| 5.5 | 反馈不改变推荐 | useFeedback, RecommendationPage | module boundary | 推荐与反馈流程 |
| 6.1 | 只用定义接口 | CaseApiService, RecommendationApiService, FeedbackApiService | API services | All |
| 6.2 | 状态可观察 | LoadingState, EmptyState, ErrorNotice, useAsyncState | UiAsyncState | All |
| 6.3 | 上游变化重校验 | API types | contract mapping | All |
| 6.4 | 敏感信息保护 | ApiClient, ErrorNotice | safe error model | All |
| 6.5 | 轻量 MVP 边界 | AdminLayout, file structure | module boundary | All |

## Components and Interfaces

| Component | Domain/Layer | Intent | Req Coverage | Key Dependencies | Contracts |
|-----------|--------------|--------|--------------|------------------|-----------|
| AdminLayout | UI Layout | 提供基础导航、页面容器和当前位置 | 1.1, 1.2, 1.3, 1.5 | Vue Router P0 | State |
| ApiClient | Integration | 统一 HTTP 调用、错误解析和脱敏错误模型 | 1.4, 6.1, 6.2, 6.4 | fetch P0 | Service |
| CaseApiService | Integration | 消费案例 CRUD 和查询 API | 2.1, 2.2, 2.4, 3.3, 6.1 | ApiClient P0 | API |
| CaseForm | UI Form | 创建和编辑 A3 案例基础字段 | 3.1, 3.2, 3.4, 3.5 | CaseApiService P0 | State |
| CaseTable | UI Display | 展示案例列表和分页结果 | 2.1, 2.3, 2.5 | CaseApiService P0 | State |
| CaseDetailPanel | UI Display | 展示案例完整基础字段 | 2.4, 2.5 | CaseApiService P0 | State |
| RecommendationApiService | Integration | 消费相似案例推荐 API | 4.1, 4.2, 4.3, 4.4, 4.5 | ApiClient P0 | API |
| RecommendationSearchForm | UI Form | 收集问题、Top-K 和过滤条件 | 4.1 | RecommendationApiService P0 | State |
| RecommendationSummary | UI Display | 展示运行标识、状态、元数据和降级原因 | 4.2, 4.4 | RecommendationApiService P0 | State |
| RecommendationCard | UI Display | 展示单条推荐项、分值、理由和来源 | 4.3, 4.5 | RecommendationApiService P0 | State |
| FeedbackApiService | Integration | 提交运行级和推荐项级反馈 | 5.1, 5.2, 5.3, 5.4, 6.1 | ApiClient P0 | API |
| FeedbackControls | UI Form | 展示反馈控件和局部提交状态 | 5.1, 5.2, 5.3, 5.4, 5.5 | FeedbackApiService P0 | State |
| useAsyncState | UI State | 统一 loading、empty、error、success 状态 | 1.4, 6.2 | Vue Composition API P0 | State |

### API Integration Layer

#### 环境与认证（MVP）

- **全匿名**：不实现登录、会话续期、Token 或角色权限框架；请求不附带 Bearer、API Key 或其它鉴权 Header（若后续产品规格要求认证，须单独立项并修订本设计）。
- **API 契约来源**：前端 API 类型定义严格对齐 `docs/contracts/` 目录下的 OpenAPI 规格文件（`a3-case-management.openapi.yaml`、`cbr-retrieval-recommendation.openapi.yaml`、`recommendation-feedback.openapi.yaml`），字段命名、枚举值、错误码和状态语义以契约文件为准。
- **开发环境代理**：本地联调通过 Vite `server.proxy` 将约定前缀（例如 `/api`）转发到本机或内网后端地址，由开发服务器代发同源请求。代理目标可用环境变量（例如 `VITE_API_PROXY_TARGET`）注入构建/开发环境，**不得**把密钥类凭据写入仓库或打包进静态资源。
- **MVP 部署策略（单节点同源部署）**：MVP 阶段前后端部署在同一节点上，前端静态资源由后端 FastAPI 应用托管（通过 `StaticFiles` 中间件或 Nginx 反向代理），前端请求后端 API 为同源请求，无需配置 CORS。具体部署方式：
  - **方式 1（FastAPI 托管）**：FastAPI 应用挂载 `StaticFiles` 中间件，将前端构建产物（`frontend/dist`）托管在根路径或 `/admin` 路径下，API 路由保持 `/api` 前缀，前端通过相对路径访问 API。
  - **方式 2（Nginx 反向代理）**：Nginx 同时托管前端静态资源和反向代理后端 API，前端和 API 共享同一域名和端口，前端通过相对路径访问 API。
  - **环境变量注入**：前端构建时通过 `VITE_API_BASE_URL` 环境变量注入 API base URL（开发环境为空或 `/api`，生产环境为 `/api` 或绝对路径），`ApiClient` 根据环境变量动态拼接请求路径。
  - **后续扩展**：验证无误后，若需要前后端分离部署或多节点部署，需单独评估 CORS 配置、CDN 托管、负载均衡和会话管理策略，并修订本设计。

#### ApiClient

| Field | Detail |
|-------|--------|
| Intent | 统一前端 HTTP 调用、响应解析和错误模型 |
| Requirements | 1.4, 6.1, 6.2, 6.4 |

**Responsibilities & Constraints**
- 遵循上文「环境与认证（MVP）」：匿名、开发代理下的 base URL 与路径约定。
- 统一设置 API base URL、JSON headers、超时或取消策略。
- 将字段级错误、未找到、冲突、降级成功和系统错误映射为前端可处理结构。
- 错误对象只包含稳定 `code`、用户可读 `message`、可选 `fields` 和 HTTP status，不保存完整敏感正文。

**Service Interface**

```typescript
type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

interface ApiClient {
  get<T>(path: string, query?: Record<string, string | number | boolean | undefined>): Promise<ApiResult<T>>;
  post<TRequest, TResponse>(path: string, body: TRequest): Promise<ApiResult<TResponse>>;
  put<TRequest, TResponse>(path: string, body: TRequest): Promise<ApiResult<TResponse>>;
}
```

### Case Management UI

#### CaseApiService

| Field | Detail |
|-------|--------|
| Intent | 封装 `a3-case-management` API 契约 |
| Requirements | 2.1, 2.2, 2.4, 3.3, 6.1 |

**API Contract**

| Method | Endpoint | Request | Response | Errors |
|--------|----------|---------|----------|--------|
| POST | `/api/a3-cases` | `CreateCaseRequest` | `CaseDetailResponse` | 400, 422, 500 |
| PUT | `/api/a3-cases/{case_id}` | `UpdateCaseRequest` | `CaseDetailResponse` | 404, 409, 422, 500 |
| GET | `/api/a3-cases/{case_id}` | path `case_id` | `CaseDetailResponse` | 404, 500 |
| GET | `/api/a3-cases` | `CaseListQuery` | `PaginatedCaseListResponse` | 422, 500 |

**Implementation Notes**
- `CaseForm` 将 `context`、`solution_steps`、`outcome` 作为结构化输入区域处理，提交前转换为上游请求结构。
- 编辑模式禁止向 `UpdateCaseRequest` 发送 `case_id` 和 `created_at`。
- 列表和详情展示不映射 embedding、相似度、推荐运行或反馈字段。

#### CaseForm

| Field | Detail |
|-------|--------|
| Intent | 创建和编辑 A3 案例基础字段 |
| Requirements | 3.1, 3.2, 3.3, 3.4, 3.5 |

**State Management**
- State model: 表单草稿、字段错误、提交中、提交成功、提交失败。
- Persistence: 不把完整表单草稿写入 localStorage。
- Invariants: 表单只提交案例基础字段；LLM、向量和推荐状态不是表单前置条件。

### Retrieval and Recommendation UI

#### RecommendationApiService

| Field | Detail |
|-------|--------|
| Intent | 封装推荐检索 API 契约 |
| Requirements | 4.1, 4.2, 4.3, 4.4, 4.5 |

**API Contract**

| Method | Endpoint | Request | Response | Errors |
|--------|----------|---------|----------|--------|
| POST | `/api/recommendations/similar-cases` | `RecommendationRequest` | `RecommendationResponse` | 422, 503 |

**Implementation Notes**
- `RecommendationResponse.items` 按后端顺序渲染，前端不得重新排序。
- 降级状态、候选不足和缺失字段都作为用户可见状态展示。
- 推荐结果保留在页面状态中，反馈失败不会清空推荐响应。

#### RecommendationCard

| Field | Detail |
|-------|--------|
| Intent | 展示单条推荐项的可解释内容 |
| Requirements | 4.3, 4.4, 4.5 |

**Responsibilities & Constraints**
- 展示 `recommendation_item_id`、`case_id`、`rank`、`case_reference`、`core_solution_steps`、`outcome_summary`、`vector_similarity_score`、`semantic_similarity_score`、`structured_similarity_score`、`business_score`、`final_score`、`recommendation_reason`、`reference_points`、`cautions`、`source_references`、`explanation_status`。
- `semantic_similarity_score` 或结构化分为空时显示后端降级说明，不伪造分值。
- 缺失字段使用 `missing_fields` 提示，不隐藏整条可用推荐。

### Feedback UI

#### FeedbackApiService

| Field | Detail |
|-------|--------|
| Intent | 封装推荐反馈提交 API 契约 |
| Requirements | 5.1, 5.2, 5.3, 5.4, 6.1 |

**API Contract**

| Method | Endpoint | Request | Response | Errors |
|--------|----------|---------|----------|--------|
| POST | `/api/recommendation-feedback` | `FeedbackCreateRequest` | `FeedbackResponse` | 400, 404, 409, 422 |

**Implementation Notes**
- 运行级反馈仅发送 `recommendation_run_id`，推荐项级反馈同时发送 `recommendation_item_id`。
- 默认 `source_channel` 为 `admin_web`。
- 可生成一次性 `idempotency_key` 避免重复点击造成重复提交；后端仍是幂等权威。

#### FeedbackControls

| Field | Detail |
|-------|--------|
| Intent | 提供反馈输入、提交和局部状态 |
| Requirements | 5.1, 5.2, 5.3, 5.4, 5.5 |

**State Management**
- State model: `idle`, `submitting`, `saved`, `failed`。
- Persistence: 不持久化完整备注；提交成功后只显示后端返回状态。
- Invariants: 反馈控件不修改推荐列表、排序、分值或解释文本。

## Data Models

### Data Contracts & Integration

本节定义前端数据模型与后端 API 契约的映射关系。所有字段命名、类型和枚举值严格对齐 `docs/contracts/` 目录下的 OpenAPI 规格文件。

#### 案例管理数据模型

**CaseListItem**（对应 `a3-case-management.openapi.yaml` § CaseListItem）

| 前端字段 | 后端字段 | 类型 | 说明 | 映射规则 |
|---------|---------|------|------|---------|
| `case_id` | `case_id` | string | 案例唯一标识 | 直接映射 |
| `problem_description_preview` | `problem_description_preview` | string | 问题描述预览（后端截断） | 直接映射，后端返回截断后的预览文本 |
| `store_profile` | `store_profile` | StoreProfile | 门店档案 | 直接映射对象 |
| `store_profile.store_id` | `store_profile.store_id` | string | 门店标识 | 从嵌套对象提取 |
| `store_profile.store_name` | `store_profile.store_name` | string | 门店名称 | 从嵌套对象提取 |
| `store_profile.brand_id` | `store_profile.brand_id` | string | 品牌标识 | 从嵌套对象提取 |
| `store_profile.brand_name` | `store_profile.brand_name` | string | 品牌名称 | 从嵌套对象提取 |
| `store_profile.business_type` | `store_profile.business_type` | string | 业态类型 | 从嵌套对象提取 |
| `store_profile.store_scale` | `store_profile.store_scale` | string | 门店规模 | 从嵌套对象提取 |
| `store_profile.franchise_type` | `store_profile.franchise_type` | string | 加盟类型 | 从嵌套对象提取 |
| `store_profile.city` | `store_profile.city` | string | 城市 | 从嵌套对象提取 |
| `store_profile.city_tier` | `store_profile.city_tier` | string | 城市规模 | 从嵌套对象提取 |
| `problem_type` | `problem_type` | ProblemType | 问题类型枚举 | 直接映射，枚举值：`service`, `quality`, `operation`, `hygiene`, `staffing`, `other` |
| `status` | `status` | CaseStatus | 案例状态枚举 | 直接映射，枚举值：`draft`, `active`, `archived` |
| `created_at` | `created_at` | string (date-time) | 创建时间 | 直接映射 ISO 8601 格式 |
| `updated_at` | `updated_at` | string (date-time) | 更新时间 | 直接映射 ISO 8601 格式 |

**CaseDetailResponse**（对应 `a3-case-management.openapi.yaml` § CaseDetailResponse）

| 前端字段 | 后端字段 | 类型 | 说明 | 映射规则 |
|---------|---------|------|------|---------|
| 继承 `CaseListItem` 所有字段 | - | - | - | - |
| `problem_description` | `problem_description` | string | 完整问题描述 | 直接映射，替换列表中的 `problem_description_preview` |
| `context` | `context` | Context | 场景上下文对象 | 直接映射对象，包含 `scene` 必填字段和可选扩展字段 |
| `context.scene` | `context.scene` | string | 场景描述 | 从嵌套对象提取 |
| `root_cause` | `root_cause` | string | 根因分析 | 直接映射 |
| `solution_steps` | `solution_steps` | SolutionStep[] | 解决步骤数组 | 直接映射对象数组 |
| `solution_steps[].order` | `solution_steps[].order` | integer | 步骤顺序 | 从数组元素提取 |
| `solution_steps[].content` | `solution_steps[].content` | string | 步骤内容 | 从数组元素提取 |
| `solution_steps[].extra` | `solution_steps[].extra` | object | 可选扩展字段 | 从数组元素提取（可选） |
| `outcome` | `outcome` | Outcome | 效果结果对象 | 直接映射对象 |
| `outcome.result` | `outcome.result` | OutcomeResult | 效果枚举 | 从嵌套对象提取，枚举值：`improved`, `no_change`, `unknown` |
| `outcome.notes` | `outcome.notes` | string | 效果备注 | 从嵌套对象提取 |

**CreateCaseRequest / UpdateCaseRequest**（对应 `a3-case-management.openapi.yaml` § CreateCaseRequest / UpdateCaseRequest）

前端表单字段直接映射到后端请求 schema，不做额外转换。编辑模式禁止发送 `case_id` 和 `created_at`。

#### 推荐检索数据模型

**RecommendationRequest**（对应 `cbr-retrieval-recommendation.openapi.yaml` § RecommendationRequest）

| 前端字段 | 后端字段 | 类型 | 说明 | 映射规则 |
|---------|---------|------|------|---------|
| `query_text` | `query_text` | string | 查询文本 | 直接映射，必填，非空 |
| `top_k` | `top_k` | integer | 返回数量 | 直接映射，范围 1-100，默认 20 |
| `filters` | `filters` | RecommendationFilters | 过滤条件对象 | 直接映射对象（可选） |
| `filters.brand_id` | `filters.brand_id` | string | 品牌过滤 | 从嵌套对象提取（可选） |
| `filters.store_id` | `filters.store_id` | string | 门店过滤 | 从嵌套对象提取（可选） |
| `filters.business_type` | `filters.business_type` | string | 业态过滤 | 从嵌套对象提取（可选） |
| `filters.store_scale` | `filters.store_scale` | string | 门店规模过滤 | 从嵌套对象提取（可选） |
| `filters.franchise_type` | `filters.franchise_type` | string | 加盟类型过滤 | 从嵌套对象提取（可选） |
| `filters.city` | `filters.city` | string | 城市过滤 | 从嵌套对象提取（可选） |
| `filters.city_tier` | `filters.city_tier` | string | 城市规模过滤 | 从嵌套对象提取（可选） |
| `filters.problem_type` | `filters.problem_type` | string | 问题类型过滤 | 从嵌套对象提取（可选） |
| `filters.tags` | `filters.tags` | string[] | 标签过滤 | 从嵌套对象提取（可选） |
| `filters.case_status` | `filters.case_status` | string | 案例状态过滤 | 从嵌套对象提取（可选） |
| `filters.created_at_from` | `filters.created_at_from` | string (date-time) | 创建时间起始 | 从嵌套对象提取（可选） |
| `filters.created_at_to` | `filters.created_at_to` | string (date-time) | 创建时间截止 | 从嵌套对象提取（可选） |
| `business_weights` | `business_weights` | BusinessWeights | 业务权重对象 | 直接映射对象（可选），MVP 阶段前端不提供权重调整 UI |

**RecommendationResponse**（对应 `cbr-retrieval-recommendation.openapi.yaml` § RecommendationResponse）

| 前端字段 | 后端字段 | 类型 | 说明 | 映射规则 |
|---------|---------|------|------|---------|
| `recommendation_run_id` | `recommendation_run_id` | string | 推荐运行标识 | 直接映射 |
| `contract_version` | `contract_version` | string | 契约版本 | 直接映射 |
| `status` | `status` | RecommendationStatus | 推荐状态枚举 | 直接映射，枚举值：`succeeded`, `empty`, `degraded`, `failed` |
| `message` | `message` | string \| null | 状态消息 | 直接映射（可选） |
| `error_code` | `error_code` | string \| null | 错误码 | 直接映射（可选） |
| `degraded_reason` | `degraded_reason` | DegradedReason \| null | 降级原因枚举 | 直接映射（可选），枚举值见契约文件 |
| `applied_filters` | `applied_filters` | object | 实际应用的过滤条件 | 直接映射对象 |
| `score_weights` | `score_weights` | object | 分值权重 | 直接映射对象 |
| `query_metadata` | `query_metadata` | QueryMetadata | 查询元数据 | 直接映射对象 |
| `query_metadata.query_hash` | `query_metadata.query_hash` | string | 查询哈希 | 从嵌套对象提取 |
| `query_metadata.requested_top_k` | `query_metadata.requested_top_k` | integer | 请求数量 | 从嵌套对象提取 |
| `query_metadata.vector_candidate_count` | `query_metadata.vector_candidate_count` | integer | 向量候选数 | 从嵌套对象提取 |
| `query_metadata.returned_count` | `query_metadata.returned_count` | integer | 实际返回数 | 从嵌套对象提取 |
| `query_metadata.latency_ms` | `query_metadata.latency_ms` | integer | 延迟毫秒数 | 从嵌套对象提取 |
| `items` | `items` | RecommendationItem[] | 推荐项数组 | 直接映射对象数组，按后端顺序渲染 |

**RecommendationItem**（对应 `cbr-retrieval-recommendation.openapi.yaml` § RecommendationItem）

| 前端字段 | 后端字段 | 类型 | 说明 | 映射规则 |
|---------|---------|------|------|---------|
| `recommendation_item_id` | `recommendation_item_id` | string \| null | 推荐项标识 | 直接映射，null 表示运行级推荐 |
| `case_id` | `case_id` | string | 案例标识 | 直接映射 |
| `rank` | `rank` | integer | 排序位置 | 直接映射，从 1 开始 |
| `case_reference` | `case_reference` | CaseReference | 案例引用对象 | 直接映射对象，后端返回预处理的引用信息 |
| `case_reference.title_preview` | `case_reference.title_preview` | string | 标题预览 | 从嵌套对象提取 |
| `case_reference.description_preview` | `case_reference.description_preview` | string | 描述预览 | 从嵌套对象提取 |
| `case_reference.brand_summary` | `case_reference.brand_summary` | string \| null | 品牌摘要 | 从嵌套对象提取（可选） |
| `case_reference.store_summary` | `case_reference.store_summary` | string \| null | 门店摘要 | 从嵌套对象提取（可选） |
| `case_reference.filter_summary` | `case_reference.filter_summary` | string \| null | 过滤摘要 | 从嵌套对象提取（可选） |
| `case_reference.case_updated_at` | `case_reference.case_updated_at` | string (date-time) | 案例更新时间 | 从嵌套对象提取 |
| `core_solution_steps` | `core_solution_steps` | string[] | 核心解决步骤 | 直接映射字符串数组 |
| `outcome_summary` | `outcome_summary` | string \| null | 效果摘要 | 直接映射（可选） |
| `structured_suggestions_summary` | `structured_suggestions_summary` | string \| null | 结构化建议摘要 | 直接映射（可选） |
| `vector_similarity_score` | `vector_similarity_score` | number | 向量相似度 | 直接映射浮点数 |
| `semantic_similarity_score` | `semantic_similarity_score` | number \| null | 语义相似度 | 直接映射（可选），降级时为 null |
| `structured_similarity_score` | `structured_similarity_score` | number \| null | 结构化相似度 | 直接映射（可选），降级时为 null |
| `business_score` | `business_score` | number \| null | 业务参数分 | 直接映射（可选） |
| `final_score` | `final_score` | number | 最终聚合分 | 直接映射浮点数，降级时可为 0.0 |
| `score_breakdown` | `score_breakdown` | ScoreBreakdown | 分值明细 | 直接映射对象 |
| `score_breakdown.final_score_source` | `score_breakdown.final_score_source` | ScoreFinalSource | 分值来源枚举 | 从嵌套对象提取，枚举值：`aggregated`, `default_zero_not_aggregated` |
| `score_breakdown.weights` | `score_breakdown.weights` | object | 权重明细 | 从嵌套对象提取（可选） |
| `score_breakdown.factors` | `score_breakdown.factors` | object | 因子明细 | 从嵌套对象提取（可选） |
| `recommendation_reason` | `recommendation_reason` | string \| null | 推荐理由 | 直接映射（可选） |
| `reference_points` | `reference_points` | string[] | 可参考解决点 | 直接映射字符串数组 |
| `cautions` | `cautions` | string[] | 注意事项 | 直接映射字符串数组 |
| `source_references` | `source_references` | string[] | 来源引用 | 直接映射字符串数组 |
| `explanation_status` | `explanation_status` | ExplanationStatus | 解释状态枚举 | 直接映射，枚举值：`generated`, `fallback`, `unavailable` |
| `missing_fields` | `missing_fields` | string[] | 缺失字段列表 | 直接映射字符串数组 |

#### 推荐反馈数据模型

**FeedbackCreateRequest**（对应 `recommendation-feedback.openapi.yaml` § FeedbackCreateRequest）

| 前端字段 | 后端字段 | 类型 | 说明 | 映射规则 |
|---------|---------|------|------|---------|
| `recommendation_run_id` | `recommendation_run_id` | string | 推荐运行标识 | 直接映射，必填 |
| `recommendation_item_id` | `recommendation_item_id` | string \| null | 推荐项标识 | 直接映射（可选），null 表示运行级反馈 |
| `usefulness` | `usefulness` | Usefulness | 有用性枚举 | 直接映射，枚举值：`useful`, `not_useful`, `unknown` |
| `comment` | `comment` | string \| null | 反馈备注 | 直接映射（可选），最大长度 2000 |
| `actor_id` | `actor_id` | string | 反馈提交者标识 | 直接映射，必填，MVP 阶段使用匿名占位符（如 `anonymous_user`） |
| `source_channel` | `source_channel` | SourceChannel | 来源渠道枚举 | 直接映射，固定值 `admin_web` |

**注意**：前端设计文档中提到的 `rating`（1-5 评分）和 `adoption_status`（采纳状态）字段在后端契约中不存在，需从前端设计中移除或标记为未来扩展字段。

**FeedbackResponse**（对应 `recommendation-feedback.openapi.yaml` § FeedbackResponse）

| 前端字段 | 后端字段 | 类型 | 说明 | 映射规则 |
|---------|---------|------|------|---------|
| `feedback_id` | `feedback_id` | string | 反馈标识 | 直接映射 |
| `recommendation_run_id` | `recommendation_run_id` | string | 推荐运行标识 | 直接映射 |
| `recommendation_item_id` | `recommendation_item_id` | string \| null | 推荐项标识 | 直接映射（可选） |
| `case_id` | `case_id` | string \| null | 案例标识 | 直接映射（可选） |
| `usefulness` | `usefulness` | Usefulness | 有用性枚举 | 直接映射 |
| `comment` | `comment` | string \| null | 反馈备注 | 直接映射（可选） |
| `target_scope` | `target_scope` | TargetScope | 反馈目标范围枚举 | 直接映射，枚举值：`run`, `item` |
| `created_at` | `created_at` | string (date-time) | 创建时间 | 直接映射 ISO 8601 格式 |
| `updated_at` | `updated_at` | string (date-time) | 更新时间 | 直接映射 ISO 8601 格式 |

## Error Handling

### Error Strategy

- API service 将后端错误统一映射为 `ApiError`，页面只消费稳定错误分类。
- 字段级错误展示在对应表单区域；页面级错误展示在 `ErrorNotice`。
- 空列表、空推荐和降级成功是可见状态，不作为不可恢复异常。
- 反馈错误仅影响当前 `FeedbackControls`，不清空推荐结果。

### Error Categories and Responses

- **User Errors (4xx)**: 字段校验失败、无效筛选、无效评分、备注过长；展示字段错误和修正提示。
- **Not Found (404)**: 案例、推荐运行或推荐项不存在；展示返回列表或重试入口。
- **Conflict (409)**: 案例不可编辑、反馈目标不匹配或幂等冲突；展示状态冲突说明。
- **Dependency Degraded**: 推荐重排或解释降级；展示降级原因并保留可用推荐项。
- **System Errors (5xx/503)**: 后端或外部依赖失败；展示稳定错误和重试入口。

### Monitoring

- 前端可在开发模式记录路由、HTTP status 和稳定错误码。
- 禁止记录完整案例正文、完整查询文本、向量数组、反馈备注全文或供应商原始错误。

## Testing Strategy

### Unit Tests

- `ApiClient` 映射成功响应、字段级错误、404、409、503 和系统错误。
- `CaseForm` 提交创建和编辑字段，禁止编辑 `case_id` 与 `created_at`，并展示字段错误。
- `RecommendationCard` 展示分值明细、解释状态、缺失字段和语义/结构化评分为空的降级提示。
- `FeedbackControls` 支持运行级和推荐项级反馈，并在失败时保留推荐上下文。

### Integration Tests

- 案例列表页按筛选条件请求 `/api/a3-cases` 并展示空结果分页。
- 案例详情页请求 `/api/a3-cases/{case_id}` 并排除向量、推荐和反馈内部字段。
- 推荐页提交 `/api/recommendations/similar-cases` 后展示运行元数据和有序推荐项。
- 反馈控件向 `/api/recommendation-feedback` 提交运行级和推荐项级反馈。
- 推荐降级和反馈失败同时出现时，推荐项仍然可见。

### E2E/UI Tests

- 用户创建案例后返回详情页并看到案例标识和更新时间。
- 用户从列表打开详情，再返回列表保留基础导航路径。
- 用户输入问题、Top-K 和过滤条件后看到推荐结果、相似度和推荐理由。
- 用户对推荐项提交反馈，成功状态显示在对应卡片区域。

## Security Considerations

- 不在浏览器持久化完整案例、完整查询正文、完整反馈备注或供应商原始错误。
- 错误提示使用稳定错误码和用户可理解消息，避免泄漏后端堆栈或数据库细节。
- 前端不实现复杂权限，但页面结构不应假设跨品牌访问一定被允许；后续权限由后端或独立权限规格控制。

## Performance & Scalability

- MVP 以同步请求和页面级 loading 为主。
- 列表分页依赖后端分页结果，不在前端一次性拉取全量案例。
- 推荐 Top-K 和候选数量由后端控制，前端只渲染返回结果。
- 组件保持轻量，避免为 MVP 引入大体积图表库或复杂 UI 框架。

## Migration Strategy

```mermaid
flowchart TD
    Start[Start] --> CreateFrontend[CreateFrontend]
    CreateFrontend --> AddApiServices[AddApiServices]
    AddApiServices --> AddPages[AddPages]
    AddPages --> AddFeedback[AddFeedback]
    AddFeedback --> RunTests[RunTests]
    RunTests --> Ready[Ready]
```

本规格只新增 `frontend/` 前端应用和测试，不迁移数据库，也不修改后端表结构。若后续 monorepo 需要统一脚本，可在根级配置中添加前端构建和测试命令。

# Design Document

## Overview

`llm-case-enrichment` 叠在 `a3-case-management` 之上，单独提供 AI 派生能力：为门店、督导和后台管理者生成案例问题摘要、方案摘要、结构化字段建议、标签建议，以及相似案例推荐理由文案。它只读取案例基础契约约定的字段，不改动案例 CRUD、基础字段或状态语义。

实现按 Python + FastAPI 后端扩展，通过 `deepseek-v4-pro` 或兼容的云端 LLM 接入点生成内容。所有 LLM 输出必须先过结构化 schema 校验和状态门控，再进入审核、向量索引或推荐展示链路。

### Goals

- 为 A3 案例产出可审核、可覆盖、可追溯的 AI 派生内容。
- 为推荐候选生成可解释文案，并保留候选案例引用。
- 用 schema 校验、运行记录、失败状态和重试边界压住 LLM 的不稳定性。
- LLM 增强、向量索引、CBR 推荐和案例管理之间职责分明。

### Non-Goals

- 不创建或修改 A3 案例基础字段，不实现案例 CRUD。
- 不生成 embedding，不建 pgvector 字段或向量索引。
- 不做 Top-K 召回、过滤、相似度计算、reranker 重排或排序调整。
- 不做复杂多轮追问、模型微调、本地模型部署、反馈学习排序。
- 不做前端页面，只提供后端契约供后台页面调用。

## Boundary Commitments

### This Spec Owns

- `CaseEnrichmentResult`、`CaseEnrichmentRun`、`RecommendationCopyRun` 等 LLM 派生结果、LLM 调用审计、成本与 schema 校验状态。
- 案例摘要、方案摘要、结构化字段建议、标签建议的生成、校验、审核状态与过期判断。
- 推荐理由、可参考解决点、注意事项文案的生成合同。
- Prompt 模板、LLM 客户端适配、输出 schema 校验、失败记录、重试边界与安全约束。

### Out of Boundary

- `A3Case` 基础实体、字段校验、创建、编辑、详情、列表查询。
- embedding 输入拼接、BGE-M3 调用、pgvector 存储与索引状态。
- CBRKit 编排、查询标准化、候选召回、reranker 重排、相似度分值与 Top-K 返回顺序。
- 推荐运行、推荐项快照、召回或排序持久化；这些归 `cbr-retrieval-recommendation` 所有，`RecommendationCopyRun` 不代表推荐运行。
- 推荐反馈、有用/无用、评分、采纳状态与排序学习。
- 跨品牌行业库脱敏审核、复杂权限体系与前端展示实现。

### Allowed Dependencies

- `a3-case-management` 的详情读取能力与基础字段契约：`case_id`、A3 基础字段、状态、过滤字段、`updated_at`。
- Python + FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL，与上游后端栈一致。
- 云端 LLM：MVP 默认 `deepseek-v4-pro`，经 OpenAI 兼容或等价 HTTP 客户端接入。
- 下游只能消费已发布或明确标注可用的派生结果状态。

### Revalidation Triggers

- `a3-case-management` 侧字段名、类型、状态语义、详情响应或 `updated_at` 语义变化。
- LLM 输出 schema、派生结果状态、审核状态或推荐文案响应结构变化。
- LLM 供应商、模型标识、数据保留策略或生产隐私配置变化。
- 生成模式从同步请求内处理切到后台队列或事件驱动。
- 下游向量索引或 CBR 推荐要求新增派生字段或改变可用状态判定。

### Runtime Contract Guardrail

- 新增 `case_contract_version` 与 `mapping_version` 配置，`CaseSnapshotProvider` 启动时做一次契约握手检查。
- 每次创建 `CaseEnrichmentRun` 时持久化 `input_contract_version` 与 `mapping_version`，便于问题回溯到具体契约版本。
- 上游契约版本与本服务配置不一致时，增强流程必须 fail-closed：返回 `CASE_INPUT_CONTRACT_MISMATCH`，不再调用 LLM。
- 该门控只阻断增强与推荐文案生成，不影响案例基础查看（与不阻塞基础查看一致）。

## Architecture

### Existing Architecture Analysis

`a3-case-management` 规格规划在 `backend/app/cases` 建模块、统一错误结构和数据库基础设施。本规格作为下游扩展，在同一 FastAPI 后端内新增 `enrichment` 模块，经 `CaseSnapshotProvider` 读上游案例详情，不直接持有或复制案例基础生命周期。

### Architecture Pattern & Boundary Map

```mermaid
flowchart TB
    Client[Client] --> Router[EnrichmentRouter]
    Retrieval[RetrievalService] --> Router
    Router --> Schemas[EnrichmentSchemas]
    Router --> Service[EnrichmentService]
    Router --> CopyService[RecommendationCopyService]
    Service --> CaseProvider[CaseSnapshotProvider]
    Service --> PromptCatalog[PromptCatalog]
    Service --> LLMClient[LLMClient]
    Service --> Validator[OutputValidator]
    Service --> Repository[EnrichmentRepository]
    CopyService --> PromptCatalog
    CopyService --> LLMClient
    CopyService --> Validator
    CopyService --> Repository
    Repository --> Database[PostgreSQL]
```



**Architecture Integration**：

- 选型：轻量分层 FastAPI 模块——Router 暴露 API，Service 编排用例，PromptCatalog 固化提示词，LLMClient 隔离供应商，OutputValidator 校验结果，Repository 落库派生结果与运行状态。
- 领域边界：`EnrichmentService` 只管案例派生内容；`RecommendationCopyService` 只解释已排序候选，不参与排序。
- 沿用上游 FastAPI、Pydantic、SQLAlchemy、Alembic、统一错误响应与数据库会话。
- 新增组件原因：LLM 调用不稳定且有安全风险，需要独立运行记录、输出校验、隐私配置与重试边界。
- 依赖方向：`Config → Schemas → PromptCatalog → LLMClient → Validator → Repository → Service → Router`；`CaseSnapshotProvider` 作为读取上游案例快照的端口，不回写案例模块。

### Technology Stack


| Layer              | Choice / Version            | Role in Feature    | Notes                     |
| ------------------ | --------------------------- | ------------------ | ------------------------- |
| Backend / Services | Python 3.11+ + FastAPI      | 暴露 LLM 增强与推荐文案 API | 与上游后端栈一致                  |
| Validation         | Pydantic                    | LLM 输出、请求响应与错误结构校验 | 对外发布结果须过 schema           |
| Data / Storage     | PostgreSQL                  | 派生结果、运行状态、错误与审核状态  | 不存向量                      |
| ORM / Migration    | SQLAlchemy + Alembic        | 派生结果表与运行记录表迁移      | 与案例表以 `case_id` 关联        |
| External AI        | `deepseek-v4-pro`           | 摘要、结构化建议、推荐文案生成    | 经配置开启生产调用                 |
| Testing            | pytest + FastAPI TestClient | 单元、API、失败与安全边界测试   | LLM 侧用 mock 或 fake client |


## File Structure Plan

### Directory Structure

```text
backend/
├── app/
│   ├── core/
│   │   ├── config.py                         # 增加 LLM 供应商、模型、超时、隐私配置
│   │   └── errors.py                         # 增加 LLM 增强错误码映射
│   ├── cases/
│   │   └── service.py                        # 被 CaseSnapshotProvider 读取案例详情
│   └── enrichment/
│       ├── models.py                         # 派生结果、运行记录和推荐文案运行 ORM 模型
│       ├── schemas.py                        # 请求、响应、LLM 输出 schema 和状态枚举
│       ├── repository.py                     # 派生结果、运行记录、审核状态和失败记录持久化
│       ├── service.py                        # 案例摘要、结构化建议和标签建议编排
│       ├── recommendation_copy.py            # 推荐理由文案生成编排
│       ├── case_snapshot.py                  # 读取并冻结上游案例输入快照
│       ├── prompts.py                        # Prompt 模板、任务类型和注入防护约束
│       ├── llm_client.py                     # deepseek-v4-pro 或兼容 LLM 供应商适配
│       ├── validators.py                     # LLM 输出解析、schema 校验和标签规范化
│       ├── jobs.py                           # 同步运行记录和未来异步 worker 边界
│       └── router.py                         # LLM 增强和推荐文案 API 端点
├── alembic/
│   └── versions/
│       └── <revision>_create_case_enrichment.py
└── tests/
    └── enrichment/
        ├── test_enrichment_validation.py     # 输出 schema、标签和状态校验
        ├── test_enrichment_service.py        # 摘要、结构化建议、过期和重试逻辑
        ├── test_recommendation_copy.py       # 推荐文案不改变排序并保留引用
        ├── test_enrichment_api.py            # API 成功、失败、轮询和审核状态
        └── test_llm_safety.py                # 提示词注入、隐私配置和日志边界
```

### Modified Files

- `backend/app/main.py` — 只追加注册 `EnrichmentRouter`，不改应用入口基础实现。
- `backend/app/core/config.py` — 只追加 LLM、Embedding、Reranker 三类模型各自的开关、供应商、模型、base_url、超时、重试、数据保留确认等配置项，不接管共享配置基础设施。
- `backend/app/core/errors.py` — 只追加 `ENRICHMENT_*`、`LLM_*` 错误码映射，不接管 `ErrorMapper` 基础实现。
- `backend/app/db/base.py` — 只追加 enrichment ORM metadata 导入，不接管数据库基础设施。
- `backend/app/cases/service.py` — 不改案例契约，仅供 `CaseSnapshotProvider` 读详情。

## System Flows

### 案例增强流程

```mermaid
sequenceDiagram
    participant Client
    participant Router
    participant Service
    participant CaseProvider
    participant LLM
    participant Validator
    participant Repository
    Client->>Router: request enrichment
    Router->>Service: create run
    Service->>CaseProvider: load case snapshot
    Service->>Repository: store running state
    Service->>LLM: generate structured output
    LLM-->>Service: raw output
    Service->>Validator: validate schema
    Validator-->>Service: valid result or errors
    Service->>Repository: store result and status
    Service-->>Router: run result
    Router-->>Client: enrichment response
```



### 推荐文案生成流程

```mermaid
sequenceDiagram
    participant Retrieval
    participant Router
    participant CopyService
    participant LLM
    participant Validator
    Retrieval->>Router: current problem and ranked candidates
    Router->>CopyService: generate copy
    CopyService->>LLM: explain candidates
    LLM-->>CopyService: candidate explanations
    CopyService->>Validator: validate references
    Validator-->>CopyService: copy result or failure
    CopyService-->>Router: explanations without rerank
    Router-->>Retrieval: copy response
```



## Requirements Traceability


| Requirement | Summary     | Components                                          | Interfaces                 | Flows    |
| ----------- | ----------- | --------------------------------------------------- | -------------------------- | -------- |
| 1.1         | 只读取上游基础案例输入 | CaseSnapshotProvider, EnrichmentService             | EnrichmentRequest          | 案例增强流程   |
| 1.2         | 不存在或不可增强时拒绝 | CaseSnapshotProvider, ErrorMapper                   | ErrorResponse              | 案例增强流程   |
| 1.3         | 识别派生结果过期    | EnrichmentRepository, EnrichmentService             | EnrichmentStatusResponse   | 案例增强流程   |
| 1.4         | 不阻塞案例创建编辑   | EnrichmentJobRunner, EnrichmentRouter               | EnrichmentRunResponse      | 案例增强流程   |
| 1.5         | 上游契约变化重新校验  | CaseSnapshotProvider, OutputValidator               | CaseInputSnapshot          | 案例增强流程   |
| 2.1         | 问题摘要        | PromptCatalog, LLMClient, OutputValidator           | CaseEnrichmentOutput       | 案例增强流程   |
| 2.2         | 方案摘要        | PromptCatalog, LLMClient, OutputValidator           | CaseEnrichmentOutput       | 案例增强流程   |
| 2.3         | 内容不足不编造     | OutputValidator, EnrichmentService                  | EnrichmentValidationError  | 案例增强流程   |
| 2.4         | 摘要来源关联      | EnrichmentRepository, EnrichmentSchemas             | SourceReference            | 案例增强流程   |
| 2.5         | 派生内容不替换原始字段 | EnrichmentRepository, CaseSnapshotProvider          | CaseEnrichmentResult       | 案例增强流程   |
| 3.1         | 字段和标签建议     | PromptCatalog, LLMClient, OutputValidator           | StructuredSuggestions      | 案例增强流程   |
| 3.2         | 基础字段和推断建议区分 | EnrichmentSchemas, OutputValidator                  | SuggestedField             | 案例增强流程   |
| 3.3         | 标签校验失败或规范化  | OutputValidator                                     | TagSuggestion              | 案例增强流程   |
| 3.4         | 人工审核覆盖      | EnrichmentRepository, EnrichmentRouter              | ReviewRequest              | 案例增强流程   |
| 3.5         | 不反写基础案例字段   | EnrichmentService, CaseSnapshotProvider             | ReviewRequest              | 案例增强流程   |
| 4.1         | schema 校验   | OutputValidator, EnrichmentSchemas                  | CaseEnrichmentOutput       | 案例增强流程   |
| 4.2         | 校验失败不发布     | EnrichmentRepository, ErrorMapper                   | EnrichmentRunResponse      | 案例增强流程   |
| 4.3         | 发布可消费结果     | EnrichmentRepository                                | EnrichmentStatusResponse   | 案例增强流程   |
| 4.4         | 状态门控        | EnrichmentRepository, EnrichmentRouter              | EnrichmentStatusResponse   | 案例增强流程   |
| 4.5         | 输入版本和输出版本   | EnrichmentRepository                                | EnrichmentRunRecord        | 案例增强流程   |
| 5.1         | 推荐文案生成      | RecommendationCopyService, PromptCatalog, LLMClient | RecommendationCopyRequest  | 推荐文案生成流程 |
| 5.2         | 引用候选案例      | OutputValidator, RecommendationCopyService          | RecommendationCopyItem     | 推荐文案生成流程 |
| 5.3         | 信息不足不改变排序   | RecommendationCopyService, OutputValidator          | RecommendationCopyError    | 推荐文案生成流程 |
| 5.4         | 不决定排序召回     | RecommendationCopyService                           | RecommendationCopyResponse | 推荐文案生成流程 |
| 5.5         | 失败降级        | RecommendationCopyService, ErrorMapper              | RecommendationCopyResponse | 推荐文案生成流程 |
| 6.1         | 限制外发输入范围    | CaseSnapshotProvider, PromptCatalog                 | PromptInput                | 案例增强流程   |
| 6.2         | 提示词注入防护     | PromptCatalog, OutputValidator                      | PromptPolicy               | 案例增强流程   |
| 6.3         | 模型标识和状态审计   | LLMClient, EnrichmentRepository                     | EnrichmentRunRecord        | 案例增强流程   |
| 6.4         | 超时限流失败和重试   | LLMClient, EnrichmentJobRunner                      | RetryRequest               | 案例增强流程   |
| 6.5         | 隐私配置门控      | Config, LLMClient                                   | LLMProviderConfig          | 案例增强流程   |


## Components and Interfaces


| Component                 | Domain/Layer      | Intent                            | Req Coverage       | Key Dependencies                                   | Contracts      |
| ------------------------- | ----------------- | --------------------------------- | ------------------ | -------------------------------------------------- | -------------- |
| EnrichmentRouter          | API               | 暴露案例增强、状态、审核与推荐文案端点               | 1.1, 3.4, 4.4, 5.1 | EnrichmentService P0, RecommendationCopyService P0 | API            |
| EnrichmentSchemas         | API/Data Contract | 请求响应、输出 schema、状态枚举与错误结构          | 2.1, 3.1, 4.1, 5.2 | Pydantic P0                                        | API, State     |
| CaseSnapshotProvider      | Integration       | 读上游案例快照并固化输入版本                    | 1.1, 1.2, 1.5, 6.1 | CaseService P0                                     | Service        |
| EnrichmentService         | Domain Service    | 编排案例摘要、结构化建议、标签建议与审核状态            | 1.3, 2.5, 3.5, 4.3 | CaseSnapshotProvider P0, LLMClient P0              | Service        |
| RecommendationCopyService | Domain Service    | 对已排序候选生成推荐文案，不改排序                 | 5.1, 5.4, 5.5      | LLMClient P0, OutputValidator P0                   | Service        |
| PromptCatalog             | AI Boundary       | 任务 Prompt、输出格式与注入防护约束             | 2.1, 3.1, 6.2      | Config P0                                          | Service        |
| LLMClient                 | External Adapter  | 调用 `deepseek-v4-pro` 或兼容模型并统一错误形态 | 6.3, 6.4, 6.5      | External LLM P0                                    | Service        |
| OutputValidator           | Validation        | 解析并校验 LLM 结构化输出                   | 3.3, 4.1, 4.2, 5.2 | EnrichmentSchemas P0                               | Service        |
| EnrichmentRepository      | Data Access       | 持久化派生结果、运行记录、状态、错误与审核结果           | 2.4, 4.5, 6.3      | PostgreSQL P0                                      | Service, State |
| EnrichmentJobRunner       | Runtime           | 同步运行、轮询状态与未来异步扩展点                 | 1.4, 6.4           | EnrichmentService P0                               | Batch          |
| ErrorMapper               | API Support       | 统一 LLM 增强错误响应                     | 1.2, 4.2, 5.5      | FastAPI P0                                         | API            |


### API Layer

#### EnrichmentRouter


| Field        | Detail                       |
| ------------ | ---------------------------- |
| Intent       | 提供 LLM 增强与推荐文案 HTTP 入口       |
| Requirements | 1.1, 1.2, 3.4, 4.4, 5.1, 5.5 |


**API Contract**


| Method | Endpoint                                    | Request                      | Response                       | Errors             |
| ------ | ------------------------------------------- | ---------------------------- | ------------------------------ | ------------------ |
| POST   | `/api/a3-cases/{case_id}/enrichment-runs`   | `CreateEnrichmentRunRequest` | `EnrichmentRunResponse`        | 404, 409, 422, 503 |
| GET    | `/api/a3-cases/{case_id}/enrichment`        | path `case_id`               | `CaseEnrichmentStatusResponse` | 404                |
| POST   | `/api/a3-cases/{case_id}/enrichment/review` | `ReviewEnrichmentRequest`    | `CaseEnrichmentResultResponse` | 404, 409, 422      |
| POST   | `/api/recommendations/copy`                 | `RecommendationCopyRequest`  | `RecommendationCopyResponse`   | 422, 503           |
| POST   | `/api/enrichment-runs/{run_id}/retry`       | path `run_id`                | `EnrichmentRunResponse`        | 404, 409, 503      |


**Implementation Notes**

- 创建增强运行可支持 `wait_for_completion`，响应须始终带 `run_id` 与状态。
- 推荐文案接口不得返回新排序字段、相似度分值或过滤决策。
- 错误响应沿用上游统一结构，并新增稳定错误码。

### Domain Layer

#### EnrichmentService


| Field        | Detail                                      |
| ------------ | ------------------------------------------- |
| Intent       | 生成并管理案例 AI 派生内容                             |
| Requirements | 1.3, 2.1, 2.2, 2.3, 2.5, 3.1, 3.2, 3.5, 4.3 |


**Service Interface**

```python
class EnrichmentService:
    def create_enrichment_run(self, case_id: str, request: CreateEnrichmentRunRequest) -> EnrichmentRunResponse: ...
    def get_current_enrichment(self, case_id: str) -> CaseEnrichmentStatusResponse: ...
    def review_enrichment(self, case_id: str, request: ReviewEnrichmentRequest) -> CaseEnrichmentResultResponse: ...
    def retry_run(self, run_id: str) -> EnrichmentRunResponse: ...
```

- 前置条件：上游案例存在且状态可作增强输入（仅 `active` 或 `archived`，`draft` 不可增强）；生产 LLM 配置已通过隐私门控。
- 后置条件：成功则写入运行记录与派生结果；失败则记录失败阶段、错误类型与是否可重试。
- 不变量：不修改 `A3Case` 基础字段；仅校验通过且状态允许的结果可发布给下游。

#### RecommendationCopyService


| Field        | Detail                  |
| ------------ | ----------------------- |
| Intent       | 对已排序推荐候选生成解释文案          |
| Requirements | 5.1, 5.2, 5.3, 5.4, 5.5 |


**Service Interface**

```python
class RecommendationCopyService:
    def generate_copy(self, request: RecommendationCopyRequest) -> RecommendationCopyResponse: ...
```

- 前置条件：请求含当前问题、已排序候选列表、候选 `case_id`，以及可引用的案例摘要或基础字段。
- 后置条件：响应中文案项保持输入候选顺序与 `case_id` 引用。
- 不变量：不返回排序变更、不改动相似度、不过滤候选。

#### CaseSnapshotProvider


| Field        | Detail             |
| ------------ | ------------------ |
| Intent       | 将上游案例详情转成 LLM 输入快照 |
| Requirements | 1.1, 1.2, 1.5, 6.1 |


**Service Interface**

```python
class CaseSnapshotProvider:
    def load_snapshot(self, case_id: str) -> CaseInputSnapshot: ...
```

- Snapshot includes: `case_id`、基础 A3 字段、状态、过滤字段、`updated_at`、允许外发的文本片段。
- Snapshot excludes: 向量、推荐分值、反馈、未授权敏感扩展字段。

### AI Boundary

#### PromptCatalog


| Field        | Detail                      |
| ------------ | --------------------------- |
| Intent       | 管理 Prompt、输出 schema 指令与安全边界 |
| Requirements | 2.1, 2.2, 3.1, 5.1, 6.2     |


**Responsibilities & Constraints**

- 案例增强与推荐文案使用各自固定任务模板。
- 系统提示词中声明：忽略案例正文里的指令性内容，只抽取业务事实。
- 写明输出 JSON schema、字段长度、来源引用与禁止编造规则。

#### LLMClient


| Field        | Detail         |
| ------------ | -------------- |
| Intent       | 隔离云端 LLM 供应商调用 |
| Requirements | 6.3, 6.4, 6.5  |


**Service Interface**

```python
class LLMClient:
    def complete_json(self, request: LLMCompletionRequest) -> LLMCompletionResult: ...
```

- 前置条件：LLM 配置中的 `provider`、`model`、`base_url`、`timeout`、`privacy_acknowledged` 已配置；生产环境须确认供应商数据保留策略。Embedding 与 Reranker 由各自独立配置管理，不复用 LLM 接入参数。
- 错误：`LLM_TIMEOUT`、`LLM_RATE_LIMITED`、`LLM_PROVIDER_ERROR`、`LLM_PRIVACY_CONFIG_MISSING`、`LLM_INVALID_RESPONSE`。
- 日志：记供应商、模型、任务类型、状态与错误类型；不记完整案例正文。

### Validation and Data Layer

#### OutputValidator


| Field        | Detail              |
| ------------ | ------------------- |
| Intent       | 把 LLM 原始输出转成可信结构化结果 |
| Requirements | 3.3, 4.1, 4.2, 5.2  |


**Responsibilities & Constraints**

- 解析 JSON，校验必填字段、枚举、长度、来源引用与候选 `case_id`。
- 标签建议去重、去空、限制数量，校验通过后持久化为规范化标签字符串列表（不含理由）。
- 推荐文案校验：输入候选与输出文案一一对应，禁止新增候选或改动顺序。

#### EnrichmentRepository


| Field        | Detail                            |
| ------------ | --------------------------------- |
| Intent       | 持久化派生结果、运行状态、错误与审核结果              |
| Requirements | 2.4, 3.4, 4.2, 4.3, 4.4, 4.5, 6.3 |


**Service Interface**

```python
class EnrichmentRepository:
    def create_run(self, run: EnrichmentRunCreate) -> EnrichmentRunRecord: ...
    def complete_run(self, run_id: str, result: CaseEnrichmentResultCreate) -> EnrichmentRunRecord: ...
    def fail_run(self, run_id: str, error: EnrichmentErrorData) -> EnrichmentRunRecord: ...
    def get_current_result(self, case_id: str) -> CaseEnrichmentResultRecord | None: ...
    def mark_reviewed(self, case_id: str, review: ReviewEnrichmentRequest) -> CaseEnrichmentResultRecord: ...
```

## Data Models

### Domain Model

```mermaid
erDiagram
    A3Case ||--o{ CaseEnrichmentResult : has
    CaseEnrichmentResult ||--o{ CaseEnrichmentRun : generated_by
    RecommendationCopyRun ||--o{ RecommendationCopyItem : contains
```



`A3Case` 仍归上游所有。`CaseEnrichmentResult` 按案例存放当前派生内容，`CaseEnrichmentRun` 记录每次生成尝试。`RecommendationCopyRun` 只记录推荐文案这次 LLM 调用的审计、成本、模型标识与 schema 校验结果——不是推荐运行、召回记录或排序持久化；推荐运行与推荐项快照仍由 `cbr-retrieval-recommendation` 负责。

### Logical Data Model

**CaseEnrichmentResult**


| Field                    | Type     | Required | Notes                                                                 |
| ------------------------ | -------- | -------- | --------------------------------------------------------------------- |
| `enrichment_id`          | string   | yes      | 派生结果唯一标识                                                              |
| `case_id`                | string   | yes      | 上游案例标识                                                                |
| `case_updated_at`        | datetime | yes      | 生成所依据的案例更新时间                                                          |
| `status`                 | enum     | yes      | `pending_review`, `published`, `stale`, `validation_failed`, `failed` |
| `problem_summary`        | text     | no       | 问题摘要                                                                  |
| `solution_summary`       | text     | no       | 方案摘要                                                                  |
| `structured_suggestions` | object   | yes      | 问题类型、根因分类、适用场景建议                                                      |
| `tag_suggestions`        | array    | yes      | 规范化后的标签字符串列表（仅存标签值，不含理由）                                                |
| `source_references`      | array    | yes      | 来源字段引用                                                                |
| `output_version`         | string   | yes      | 输出 schema 版本                                                          |
| `reviewed_by`            | string   | no       | 审核人                                                                   |
| `reviewed_at`            | datetime | no       | 审核时间                                                                  |
| `created_at`             | datetime | yes      | 创建时间                                                                  |
| `updated_at`             | datetime | yes      | 更新时间                                                                  |


**CaseEnrichmentRun**


| Field                    | Type     | Required | Notes                                                              |
| ------------------------ | -------- | -------- | ------------------------------------------------------------------ |
| `run_id`                 | string   | yes      | 运行标识                                                               |
| `case_id`                | string   | yes      | 上游案例标识                                                             |
| `task_type`              | enum     | yes      | `case_enrichment`                                                  |
| `status`                 | enum     | yes      | `running`, `succeeded`, `failed`, `validation_failed`, `retryable` |
| `model_id`               | string   | yes      | 默认 `deepseek-v4-pro`                                               |
| `request_purpose`        | string   | yes      | 请求目的，如 `case_enrichment`、`recommendation_copy`                     |
| `case_updated_at`        | datetime | yes      | 输入版本                                                               |
| `input_contract_version` | string   | yes      | 上游案例输入契约版本                                                         |
| `mapping_version`        | string   | yes      | 本服务输入映射版本                                                          |
| `error_code`             | string   | no       | 失败错误码                                                              |
| `error_stage`            | string   | no       | `load_case`, `llm_call`, `parse`, `validate`, `persist`            |
| `retry_count`            | integer  | yes      | 重试次数                                                               |
| `started_at`             | datetime | yes      | 开始时间                                                               |
| `finished_at`            | datetime | no       | 结束时间                                                               |


**RecommendationCopyRun**


| Field                      | Type     | Required | Notes                          |
| -------------------------- | -------- | -------- | ------------------------------ |
| `copy_run_id`              | string   | yes      | LLM 文案调用审计标识，不等同推荐运行标识         |
| `query_text_hash`          | string   | yes      | 当前问题文本哈希，避免存过多原文               |
| `status`                   | enum     | yes      | `succeeded`, `failed`          |
| `candidate_case_ids`       | array    | yes      | 输入候选顺序                         |
| `items`                    | array    | yes      | 推荐文案结果                         |
| `model_id`                 | string   | yes      | 模型标识                           |
| `request_purpose`          | string   | yes      | 请求目的，固定为 `recommendation_copy` |
| `token_usage`              | object   | no       | 成本与用量审计                        |
| `schema_validation_status` | string   | yes      | 输出 schema 校验状态                 |
| `created_at`               | datetime | yes      | 创建时间                           |


### Physical Data Model

**Table: `case_enrichment_results`**

- Primary key: `enrichment_id`
- Foreign reference by value: `case_id`
- Indexes: `case_id`, `(case_id, status)`, `(case_id, case_updated_at)`
- JSONB fields: `structured_suggestions`, `tag_suggestions`, `source_references`

**Table: `case_enrichment_runs`**

- Primary key: `run_id`
- Indexes: `case_id`, `status`, `(case_id, started_at desc)`
- Stores model_id/status/error metadata, not full prompt body.

**Table: `recommendation_copy_runs`**

- Primary key: `copy_run_id`
- Indexes: `created_at`, `status`
- 仅存候选 ID、生成文案、用量与 schema 校验状态，供 LLM 调用审计；可按保留策略裁剪原始请求细节。不存检索候选、排序决策或推荐运行状态。

### Data Contracts & Integration

**CaseEnrichmentOutput**

- `problem_summary`：精炼文本；缺失时可标 `missing_information`。
- `solution_summary`：同上。
- `structured_suggestions`：`problem_type_suggestion`、`root_cause_category`、`applicable_scenarios`、`confidence_notes`。
- `tag_suggestions`：规范化标签列表（字符串数组），仅存标签值，不包含理由字段。
- `source_references`：来源字段列表，如 `problem_description`、`context`、`root_cause`、`solution_steps`、`outcome`。
- `missing_information`：结构化条目数组，每项含 `field`、`reason`、`blocking_level`（`required` | `recommended`）。摘要或推荐文案无法可靠生成时必须返回该字段，禁止编造。

**RecommendationCopyResponse**

- `items` 保持输入候选顺序。
- 每项含 `case_id`、`reason`、`reference_points`、`cautions`、`source_references`。
- 响应不含相似度改动、rerank 分值改动、过滤决策或新候选 ID。

## Error Handling

### Error Strategy

- 输入错误：返回字段级或案例级错误，不生成已发布结果。
- LLM 供应商错误：写入失败或可重试的运行记录。
- Schema 校验失败：不发布结果，保留校验明细供运维排查。
- 推荐文案失败：返回明确失败或部分成功；下游仍可展示检索候选。

### Error Categories and Responses

- **User Errors (4xx)**：缺 `case_id`、审核载荷无效、候选列表无效。
- **Business Logic Errors (409/422)**：案例不符合增强条件、审核目标已过期、输出校验失败、不允许重试。
- **External Dependency Errors (503)**：LLM 超时、限流、供应商故障、隐私配置缺失。
- **System Errors (5xx)**：数据库持久化失败或未预期运行时错误。

### Monitoring

- 记录运行生命周期：已请求、LLM 调用开始、校验通过/失败、已持久化、已重试。
- 指标：运行成功率、校验失败率、供应商超时率、重试次数、平均耗时。
- 日志须脱敏完整案例正文与 Prompt；保留 `case_id`、`run_id`、`request_purpose`、`model_id`、status、error code。

## Testing Strategy

### Unit Tests

- `OutputValidator` 拒绝畸形 JSON、缺字段、非法枚举、无效 `case_id` 引用与超长文本。
- `PromptCatalog` 各任务类型含注入防护约束与固定 schema 指令。
- `EnrichmentService` 在案例 `updated_at` 晚于最近一次已发布结果时将结果标为 stale。
- `RecommendationCopyService` 保持候选顺序，拒绝新增或缺失候选解释。
- `LLMClient` 将超时、限流、供应商错误与隐私配置缺失映射为稳定错误码。

### Integration Tests

- POST `/api/a3-cases/{case_id}/enrichment-runs`：加载上游快照、创建运行、校验 mock LLM 输出并写入已发布或待审核结果。
- GET `/api/a3-cases/{case_id}/enrichment`：返回当前状态，含 stale 与 validation_failed。
- POST `/api/a3-cases/{case_id}/enrichment/review`：写入审核覆盖，不修改 `a3_cases`。
- POST `/api/recommendations/copy`：每位候选一条解释，顺序不变。
- 重试接口：仅对可重试的失败运行重试，并递增重试计数。

### Security and Privacy Tests

- 生产 LLM：未确认供应商数据保留或未配 API 时 fail-closed。
- 案例正文中的注入文案不得改写输出 schema或索要隐藏字段。
- 日志与失败运行记录不含完整 Prompt 或完整案例正文。
- 外发载荷仅含任务所需字段。

### Performance / Load

- 案例增强状态查询走索引 `case_id` 与 status。
- LLM 超时与重试配置避免请求线程无限阻塞。
- 推荐文案生成的候选数量以上游 CBR 推荐给出的上限为界，不接受无界列表。

## Security Considerations

- 案例内容视为敏感业务数据；外发 LLM 仅带任务所需最少字段。
- 生产须显式配置三套独立参数：LLM、Embedding、Reranker 各自的 provider、model、base_url、API key 来源、超时、重试上限与数据保留确认。
- 系统提示词须要求模型忽略案例正文内的指令，仅输出约定 schema。
- 不向终端用户暴露供应商原始错误、Prompt 或完整输出；对外给稳定码与运维可读说明。

## Performance & Scalability

- MVP 可在运行记录后同步执行生成；API 仍暴露状态，日后换异步 worker 不破坏客户端契约。
- 重试有配置上限，仅允许供应商/瞬时类失败重试。
- 推荐文案请求的候选数以 CBR 推荐的 Top-K 为上限；本规格不额外拉候选。

## Migration Strategy

```mermaid
flowchart TD
    Start[Start] --> AddTables[AddTables]
    AddTables --> AddConfig[AddConfig]
    AddConfig --> RegisterRouter[RegisterRouter]
    RegisterRouter --> RunTests[RunTests]
    RunTests --> Ready[Ready]
```



迁移只新增 LLM 派生结果表、增强运行记录表与推荐文案运行记录表，不改 `a3_cases`。回滚时删除本规格新增表与索引即可，不影响案例基础数据。
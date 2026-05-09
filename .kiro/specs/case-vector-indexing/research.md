# Research & Design Decisions

## Summary

- **Feature**: `case-vector-indexing`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - 本规格处于 `a3-case-management` 与 `llm-case-enrichment` 下游，仅消费稳定案例字段、案例状态、过滤字段、`updated_at`，以及已发布或明确可消费的 LLM 派生文本。
  - roadmap 和产品文档要求 PostgreSQL + pgvector 单库部署，pgvector 版本锁定至 `0.8.2+`，embedding 默认通过云端接入点 `bge-large-zh` 生成。
  - pgvector 0.8.x 支持 HNSW 索引、过滤查询优化和迭代扫描。`0.8.2` 修复了并行 HNSW 索引构建相关的安全漏洞，应作为最低版本约束。

## Research Log

### 并发假设与防抖策略

- **Context**: 需要明确向量索引刷新的并发场景，决定是否需要数据库层并发控制（如乐观锁、悲观锁、分布式锁）。
- **Sources Consulted**:
  - `.kiro/specs/llm-case-enrichment/design.md` §2.6 "Cross-Spec Transaction: '提交且摘要'"（L57-59）
  - 产品流程分析：案例保存 → LLM 增强 → 向量索引的异步触发链路
- **Findings**:
  - **正常流程完全串行**：用户提交案例后，后端保存案例并立即返回成功，然后异步触发 LLM 增强，LLM 增强完成后再异步触发向量索引。整个链路完全串行，不存在并发问题。
  - **并发问题仅发生在用户多次重试**：当 LLM 增强或向量索引失败后，用户可能在短时间内多次点击"重试"按钮，触发同一案例的并发刷新请求。
  - **数据库层并发控制不适用**：由于正常流程串行，数据库层的唯一约束（`case_id + is_current=true`）仅用于保证数据完整性（防止代码逻辑错误导致同一案例产生多条当前有效向量），不是并发控制手段。
- **Implications**:
  - **Router 层防抖机制**：在 API 入口处实现防抖，使用内存 set 记录正在进行的刷新任务（`case_id`），若检测到重复请求则返回 409 错误（`VECTOR_REFRESH_IN_PROGRESS`）。
  - **超时自动清理**：防抖锁超时时间为 120 秒，超时后自动清理，避免因异常情况导致锁永久占用。
  - **未来扩展**：MVP 阶段使用内存 set（单节点部署），未来多节点部署时可替换为 redis。
  - **简化状态机**：去掉 `queued`、`retryable`、`cancelled` 等复杂状态，只保留 `running`、`succeeded`、`failed`。MVP 阶段刷新任务在请求线程内同步执行。
  - **简化 Repository**：去掉 `publish_vector` 的并发冲突处理逻辑（409 重试），若触发唯一约束冲突则直接抛出异常（理论上不应该发生）。

### 上游规格契约

- **Context**: 本规格依赖 `a3-case-management` 和 `llm-case-enrichment`，需准确复用其已定义的字段和边界。
- **Sources Consulted**:
  - `.kiro/specs/a3-case-management/requirements.md`
  - `.kiro/specs/a3-case-management/design.md`
  - `.kiro/specs/llm-case-enrichment/requirements.md`
  - `.kiro/specs/llm-case-enrichment/design.md`
- **Findings**:
  - `a3-case-management` 拥有 `A3Case` 基础实体、`case_id`、状态、过滤字段、`created_at`、`updated_at`，并明确不保存向量、相似度、推荐或反馈字段。
  - `llm-case-enrichment` 拥有 `CaseEnrichmentResult` 和运行状态，发布可消费派生内容，但不生成 embedding，不负责 pgvector，也不决定候选搜索、过滤或排序。
  - 推荐文案接口和推荐排序属于 LLM/CBR 下游边界，本规格仅提供候选向量搜索结果。
  - 问题侧索引 embedding 的七个输入段落与 `A3Case` / `CaseEnrichmentResult` 字段的一一（含同段多字段）映射已写入 **`design.md`** 中 `EmbeddingInputComposer` 小节 **「问题侧 embedding 输入段落与上游字段映射（案例索引）」**，以实现时可据此实现 Composer 与快照测试。
- **Implications**:
  - 设计中引入 `CaseIndexSourceProvider`，只读取案例快照和可消费派生结果，不修改上游数据。
  - 向量表通过 `case_id` 关联上游案例，但不反向扩展 `a3_cases` 表。
  - 输入版本应包含 `case_updated_at`、`enrichment_id`、`enrichment_status` 和输入文本指纹，以支持过期判断。

### pgvector 版本与索引能力

- **Context**: roadmap 明确要求 PostgreSQL + pgvector，版本 `0.8.2+`，MVP 不引入独立向量数据库。
- **Sources Consulted**:
  - [pgvector GitHub](https://github.com/pgvector/pgvector)
  - [pgvector 0.8.2 Released](https://www.postgresql.org/about/news/pgvector-082-released-3245/)
  - AWS Database Blog: pgvector 0.8.0 filtered vector search and iterative scans
- **Findings**:
  - pgvector 支持 `vector(n)` 数据类型、HNSW 和 IVFFlat 索引。HNSW 适合低延迟近似最近邻检索。
  - HNSW 支持 cosine、L2、inner product 等距离操作符。中文语义候选搜索通常以 cosine 距离作为默认相似度度量。
  - `0.8.0` 引入 iterative scan，可改善带过滤条件的 ANN 候选搜索；过滤字段仍需常规 B-tree/GIN 索引辅助。
  - `0.8.2` 修复了并行 HNSW 索引构建相关的缓冲区溢出漏洞。
- **Implications**:
  - 物理模型使用 `vector(1024)` 作为默认 BGE-M3 向量列，以 HNSW + cosine 操作类作为默认索引策略。
  - 品牌、门店、问题类型、状态、标签和更新时间需建立独立索引，以支撑过滤后的 Top-K 搜索。
  - 运行环境必须在迁移或启动检查中验证 pgvector 版本不低于 `0.8.2`。

### BGE-M3 与远程模型接入

- **Context**: 产品和 roadmap 要求通过云端 embedding API 使用 BGE-M3，默认模型为 `bge-large-zh`。
- **Sources Consulted**:
  - [BAAI/bge-m3 Hugging Face](https://huggingface.co/BAAI/bge-m3)
  - BGE-M3 model documentation and model card summaries
- **Findings**:
  - BGE-M3 dense embedding 常见输出维度为 1024，支持多语言和长文本输入。
  - 项目约束使用远程模型 `bge-large-zh` 及独立 api_key/base_url，因此实现不能绑定本地 FlagEmbedding 或本地推理。
  - 供应商 API 的认证、超时、限流和隐私配置会影响生产可用性。
- **Implications**:
  - 设计将维度作为配置和运行校验项，默认值 1024，避免供应商变更时产生静默错误。
  - `EmbeddingClient` 只抽象远程调用，不包含本地模型加载、批量训练或成本优化逻辑。
  - 生产启用前必须校验 provider、model、base_url、凭据来源、超时、重试和供应商数据保留确认。

### 现有代码结构

- **Context**: 需要确定实施文件结构和是否复用现有模块。
- **Sources Consulted**:
  - 仓库 glob：`backend/**/*.py`、`pyproject.toml`、`package.json`
  - 相关规格文件的 File Structure Plan
- **Findings**:
  - 当前仓库尚无后端或前端应用代码。
  - `a3-case-management` 设计计划创建 `backend/app/cases`、数据库配置、统一错误结构和测试基础。
  - `llm-case-enrichment` 设计计划创建 `backend/app/enrichment`，并通过 `CaseSnapshotProvider` 读取上游案例。
- **Implications**:
  - 本规格应在同一 FastAPI 后端中新增 `backend/app/vector_indexing` 模块。
  - 实施任务必须显式依赖上游后端基础结构和案例/增强读取契约。
  - 文件计划不能假设已有代码落地，需将迁移、配置、运行检查和测试纳入任务。

## Architecture Pattern Evaluation


| Option        | Description                                    | Strengths              | Risks / Limitations                      | Notes    |
| ------------- | ---------------------------------------------- | ---------------------- | ---------------------------------------- | -------- |
| 轻量分层模块        | Router、Service、Repository、Client、Job Runner 分层 | 与上游 FastAPI 规格一致，实施成本低 | 若未来事件量大，需引入异步队列扩展                        | Selected |
| 独立向量服务        | 单独服务管理 embedding 和向量搜索                         | 可独立扩缩容                 | 超出 MVP 范围，增加部署复杂度                        | Rejected |
| 推荐编排强绑定检索层 | 直接按推荐编排内部格式建索引和搜索                          | 下游接入快                  | 违反 roadmap 的边界解耦约束，并混淆向量索引与推荐编排 | Rejected |
| 专用向量数据库       | 使用 Milvus 等独立向量库                               | 大规模候选搜索能力强             | 超出 MVP 和单库部署约束                           | Rejected |


## Design Decisions

### Decision: 使用 PostgreSQL + pgvector 作为当前向量存储

- **Context**: MVP 需验证案例入库、向量检索和相似案例推荐的最小闭环，roadmap 要求单库优先。
- **Alternatives Considered**:
  1. PostgreSQL + pgvector — 与业务数据同库，事务和过滤字段整合简单。
  2. Milvus — 更适合大规模向量检索，但部署和运维复杂。
- **Selected Approach**: 在 PostgreSQL 中新增独立向量表和运行记录表，启用 pgvector `0.8.2+`，默认使用 HNSW cosine 索引。
- **Rationale**: 满足 MVP 单库部署、过滤字段联查、审计和一致性要求。
- **Trade-offs**: 超大规模候选搜索可能需未来迁移至专用向量库；当前设计通过接口边界保留迁移空间。
- **Follow-up**: 实施阶段验证 pgvector 版本、向量维度和索引构建参数。

### Decision: 主召回向量只表达问题侧语义画像

- **Context**: 用户检索时提交的是当前问题，初筛召回应优先匹配历史案例的“问题相似度”，而不是被解决步骤、效果结果或方案摘要影响。
- **Alternatives Considered**:
  1. 直接将完整案例或多段整案文本发送给 embedding 服务。
  2. 只使用 LLM 的 `problem_summary` 建立向量。
  3. 使用问题摘要、问题描述、问题类型、场景上下文、根因分类、适用场景和标签组成问题侧语义画像。
- **Selected Approach**: `EmbeddingInputComposer` 输出带来源分段、内容指纹和来源版本的问题侧输入文本；主召回向量排除解决步骤、效果结果、方案摘要和推荐文案，`EmbeddingClient` 只负责远程 embedding 调用。
- **Rationale**: 问题侧语义画像能与用户问题查询保持同构，减少解法文本污染召回；相比只用问题摘要，又保留了问题类型、场景和标签等有助于中文业务召回的短语。
- **Trade-offs**: 需维护输入模板版本，并在下游通过 reranker、结构化局部相似度和业务参数分补足“案例是否值得参考”的判断。
- **Follow-up**: 实施阶段为输入模板编写快照测试，验证解决方案和效果字段不会进入主召回 payload。

### Decision: 向量搜索只提供候选原语

- **Context**: 下游 `cbr-retrieval-recommendation` 消费本规格输出的候选向量搜索结果，并负责分数加权聚合、reranker 和推荐解释。
- **Alternatives Considered**:
  1. 本规格直接返回推荐结果。
  2. 本规格只返回 Top-K 候选、相似度和索引元数据。
- **Selected Approach**: `VectorSearchService` 只暴露查询向量生成、pgvector 过滤、Top-K 候选和状态元数据。
- **Rationale**: 避免吸收推荐职责，保持边界解耦；分数加权聚合只应在下游候选集内执行。
- **Trade-offs**: 下游需自行组合推荐上下文，但职责边界清晰。
- **Follow-up**: 下游规格变更搜索请求或响应时触发本规格重校验。

## Risks & Mitigations

- **embedding 供应商限流或超时导致索引滞后** — 通过运行记录、可重试状态、重试上限和状态查询缓解。
- **LLM 派生结果过期但向量未刷新** — 用 `case_updated_at`、`enrichment_id` 和输入指纹判定过期。
- **过滤条件与 ANN 搜索组合导致候选搜索不稳定** — 使用过滤字段索引、HNSW iterative scan 配置和集成测试验证。
- **向量维度与模型响应不一致** — 通过配置化维度和响应校验拒绝发布。
- **日志泄露案例正文或向量** — 日志只记录标识、状态、错误码和哈希，不记录全文或向量数组。

## References

- [pgvector GitHub](https://github.com/pgvector/pgvector) — pgvector 数据类型、HNSW、距离操作符和过滤查询能力。
- [PostgreSQL: pgvector 0.8.2 Released](https://www.postgresql.org/about/news/pgvector-082-released-3245/) — `0.8.2` 安全修复和版本约束依据。
- [BAAI/bge-m3 Hugging Face](https://huggingface.co/BAAI/bge-m3) — BGE-M3 维度和多语言能力背景。
- `docs/product-overview.md` — 产品权威入口与能力闭环。
- `docs/mvp-product.md` — MVP 技术栈、案例向量化入库和检索流程。
- `.kiro/steering/roadmap.md` — 规格边界、依赖顺序和边界解耦约束。


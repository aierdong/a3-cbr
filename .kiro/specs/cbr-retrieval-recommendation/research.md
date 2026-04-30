# Research & Design Decisions

## Summary

- **Feature**: `cbr-retrieval-recommendation`
- **Discovery Scope**: Complex Integration
- **Key Findings**:
  - 上游规格已经把案例基础字段、LLM 推荐文案和候选向量搜索原语分开，本规格应只编排检索推荐，不反向拥有上游数据生命周期。
  - 推荐目标是 Hybrid CBR：硬过滤去除明显无关案例，问题语义向量做初筛，reranker 生成纯语义相似度，结构化派生字段和业务参数提供可解释的局部评分，CBRKit 聚合最终排序。
  - CBRKit 适合作为候选集内的可替换编排/重排适配层，但持久化模型和对外响应契约必须由系统自身定义。
  - `qwen3-reranker-8b` 是远程重排默认 model，应通过独立 `provider/model/base_url` 配置和适配层记录分值、状态、耗时和降级原因。

## Research Log

### 上游规格契约

- **Context**: 本规格依赖 `a3-case-management`、`llm-case-enrichment` 和 `case-vector-indexing`。
- **Sources Consulted**: `.kiro/specs/a3-case-management/requirements.md`、`.kiro/specs/a3-case-management/design.md`、`.kiro/specs/llm-case-enrichment/requirements.md`、`.kiro/specs/llm-case-enrichment/design.md`、`.kiro/specs/case-vector-indexing/requirements.md`、`.kiro/specs/case-vector-indexing/design.md`。
- **Findings**:
  - 案例基础数据由 `A3Case` 和案例管理 API 提供，推荐不能写回案例基础字段。
  - LLM 增强的 `RecommendationCopyService` 只解释已排序候选，不改变排序。
  - 向量索引的 `/api/vector-search` 只返回候选原语、相似度、索引版本和过滤元数据，不承担推荐排序；本规格不直接生成 embedding 或查询 pgvector。
- **Implications**:
  - 本规格需要新增 retrieval 模块，消费上游公开契约。
  - 推荐运行记录保存查询哈希、候选引用、分值和状态，但不保存反馈结果。
  - 最终响应必须同时包含向量分值、语义相似度分、结构化局部相似度、业务参数分、最终聚合分、解释状态和可追溯引用。

### CBRKit 候选编排能力

- **Context**: Roadmap 要求 CBRKit 可替换，且核心持久化不与其强绑定。
- **Sources Consulted**: CBRKit GitHub/文档搜索结果、PyPI/GitHub 描述、ICCBR 2024 论文摘要。
- **Findings**:
  - CBRKit 是 Python CBR 工具包，提供检索流水线、CBR cycle 编排、System 封装和可组合相似度/重排能力。
  - CBRKit 可以直接从 casebase 执行检索，但本规格只允许它处理 `case-vector-indexing` 已返回的候选集。
  - CBRKit 支持把检索、复用、修正、保留拆成可组合阶段，适合本规格在候选集内采用 rerank/assemble 相关能力。
  - CBRKit 的生态规模小于主流 Web 框架，不能把系统数据模型或 API 契约绑定到它的内部对象。
- **Implications**:
  - 设计采用 `CBROrchestrator` 端口封装 CBRKit，领域层使用系统自定义 `RetrievalCandidate`、`RerankedCandidate` 和 `RecommendationItem`。
  - `CBROrchestrator` 不从全量 SQL casebase 重新加载案例，只接收向量候选和补齐后的候选快照。
  - CBRKit 失败时可降级为向量顺序候选，不影响向量搜索契约和响应结构。

### Qwen3-Reranker-8B 重排接入

- **Context**: 本规格需要使用默认 model `qwen3-reranker-8b` 重排候选，并支持独立 provider/base_url。
- **Sources Consulted**: Qwen/Qwen3-Reranker-8B 模型卡、vLLM/DeepInfra/Fireworks 相关 API 说明搜索结果。
- **Findings**:
  - Qwen3-Reranker-8B 是 instruction-aware cross-encoder reranker，常见形态是输入 query 与 documents，输出相关性分值。
  - 部署方可能提供 `/v1/rerank` 或 `/score` 类接口，响应字段随供应商不同而变化。
  - 模型适合基于查询和候选文档做精排，但需要限制候选数量和输入长度以控制延迟。
- **Implications**:
  - 设计通过 `RerankerClient` 统一供应商差异，默认模型 id 固定为 `qwen3-reranker-8b`。
  - 响应保存 `semantic_similarity_score`、模型 id、调用状态和耗时，最终排序由 CBRKit 聚合结果决定。
  - 重排失败时返回降级状态，按向量候选原始顺序组装结果。

### 产品与 MVP 边界

- **Context**: `docs/product-overview.md` 作为产品权威入口，覆盖长期自动推送和行业库愿景；`docs/mvp-product.md` 仅补充 MVP 范围收敛。
- **Sources Consulted**: `docs/product-overview.md`、`.kiro/steering/roadmap.md`。
- **Findings**:
  - MVP 重点是手动输入问题、Top-K 相似案例、推荐理由、相似度分值和基础过滤。
  - 自动推送渠道、经营指标触发、巡检触发、行业库高权重候选搜索不在当前规格。
  - LLM 可辅助推荐解释，但不承担主检索职责。
- **Implications**:
  - 本规格只提供手动检索入口的后端契约，不实现 App 消息、邮件或前端页面。
  - 过滤字段与向量索引字段保持一致，MVP 仅使用品牌、门店、问题类型、标签、状态和时间范围等上游已支持字段。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| CBRKit 直连持久化 | 让 CBRKit 内部对象直接读取全量数据库并保存推荐运行 | 快速接入 | 数据模型与 CBRKit 强绑定，替换成本高；还会绕过向量索引边界 | Rejected |
| 系统契约 + CBRKit 适配器 | 系统定义查询、候选、排序和响应契约，CBRKit 只做编排适配 | 可替换、可测试、边界清晰 | 需要额外适配层 | Selected |
| 纯自研排序流水线 | 不接入 CBRKit，只手写向量候选重排 | 依赖少 | 不符合 roadmap，CBR 扩展能力弱 | Rejected |

## Design Decisions

### Decision: 使用系统契约隔离 CBRKit

- **Context**: CBRKit 必须可替换，且持久化数据模型不能与其强绑定；向量候选必须来自 `case-vector-indexing`，不能由 CBRKit 重新从全量 SQL casebase 发起候选搜索。
- **Alternatives Considered**:
  1. 直接保存 CBRKit 输出对象。
  2. 让 CBRKit 从全量 SQL casebase 加载案例并执行检索。
  3. 只在适配器内部使用 CBRKit 处理向量搜索已返回的候选，外部使用系统自定义结构。
- **Selected Approach**: `CBROrchestrator` 接收系统候选对象及其向量分、语义分、结构化局部相似度、业务参数分和权重配置，调用 CBRKit 适配层后返回系统定义的聚合排序结果。
- **Rationale**: 保留 CBRKit 作为候选编排和聚合能力，同时避免对外 API、数据库和任务边界依赖其内部结构，也避免重复承担向量索引职责。
- **Trade-offs**: 需要多一层映射，但换来替换空间和更清晰测试。
- **Follow-up**: 实施阶段确认 CBRKit 版本和具体流水线 API 后更新适配器实现，不改变领域契约。

### Decision: 使用 Hybrid CBR 分值拆分与聚合

- **Context**: 用户查询是当前问题，单一向量分无法表达业务适配度；同时，品牌、问题类型等字段需要作为硬过滤或业务权重，而不是混进 embedding。
- **Alternatives Considered**:
  1. 只按向量相似度排序。
  2. reranker 直接决定最终排序。
  3. 拆分语义相似度、结构化局部相似度和业务参数分，再由 CBRKit 聚合。
- **Selected Approach**: 向量搜索负责问题语义初筛；reranker 生成纯语义相似度；`structured_suggestions` 生成局部相似度；品牌、业态、门店等级、时间等生成业务参数分；CBRKit 按默认权重和受控请求权重聚合最终分。
- **Rationale**: 分值来源清晰，便于解释和调参；主召回保持问题相似，业务适配通过显式权重影响最终排序。
- **Trade-offs**: 需要更多评分元数据和测试；MVP 可先将结构化局部相似度标记为 skipped，但保留契约。
- **Follow-up**: 实施阶段先锁定默认权重与业务因子范围，避免用户传入无界权重导致排序不可控。

### Decision: 推荐运行记录只保存可审计元数据

- **Context**: 下游反馈需要引用推荐运行，但本规格不能吸收反馈持久化。
- **Alternatives Considered**:
  1. 保存完整查询、候选正文和解释文本。
  2. 保存查询哈希、候选引用、分值、状态和必要摘要。
- **Selected Approach**: `RecommendationRun` 保存运行标识、查询哈希、过滤条件、候选数量、模型 id、降级状态；`RecommendationItemSnapshot` 保存候选引用和分值。
- **Rationale**: 支持审计和反馈关联，同时降低敏感文本和供应商输出保留风险。
- **Trade-offs**: 深度问题排查可能需要结合请求日志和上游案例详情。
- **Follow-up**: 与反馈规格对齐 `run_id` 和 `recommendation_item_id` 引用。

### Decision: 重排失败降级到向量顺序

- **Context**: MVP 需要可用的相似案例推荐，但远程 reranker 可能超时或失败。
- **Alternatives Considered**:
  1. 重排失败时整次请求失败。
  2. 重排失败时返回向量候选并标记降级。
- **Selected Approach**: 返回向量候选原始顺序或可用业务分降级顺序，保留向量相似度，缺省语义相似度或聚合分，并标记 `degraded_reason`。
- **Rationale**: 向量候选仍是有效来源，用户可继续查看结果；响应清楚暴露降级状态。
- **Trade-offs**: 降级结果质量可能低于重排结果。
- **Follow-up**: 测试降级响应不包含伪造语义分或聚合分。

## Risks & Mitigations

- CBRKit API 与实施期版本差异较大 — 通过适配器封装并用 fake orchestrator 覆盖核心测试。
- Reranker 延迟影响检索响应 — 限制候选数量、配置超时，失败时降级到向量顺序。
- 上游过滤字段扩展可能反向扩大推荐契约 — MVP 先保持过滤字段与案例管理和向量索引一致，新增字段需另行重校验。
- 推荐解释可能被误认为排序依据 — 响应中明确区分排序分值与自然语言解释状态。

## References

- `docs/product-overview.md` — 长期产品流程与 CBR 目标。
- `docs/mvp-product.md` — MVP 范围、技术栈和检索流程（补充来源）。
- `.kiro/steering/roadmap.md` — 规格依赖顺序和技术约束。
- `.kiro/specs/a3-case-management/design.md` — 案例基础契约。
- `.kiro/specs/llm-case-enrichment/design.md` — 推荐文案生成边界。
- `.kiro/specs/case-vector-indexing/design.md` — 向量搜索原语和候选响应。

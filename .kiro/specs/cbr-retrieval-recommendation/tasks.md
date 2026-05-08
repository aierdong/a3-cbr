# Implementation Plan

- [ ] 1. 建立检索推荐基础设施

- [ ] 1.1 扩展推荐检索配置与错误码
  - 增加相似案例推荐启用开关、Top-K 上限、向量候选上限、默认聚合权重、业务权重上限等通用项。
  - **复用 `llm-case-enrichment` 建立的多模型配置隔离基础设施**：使用 `NormalizerLLMConfig`（供 `QueryNormalizer` 使用）和 `RerankerConfig`（供 `RerankerClient` 使用），这两个配置类由 `llm-case-enrichment` 规格在 `backend/app/core/config.py` 中定义。本规格只定义调用契约和配置命名空间，不拥有配置类定义或共享 `LLMClient` 实现。
  - 确保 `NormalizerLLMConfig` 和 `RerankerConfig` 通过依赖注入传递给各自的客户端，不与 `EnrichmentLLMConfig`、`EmbeddingConfig` 混用。
  - 增加检索、向量候选消费、LLM normalizer、结构化局部评分、业务评分、分值聚合、重排和解释降级相关错误码。
  - 仅向共享配置和错误映射追加本规格所需配置值与错误码，不拥有 `backend/app/core/config.py`、`backend/app/core/errors.py` 或 `ErrorMapper` 基础实现。
  - 完成后，生产配置缺失时可以 fail closed，错误响应包含稳定错误码；模型配置与其他规格隔离。
  - _Requirements: 1.3, 1.6, 1.7, 2.4, 3.4, 6.3, 6.4, 7.4, 7.5_

- [ ] 1.2 建立推荐运行和推荐项快照存储
  - 创建推荐运行和推荐项快照的数据结构，用于保存运行标识、查询哈希、过滤条件、业务权重、候选引用、分值明细和降级状态。
  - **迁移与 ORM**：在 `recommendation_runs` 表增加独立列 **`contract_version`**（建议 `varchar(64) NOT NULL`，与 `design.md` 物理模型一致）；SQLAlchemy/Alembic 迁移与 `backend/app/retrieval/models.py`（或等价 ORM）同步纳入该列；**`reranker_status` 列 `NOT NULL`，数据库默认 `'pending'`**（与 `design.md`「Reranker 状态语义」一致）。
  - **`contract_version` 语义**：运行级依赖契约快照标识（应用常量或配置注入，如 `mvp-1` / semver），须在本规格 **Version & Compatibility Policy** 与实现对齐；本条记录在 **`create_run` 时写入一次**，**`fail_run` / `complete_run` 不得改写该列**。
  - **`recommendation_item_id` 约束**：生成或写入推荐项快照前须校验 `recommendation_item_id` 不等于字面字符串 `'RUN'`（该取值保留给下游 `recommendation-feedback` 表示运行级反馈持久化哨兵，见 Requirement 7.6）；若冲突则视为内部错误并 fail closed。
  - 数据结构只保存上游标识、分值和轻量元数据，不保存完整问题原文、完整案例正文、向量数组或反馈结果。
  - 完成后测试数据库可以应用迁移，并通过运行标识查询推荐运行和排序项。
  - _Requirements: 2.5, 4.3, 4.5, 6.1, 6.2, 6.5, 7.6_

- [ ] 1.3 定义检索请求、过滤、候选和响应契约
  - 定义相似案例推荐请求、过滤条件、业务权重参数、`NormalizedRetrievalQuery`（含单次 LLM normalizer 产出的标准化检索文本与 `query_structured_suggestions`）、推荐运行状态、推荐项、降级状态和错误响应契约。
  - 响应契约包含推荐运行标识、**`contract_version`（与 `recommendation_runs.contract_version` 一致）**、推荐项标识、应用后的过滤条件、有效权重、候选数量、分值明细、解释状态和来源引用；**GET** `/api/recommendations/runs/{run_id}` 的 **`RecommendationRunResponse`** 运行级元数据须包含同名 **`contract_version`**。
  - 完成后 API、服务、测试和下游反馈可复用同一套稳定 schema。
  - _Requirements: 1.1, 1.2, 1.5, 3.2, 4.1, 4.2, 5.4, 6.2_
  - _Boundary: RetrievalSchemas_

- [ ] 2. 实现查询、向量候选消费和候选准备

- [ ] 2.1 实现 QueryNormalizer、过滤和业务权重校验
  - 实现 **`QueryNormalizer`**：校验当前问题文本、Top-K、时间范围、过滤字段格式和业务权重范围；通过**共享 `LLMClient`**（位于 `backend/app/common/llm_client.py`，由 `llm-case-enrichment` 规格建立）执行单次 LLM normalizer 外呼，传入 `NormalizerLLMConfig` 配置对象（由 `llm-case-enrichment` 规格在 `backend/app/core/config.py` 中定义）。
  - 单次 LLM normalizer 外呼返回可被 schema 校验的结构化结果，包含标准化检索文本与 `query_structured_suggestions`；失败路径严格执行 Requirement `1.7`（fail closed，不得用原始 `query_text` 兜底检索）。
  - 将品牌、门店、问题类型、标签、状态和创建时间范围映射为推荐流程可消费的硬过滤条件；对未列入上游契约的过滤字段返回字段级错误。
  - 完成后非法请求在调用向量搜索端口前返回字段级错误；合法请求产出 `NormalizedRetrievalQuery`（含同窗结构化画像），并回显规范化过滤条件与有效业务权重。
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 4.2_
  - _Boundary: QueryNormalizer (uses shared LLMClient with NormalizerLLMConfig)_

- [ ] 2.2 (P) 实现向量搜索端口
  - 调用上游向量搜索能力，提交标准化用户问题、Top-K 和规范化过滤条件，不直接生成案例 embedding 或查询 pgvector。
  - 将问题语义向量候选映射为推荐候选原语，保留案例标识、向量标识、问题语义相似度、距离、索引版本和过滤元数据。
  - 强制校验批次级 `search_ref` 与 `index_version`，以及候选级 `case_id`、`vector_id`、`similarity_score`、`index_status` 最小字段；任一字段缺失或不可解析按 `invalid_response` 失败路径处理，不编造候选。
  - 对齐依赖契约快照：固定最小必需字段校验与错误语义映射（`timeout`、`unavailable`、`invalid_response`），并记录契约版本信息。
  - 完成后空候选、可检索候选和向量搜索失败均能被稳定区分。
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: VectorSearchPort_

- [ ] 2.3 (P) 实现推荐候选案例快照读取
  - 根据向量候选读取上游案例详情和当前可消费的 `CaseEnrichmentResult`，补齐问题摘要、结构化建议、过滤字段摘要、核心解决步骤、效果结果和更新时间。
  - 对齐依赖契约快照：保证 `not_found` 与 `forbidden` 可区分，单候选失败仅标记缺失而非整批失败。
  - 对缺失摘要、结构化建议、解决步骤或效果信息的候选标记缺失字段，不直接移除候选。
  - 完成后推荐组装可以使用统一候选快照生成响应、结构化评分和重排输入。
  - _Requirements: 3.2, 5.2, 5.4, 5.5_
  - _Boundary: RecommendationCaseProvider_

- [ ] 3. 实现分值聚合、重排和解释

- [ ] 3.1 (P) 实现远程 reranker 适配
  - 接入默认 model `qwen3-reranker-8b`（可配置 provider/base_url），通过**共享 `LLMClient`**（位于 `backend/app/common/llm_client.py`）或独立 HTTP 客户端执行重排调用，传入 `RerankerConfig` 配置对象（由 `llm-case-enrichment` 规格在 `backend/app/core/config.py` 中定义）。
  - 提交标准化查询和候选问题画像文档并接收每个候选的纯语义相关性分值。
  - 统一处理超时、限流、供应商失败、配置缺失和不可解析响应。
  - 完成后成功响应返回可排序语义分值，失败响应返回稳定错误和耗时元数据。
  - _Requirements: 3.1, 3.4, 7.3, 7.4_
  - _Boundary: RerankerClient (uses RerankerConfig)_

- [ ] 3.2 (P) 实现结构化局部相似度和业务参数评分
  - 基于 `NormalizedRetrievalQuery.query_structured_suggestions` 与候选 `CaseEnrichmentResult.structured_suggestions` 计算问题类型、根因分类、适用场景和标签的局部相似度（查询侧结构化来自与检索文本同窗的 LLM normalizer，见任务 2.1）。
  - 根据业务权重和候选字段计算业态、门店等级、品牌、时间等业务参数分，并保留因子贡献明细。
  - MVP 可将结构化局部相似度标记为 skipped，但 schema、运行记录和响应必须预留。
  - 完成后每个候选都能获得可解释的结构化分和业务分元数据。
  - _Requirements: 3.2, 3.5, 4.2, 7.4_
  - _Boundary: StructuredSimilarityScorer, BusinessScoreCalculator_
  - _Depends: 2.1, 2.3_

- [ ] 3.3 实现分值加权聚合
  - 实现 `ScoreAggregator`：对候选集执行 min-max 归一化、缺失分项重加权（`w'_k = w_k / sum(w_j, j in A)`）和加权求和。
  - 将向量相似度、语义分、结构化局部相似度、业务参数分和有效权重聚合为最终排序分值。
  - 当无法得到可信聚合分（如 `aggregation_unavailable` 或进入定义的降级排序路径）时，将候选 `final_score` 置为 `0`，并在 `score_breakdown` 中显式标记“未聚合/默认值”语义，避免将 `0` 误解为真实聚合结果。
  - `ScoreAggregator` 只处理向量搜索已返回候选集，不从全量 SQL casebase 独立加载案例或发起检索。
  - 保证聚合器内部对象不进入数据库和 API 响应。
  - 完成后聚合成功时按最终聚合分排序，聚合失败时按故障矩阵降级：语义分优先；语义分缺失时业务分；仍不可用时向量顺序。
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_
  - _Boundary: ScoreAggregator_
  - _Depends: 3.1, 3.2_

- [ ] 3.4 实现推荐解释和结构化降级
  - 调用上游推荐文案能力，为已排序候选生成推荐理由、可参考解决点、注意事项和来源引用。
  - 校验解释结果不新增候选、不删除候选、不改变候选顺序。
  - 完成后文案失败或信息不足时返回结构化降级解释，并保留解释状态。
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: RecommendationExplainer_
  - _Depends: 2.3_

- [ ] 4. 编排端到端推荐流程

- [ ] 4.1 实现推荐服务主流程
  - 串联 QueryNormalizer（通过共享 `LLMClient` + `NormalizerLLMConfig` 执行单次 LLM normalizer）、向量候选消费、候选快照读取、语义精排、结构化局部评分、业务评分、分值聚合、推荐解释和结果组装。
  - **实现 `RecommendationRunContext` 上下文管理器**（见 `design.md` RecommendationService 章节）：`__enter__` 执行 `create_run` 并返回 `run_id`；`__exit__` 保证运行记录终态一致性——若 `completed` 标记未置位且存在未捕获异常，须在 `__exit__` 中尽力写入 `fail_run`；提供 `complete()` 和 `fail()` 方法供主流程显式写入终态。替代方案为手写 `try/finally` + `run_completed` 标记（design.md 备选实现），但须保证同等终态语义。
  - **运行记录顺序**：进入主流程后 **先** `create_run`，再执行 LLM normalizer；Requirement `1.7` 失败时 **须** `fail_run` 且 POST 响应 **必须** 含 `recommendation_run_id`（不得在未建 run 的情况下返回 `1.7` 失败）。
  - 对空候选、候选不足、重排失败、聚合失败和解释失败分别返回成功、空结果或降级状态，并严格执行故障矩阵组合规则。
  - 当 reranker 与分值聚合同时失败时，按”业务分优先，业务分不可用再回退向量顺序”返回排序，并标记 `reranker_and_aggregation_failed`。
  - 完成后合法请求可以返回 Top-K 推荐项，并且每项包含案例引用、核心步骤、分值明细、解释和来源。
  - _Requirements: 1.4, 1.7, 2.3, 3.3, 3.4, 4.1, 4.4, 5.1, 5.3, 5.5, 6.1, 6.3, 7.1_
  - _Boundary: RecommendationService_
  - _Depends: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

- [ ] 4.2 实现推荐运行持久化和查询
  - **`create_run`** 写入 **`contract_version` 独立列**（取值来自配置或代码常量）；后续 **`fail_run` / `complete_run` 不更新该列**。
  - 保存每次检索的运行标识、查询哈希、应用过滤条件、有效业务权重、候选数量、返回数量、模型标识、耗时、降级状态和错误类型。
  - 保存每个推荐项的推荐项标识、案例引用、向量来源、向量分值、语义分、结构化局部相似度、业务分、最终聚合分、排序位置、解释状态和缺失字段。
  - **实现级联删除**：删除推荐运行或推荐项快照时，须同步调用 `recommendation-feedback` 的删除接口（`DELETE /api/recommendation-feedback`）清理关联反馈记录；反馈删除失败不阻塞推荐记录删除，但须记录告警日志。实现 `delete_recommendation_run`（先删快照 → 调反馈删除 → 删运行）和 `delete_recommendation_items`（先调反馈删除 → 删快照）两个方法。
  - 完成后下游反馈可以通过推荐运行标识和推荐项标识关联本次推荐。
  - _Requirements: 2.5, 4.3, 5.3, 7.1, 7.2, 7.3, 7.5_
  - _Boundary: RecommendationRepository_

- [ ] 4.3 暴露相似案例推荐 API
  - **POST `/api/recommendations/similar-cases`**：手动相似案例推荐入口，接收当前问题、Top-K、过滤条件和可选业务权重。响应成功、空结果、降级和失败状态时均使用一致结构。
  - **GET `/api/recommendations/runs/{run_id}`**：返回推荐运行状态和候选快照元数据（含 `contract_version`），不返回完整查询原文或完整案例正文；运行不存在时返回 404。
  - 完成后客户端可通过 HTTP 获取推荐结果、运行标识、推荐项标识、应用过滤条件、有效权重和分值明细；下游反馈规格可通过 GET 端点查询运行元数据。
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 5.1, 7.2_
  - _Boundary: RetrievalRouter_
  - _Depends: 4.1, 4.2_

- [ ] 4.4 接入应用入口、数据库会话和错误映射
  - 将检索推荐路由接入应用入口，纳入数据库 metadata 和请求事务生命周期。
  - 将校验、向量搜索、结构化评分、业务评分、重排、分值聚合、解释和系统错误映射为稳定响应。
  - 只追加路由注册、metadata 导入和错误码映射，不重构共享应用入口、数据库会话或错误映射基础设施。
  - 完成后从应用入口发起请求即可访问推荐端点，失败响应不会泄漏底层异常。
  - _Requirements: 1.3, 2.4, 3.4, 4.4, 7.4, 7.5_
  - _Boundary: RetrievalRouter, ErrorMapper_
  - _Depends: 4.3_

- [ ] 4.5 验证与上游和下游边界分离
  - 确认推荐流程只读取案例、向量候选、可消费 LLM 派生结果和推荐文案能力；查询规范化通过**共享 `LLMClient` + `NormalizerLLMConfig`** 执行，**不**复用 `llm-case-enrichment` 的 `EnrichmentLLMConfig`。不生成案例 embedding、不直接查询 pgvector，也不写回案例、LLM 派生、向量或反馈数据。
  - 对照依赖契约快照校验上游最小字段集、错误语义和兼容策略，发现缺失或破坏性变更时触发重验流程。
  - 确认响应不暴露聚合器内部对象、向量数组、完整问题原文或完整案例正文。
  - **配置隔离验证**：验证 `NormalizerLLMConfig` 和 `RerankerConfig` 是独立实例，不与 `EnrichmentLLMConfig`、`EmbeddingConfig` 共享引用（`id()` 检查）。
  - 完成后本规格边界与前置规格和后续反馈规格保持可独立验证。
  - _Requirements: 3.6, 4.5, 5.5, 6.2, 7.2, 7.5_
  - _Boundary: RecommendationService, RecommendationRepository_
  - _Depends: 4.4_

- [ ] 5. 补齐验证覆盖

- [ ] 5.1 编写查询、过滤、业务权重和向量候选消费测试
  - 覆盖空查询、Top-K 越界、无效过滤、权重越界、过滤回显、权重回显。
  - **`QueryNormalizer` + 共享 `LLMClient`**：成功解析、超时、限流、配置缺失、响应不可解析；断言使用 `NormalizerLLMConfig`（由 `llm-case-enrichment` 定义），**不依赖** `EnrichmentLLMConfig` 或 enrichment 模块测试替身。
  - **`QueryNormalizer`**：LLM normalizer 失败时不调用向量端口；成功时 `NormalizedRetrievalQuery` 同时携带检索文本与 `query_structured_suggestions`。结合 **`RecommendationService`**：断言 `create_run` → normalizer 失败 → `fail_run`，响应含 `recommendation_run_id`。
  - 覆盖空候选、候选不足和向量搜索失败；断言向量候选只包含可检索案例，并保留问题语义向量来源和索引版本。
  - **配置隔离回归测试**（复用 `llm-case-enrichment` 建立的基础设施）：验证修改 `RerankerConfig.timeout_ms` 不影响 `NormalizerLLMConfig` 的调用参数；验证 `NormalizerLLMConfig` 和 `RerankerConfig` 是独立实例（`id()` 检查）。
  - 完成后查询校验、LLM normalizer、业务权重校验、向量候选消费行为和配置隔离可被单元测试稳定验证。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Boundary: QueryNormalizer (with shared LLMClient), VectorSearchPort_

- [ ] 5.2 编写评分、聚合、解释和降级测试
  - 覆盖 reranker 成功排序、reranker 失败降级、结构化局部评分 skipped、业务评分、分值聚合成功、分值聚合失败降级、解释成功、解释失败降级和候选信息缺失。
  - 增加故障矩阵组合测试：`reranker + aggregation` 同时失败时按业务分优先降级，业务分不可用时回退向量顺序，并断言 `degraded_reason=reranker_and_aggregation_failed`。
  - 断言聚合不可用或降级排序路径下，候选 `final_score=0` 且 `score_breakdown` 包含“未聚合/默认值”标记；不得将 `0` 当作真实聚合分输出。
  - 断言降级响应不伪造语义分或聚合分，解释不会新增、删除或重排候选。
  - 完成后分值聚合、远程重排、业务评分、结构化评分和推荐解释边界均有独立测试，并能证明聚合器不从全量 casebase 独立检索。
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: StructuredSimilarityScorer, BusinessScoreCalculator, ScoreAggregator, RerankerClient, RecommendationExplainer_

- [ ] 5.3 编写依赖契约快照与兼容回归测试
  - 为 `a3-case-management`、`case-vector-indexing`、`llm-case-enrichment` 增加最小字段集和错误语义契约测试，验证新增字段兼容、必需字段缺失报错、等价字段映射和契约版本标记。
  - 为本规格的 **`QueryNormalizer` + 共享 `LLMClient`** 建立响应 schema 快照或等价契约测试（使用 `NormalizerLLMConfig`，独立于 `llm-case-enrichment` 的 `EnrichmentLLMConfig`，避免与文案 LLM 漂移耦合）。
  - 覆盖 `not_found`/`forbidden` 区分、向量端口 `timeout`/`unavailable`/`invalid_response` 映射、解释服务不改候选顺序。
  - **配置隔离验证**（复用 `llm-case-enrichment` 建立的基础设施）：验证 `NormalizerLLMConfig` 和 `RerankerConfig` 在 `backend/app/core/config.py` 中独立定义；验证修改某一模型配置（如 `RerankerConfig.base_url`）不影响 `NormalizerLLMConfig` 的调用参数；验证两个配置对象在应用启动时独立构造，不共享实例引用（`id()` 检查）。
  - 完成后跨规格接口漂移和配置隔离可在回归阶段被提前发现，避免运行时隐性降级。
  - _Requirements: 2.1, 2.4, 2.5, 5.2, 6.2, 7.3, 7.4_
  - _Boundary: VectorSearchPort, RecommendationCaseProvider, RecommendationExplainer_
  - _Depends: 2.2, 2.3, 3.4, 4.5_

- [ ] 5.4 编写推荐 API 与运行记录集成测试
  - 覆盖推荐成功、空结果、降级结果、运行查询和错误响应结构；覆盖 LLM normalizer 失败的 **503** + `recommendation_run_id` + 运行终态与「未调用向量搜索」断言。
  - 断言 **`reranker_status`**：从未进入重排的终态路径（如 normalizer 失败、向量失败、空候选）为 **`pending`**；重排已调用且成功为 **`succeeded`**、失败为 **`failed`**（与 `design.md`「Reranker 状态语义」一致）。
  - 断言 **`create_run` 后若编排抛未捕获异常**，仍通过守卫（如 `finally`）写入 **`fail_run`**，数据库无「已创建 run 但无终态」的悬挂记录。
  - 断言 **POST** 响应与 **GET** `/api/recommendations/runs/{run_id}` 返回的 **`contract_version`** 与数据库 **`recommendation_runs.contract_version`** 一致，且在 **`fail_run` / `complete_run` 后不被改写**。
  - 断言推荐运行和推荐项快照包含反馈引用标识、候选引用、分值明细、有效权重、状态和耗时。
  - 完成后端到端推荐 API 可用，且运行记录满足下游反馈关联需求。
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 7.1, 7.2, 7.3, 7.4_
  - _Boundary: RetrievalRouter, RecommendationService, RecommendationRepository_
  - _Depends: 4.4_

- [ ] 5.5 编写隐私、安全和边界测试
  - 覆盖日志、错误响应和运行记录不包含完整问题原文、完整案例正文、向量数组或供应商原始错误。
  - 覆盖生产 **LLM normalizer、reranker 或聚合**相关配置缺失时 fail closed；验证 `NormalizerLLMConfig` 和 `RerankerConfig` 互不串用，与 `EnrichmentLLMConfig`、`EmbeddingConfig` 隔离。
  - 覆盖推荐流程不写回上游或反馈表。
  - 完成后安全、隐私、配置隔离和跨规格边界要求均可通过自动化测试验证。
  - _Requirements: 5.5, 7.4, 7.5_
  - _Boundary: ErrorMapper, RecommendationRepository, RecommendationService_
  - _Depends: 4.5_

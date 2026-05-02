# Implementation Plan

- [ ] 1. Foundation: 向量索引运行基础
- [ ] 1.1 建立向量索引配置与生产启用门控
  - 增加 embedding provider、model、base_url、向量维度、超时、重试、pgvector 最低版本和供应商隐私确认配置。
  - 默认 model 为 `bge-large-zh`，默认维度为 1024，生产环境缺少必要配置时启动或调用失败关闭。
  - 仅向共享配置追加本规格所需配置值，不拥有 `backend/app/core/config.py` 基础实现。
  - 完成后，配置校验能区分开发 fake embedding、生产远程 embedding 和配置缺失三类状态。
  - _Requirements: 2.5, 6.4_

- [ ] 1.2 建立 pgvector 扩展、向量表、任务表和索引迁移
  - 启用 pgvector 扩展，并验证扩展版本不低于 `0.8.2`。
  - 创建保存成功案例向量、过滤字段、输入版本、当前有效标记、可检索标记和任务生命周期的持久化结构。
  - 建立 HNSW cosine 向量索引，以及品牌、门店、问题类型、状态、标签和时间字段索引。
  - 仅向共享 metadata 追加 `vector_indexing` ORM 导入，不拥有 `backend/app/db/base.py` 或数据库基础设施。
  - 完成后，迁移可在空库中创建所有向量索引结构，且不会修改案例基础表或 LLM 派生结果表。
  - _Requirements: 3.1, 3.5, 5.2, 6.4_

- [ ] 1.3 建立向量索引 API schema、状态枚举和错误码
  - 定义手动刷新、重试、移除/不可检索标记、状态查询、搜索请求和搜索候选响应结构。
  - 定义任务状态（queued、running、succeeded、retryable、failed、cancelled）和向量可检索状态（当前有效、可检索、降级原因）。
  - 增加输入不足、embedding 失败、维度不匹配、pgvector 不可用、查询参数无效等稳定错误码。
  - 仅向共享错误映射追加向量索引错误码，不拥有 `backend/app/core/errors.py` 或 `ErrorMapper` 基础实现。
  - 完成后，API 层可以返回一致的成功、校验失败、状态冲突和外部依赖失败响应。
  - _Requirements: 3.3, 5.3, 5.4, 6.3, 6.5_

- [ ] 2. Core indexing: 输入组合、embedding 和持久化
- [ ] 2.1 (P) 构建案例索引输入快照读取能力
  - 读取上游案例基础字段、状态、过滤字段、`updated_at` 和当前可消费的 LLM 派生结果。
  - 对 LLM 派生结果缺失、未发布或过期的情况返回明确可降级原因。
  - 对删除、归档或不可检索案例返回不可索引原因，不反向修改上游数据。
  - 完成后，同一个案例标识可以得到包含来源版本的索引输入快照。
  - _Requirements: 1.1, 1.3, 3.4, 3.5, 4.1_
  - _Boundary: CaseIndexSourceProvider_

- [ ] 2.2 (P) 构建问题侧 embedding 输入文本组合能力
  - 按稳定段落顺序组合问题摘要、问题描述、问题类型、场景上下文、根因分类、适用场景和标签。
  - 明确排除解决步骤、效果结果、方案摘要和推荐文案，避免主召回向量被解法文本污染。
  - 为每个段落保留来源字段、来源版本、模板版本和内容指纹。
  - 在内容不足时拒绝生成输入，并返回可定位缺失字段；在 LLM 派生文本不可用时生成降级输入。
  - 完成后，相同输入快照会生成相同文本指纹，且不会包含解决步骤、效果结果、方案摘要、推荐分值、反馈或未授权字段。
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 6.1_
  - _Boundary: EmbeddingInputComposer_

- [ ] 2.3 (P) 构建远程 embedding 客户端与响应校验
  - 调用配置的云端 embedding 接入点，并记录供应商、模型 id、维度、输入指纹和调用状态。
  - 将超时、限流、供应商错误、格式不可解析和向量维度不匹配映射为稳定错误。
  - 确保失败日志只包含标识、模型、状态、错误码和输入哈希，不包含完整文本或向量数组。
  - 完成后，fake 和远程客户端都遵循同一响应校验与错误结构。
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 6.5_
  - _Boundary: EmbeddingClient_

- [ ] 2.4 (P) 构建向量仓储的发布、状态和搜索基础
  - 保存成功向量、输入版本、过滤字段、当前有效标记、可检索标记、任务状态和最近失败原因。
  - 发布新向量时停用同一案例旧输入版本，保证当前有效向量唯一。
  - 搜索查询只返回当前有效且可检索的向量记录。
  - 完成后，仓储可以独立完成向量发布、任务更新、不可检索标记和过滤搜索。
  - _Requirements: 1.5, 3.1, 3.2, 4.2, 4.5, 5.2, 6.2_
  - _Boundary: VectorRepository_

- [ ] 3. Lifecycle: 手动刷新、重试、移除和状态
- [ ] 3.1 编排单案例向量刷新与发布流程
  - 串联输入快照、输入组合、embedding 调用、向量校验和仓储发布。
  - 对相同输入指纹避免重复发布；对新输入版本发布新向量并停用旧当前版本。
  - 完成后，合法案例刷新会生成当前有效向量；如使用降级输入，应在向量记录中保存降级原因，并可通过状态接口查询。
  - _Depends: 2.1, 2.2, 2.3, 2.4_
  - _Requirements: 2.1, 3.1, 3.2, 3.3, 4.1, 4.2_
  - _Boundary: VectorIndexService_

- [ ] 3.2 实现手动刷新幂等判断
  - 在手动刷新请求中根据案例更新时间、派生结果版本、输入模板版本和内容指纹判断输入版本是否变化。
  - 对相同输入版本返回当前有效向量或已有任务，避免重复发布和重复排队。
  - 完成后，基础案例或可消费 LLM 派生文本变化需要由调用方显式触发刷新，本服务不执行自动刷新或自动过期扫描。
  - _Requirements: 1.5, 4.1, 6.2_
  - _Boundary: VectorIndexService, VectorJobRunner_

- [ ] 3.3 实现失败记录和受控重试
  - 保存失败阶段、错误类型、可重试状态、重试次数和下一次可重试时间。
  - 对超时、限流和供应商失败执行受控重试；对输入不足、维度不匹配和配置缺失拒绝重试。
  - 完成后，重试接口只接受可重试任务，并在超过上限后保留失败任务状态和最近有效向量说明。
  - _Requirements: 2.3, 2.4, 4.3, 4.4, 6.2, 6.3_
  - _Boundary: VectorJobRunner, VectorIndexService_

- [ ] 3.4 实现手动移除和不可检索标记一致性
  - 当调用方明确请求移除或案例不可检索标记时，将当前有效向量标记为不可检索。
  - 通过任务记录保留状态变化审计，并确保搜索不会返回不可检索案例。
  - 完成后，案例不可作为来源时仍可查询索引状态，但不会出现在向量搜索命中中。
  - _Requirements: 3.4, 4.5, 6.2_
  - _Boundary: VectorIndexService, VectorRepository_

- [ ] 4. Search primitives: 查询向量化与 Top-K 候选搜索原语
- [ ] 4.1 构建用户问题查询向量生成和搜索请求校验
  - 校验查询文本、Top-K 范围和过滤字段。
  - 使用与案例索引一致的 embedding 客户端生成查询向量。
  - 完成后，非法查询返回字段级错误，合法查询产生可搜索的用户问题查询向量和查询元数据。
  - _Depends: 2.3_
  - _Requirements: 5.1, 5.3, 6.5_
  - _Boundary: VectorSearchService, VectorSchemas, EmbeddingClient_

- [ ] 4.2 实现带结构化过滤的 Top-K 问题语义候选搜索
  - 使用品牌、门店、问题类型、标签、状态和时间范围过滤可检索向量；时间范围按天粒度使用 `case_vectors.created_at` 近似案例创建时间。
  - 返回候选案例标识、向量标识、距离、相似度、输入版本和过滤元数据。
  - 完成后，搜索结果只包含满足过滤条件且可检索的案例，并按问题语义距离排序。
  - _Depends: 2.4, 4.1_
  - _Requirements: 5.1, 5.2, 5.4_
  - _Boundary: VectorSearchService, VectorRepository_

- [ ] 4.3 明确候选搜索原语与推荐编排解耦
  - 搜索响应不包含推荐理由、业务参数分、reranker 分数、CBRKit 内部结构、反馈或最终展示顺序字段。
  - 为下游保留必要索引元数据，便于 CBR 检索推荐规格在候选集内完成补齐、重排和解释。
  - 完成后，搜索接口只提供向量候选原语，不会调用 CBRKit、reranker 或推荐文案服务，也不会决定最终推荐展示顺序。
  - _Requirements: 5.5_
  - _Boundary: VectorSearchService_

- [ ] 5. Validation: API、数据库、隐私和回归验证
- [ ] 5.1 完成刷新、状态、重试和搜索 API 集成测试
  - 覆盖单案例手动刷新成功、降级输入、失败任务状态、重试成功、重试上限、手动不可检索标记和状态查询。
  - 覆盖搜索成功、空结果、过滤条件、非法参数和不可检索案例不命中。
  - 完成后，API 测试能验证主要用户和下游可观察行为。
  - _Requirements: 1.3, 2.3, 3.3, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4_
  - _Boundary: VectorRouter, VectorIndexService, VectorSearchService, VectorJobRunner_

- [ ] 5.2 完成 pgvector 迁移和仓储集成测试
  - 验证 pgvector 版本检查、向量维度、HNSW cosine 索引和过滤字段索引。
  - 验证发布新向量时旧版本不再是当前有效结果。
  - 完成后，数据库层可证明向量结构、索引和当前有效记录规则符合设计。
  - _Requirements: 3.1, 3.2, 4.2, 5.2, 6.4_
  - _Boundary: PgvectorChecks, VectorRepository_

- [ ] 5.3 完成隐私、安全和可观测性测试
  - 验证生产配置缺失时 fail closed。
  - 验证日志、错误响应和任务记录不包含完整案例正文、完整 embedding 输入文本或向量数组。
  - 验证任务生命周期记录覆盖排队、处理中、成功、失败、重试和移除/不可检索标记。
  - 完成后，运维可按案例标识查看状态和失败原因，敏感内容不会进入日志或错误响应。
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: VectorJobRunner, VectorIndexService, VectorSearchService, ErrorMapper_

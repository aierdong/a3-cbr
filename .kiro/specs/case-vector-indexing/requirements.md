# Requirements Document

## Introduction

`case-vector-indexing` 为 A3 案例知识库提供可检索的问题侧语义向量索引能力。该模块消费 `a3-case-management` 的基础问题字段和过滤字段，以及 `llm-case-enrichment` 已校验的问题摘要、结构化建议、标签建议和派生结果状态；在明确触发刷新、重试或移除操作后生成或更新 embedding，并维护可供下游推荐阶段稳定消费的索引状态与候选向量搜索原语。

本规格聚焦以下能力：云端 embedding 生成、问题侧 embedding 输入文本组合、PostgreSQL + pgvector 向量存储与索引、刷新/重试/状态管理，以及向量搜索基础能力。相似案例推荐、CBRKit 编排、reranker、推荐理由生成和反馈学习排序由后续规格负责。

## Boundary Context

- **In scope**: 问题侧向量化输入文本策略、云端 embedding 调用、案例问题向量记录、索引状态、手动刷新与重试、手动移除/不可检索标记一致性、基础 Top-K 向量搜索原语。
- **Out of scope**: CBRKit 编排、候选重排、推荐理由、最终推荐排序、反馈学习、多模型候选搜索、Milvus 等独立向量库、本地模型部署和推理成本优化。
- **Adjacent expectations**: 本规格依赖 `a3-case-management` 提供稳定的 `case_id`、基础字段、状态、过滤字段和 `updated_at`；依赖 `llm-case-enrichment` 提供已发布或明确可消费的摘要与规范化文本；`cbr-retrieval-recommendation` 仅消费本规格输出的候选搜索原语和索引状态，不反向要求本规格承担推荐编排。

## Requirements

### Requirement 1: 问题侧 Embedding 输入文本组合

**Objective:** As a 下游检索功能实现者, I want 系统按稳定规则组合案例的问题侧语义画像, so that 用户问题向量能够优先召回问题相似的历史案例，而不是被解决方案或效果文本干扰。

#### Acceptance Criteria

1.1 When 案例进入可索引处理, the 案例向量索引服务 shall 基于问题描述、问题类型、场景上下文、LLM 问题摘要和可消费的结构化问题建议生成单一问题侧 embedding 输入文本。
1.2 The 案例向量索引服务 shall 在输入文本中保留以下来源分段：问题摘要、问题描述、问题类型、场景上下文、根因分类、适用场景和标签。
1.3 The 案例向量索引服务 shall 不把解决步骤、效果结果、方案摘要或推荐文案纳入主召回 embedding 输入；这些内容只能作为下游展示、解释、reranker 输入或未来解法相似向量的来源。
1.4 When LLM 派生文本不存在、未发布或已过期, the 案例向量索引服务 shall 使用可用的问题描述、问题类型和场景上下文生成降级输入，并在索引状态中标记降级原因。
1.5 If 案例问题侧内容不足以形成可检索文本, then the 案例向量索引服务 shall 拒绝生成 embedding，并记录可定位的缺失信息。
1.6 The 案例向量索引服务 shall 为每次输入文本保存内容指纹、来源版本和生成时间，以支持后续判断是否需要刷新。

### Requirement 2: 云端 embedding 生成

**Objective:** As a 平台管理员, I want 案例通过受控的云端 embedding 服务生成向量, so that 语义索引质量可审计、可替换，且运行记录仅保留 `embedding_model_id` 等必要模型标识。

#### Acceptance Criteria

2.1 When embedding 输入文本准备完成, the 案例向量索引服务 shall 调用配置的云端 embedding 服务（provider/model/base_url）生成向量。
2.2 The 案例向量索引服务 shall 记录 `embedding_model_id`、向量维度、输入指纹和调用状态；provider/base_url 仅作为运行时配置，不作为持久化字段。
2.3 If embedding 调用超时、限流或供应商失败, then the 案例向量索引服务 shall 记录失败阶段、错误类型和是否可重试，而不阻塞案例基础查看。
2.4 If embedding 响应缺失向量、维度不匹配或格式不可解析, then the 案例向量索引服务 shall 不发布该向量，并记录校验失败原因。
2.5 The 案例向量索引服务 shall 支持通过配置替换云端 embedding 供应商，且默认 model 保持为 `bge-large-zh`。

### Requirement 3: 向量记录与可检索状态

**Objective:** As a 后台管理者, I want 每个可索引案例都有清晰的向量记录和状态, so that 前端和下游流程能够判断案例是否可参与候选向量搜索。

#### Acceptance Criteria

3.1 When 案例 embedding 校验通过, the 案例向量索引服务 shall 保存问题侧语义向量、结构化过滤字段、输入版本和可检索标记。
3.2 The 案例向量索引服务 shall 为每个案例维护当前有效向量记录，并避免同一输入版本重复发布多条有效向量。
3.3 While 刷新或重试任务处于排队、处理中、失败、可重试或成功状态, the 案例向量索引服务 shall 基于任务记录和当前有效向量对外返回明确索引状态。
3.4 When 案例状态不允许被检索且调用方明确请求移除或标记不可检索, the 案例向量索引服务 shall 将当前有效向量标记为不可检索，并通过任务记录保留可审计状态变化。
3.5 The 案例向量索引服务 shall 不把向量、相似度、推荐分值或反馈信息写回 `a3-case-management` 的案例基础字段。

### Requirement 4: 刷新、删除与重试一致性

**Objective:** As a 运维人员, I want 案例内容变化后可以手动触发向量索引刷新并可控重试, so that 索引更新由明确操作驱动且运行过程可审计。

#### Acceptance Criteria

4.1 When 调用方针对案例基础字段、案例状态或可消费的 LLM 派生文本变化手动请求刷新, the 案例向量索引服务 shall 判断输入版本是否变化，并在需要时创建刷新任务。
4.2 When 刷新任务成功完成, the 案例向量索引服务 shall 发布新向量，并使旧输入版本不再作为当前有效结果。
4.3 If 刷新任务失败且错误可重试, then the 案例向量索引服务 shall 按受控次数记录重试尝试和下一次可重试时间。
4.4 If 刷新任务超过重试上限或错误不可重试, then the 案例向量索引服务 shall 将任务状态标记为失败并保留最近一次有效向量的可用性说明。
4.5 When 案例被删除、归档或变为不可作为检索来源且调用方明确请求移除或标记不可检索, the 案例向量索引服务 shall 停止将该案例作为向量搜索命中返回。

### Requirement 5: 向量搜索原语

**Objective:** As a CBR 检索推荐实现者, I want 使用向量搜索原语获取候选案例, so that 推荐流程可在本规格之外完成候选补齐、重排和解释。

#### Acceptance Criteria

5.1 When 下游提交已标准化的用户问题文本和 Top-K 参数, the 案例向量索引服务 shall 生成查询向量，并返回按问题语义相似度排序的候选案例标识、分值和索引元数据。
5.2 When 下游提交品牌、门店、问题类型、标签、状态或时间范围过滤条件, the 案例向量索引服务 shall 在搜索结果中仅返回满足过滤条件且可检索的案例。
5.3 If 查询文本为空、Top-K 越界或过滤条件无效, then the 案例向量索引服务 shall 拒绝搜索并返回字段级错误信息。
5.4 If 没有满足条件的向量结果, then the 案例向量索引服务 shall 返回空候选列表和有效查询元数据。
5.5 The 案例向量索引服务 shall 不生成推荐理由、不调用 reranker、不执行 CBRKit 重排，也不决定最终推荐展示顺序。

### Requirement 6: 安全、隐私、可观测性与运行约束

**Objective:** As a 平台管理员, I want 向量化过程可审计、可观测且保护案例敏感内容, so that 外部模型调用和索引运行风险可控。

#### Acceptance Criteria

6.1 The 案例向量索引服务 shall 在发送给 embedding 服务前限制输入范围，仅包含生成案例语义向量所需的文本片段。
6.2 The 案例向量索引服务 shall 记录向量任务生命周期，包括排队、处理中、成功、失败、重试和移除/不可检索标记。
6.3 The 案例向量索引服务 shall 提供按案例标识查询索引状态和最近失败原因的能力。
6.4 If embedding 生产配置缺少 provider、model、base_url、凭据来源、超时、重试或供应商隐私确认, then the 案例向量索引服务 shall 拒绝启用生产向量化流程。
6.5 The 案例向量索引服务 shall 避免在日志和错误响应中暴露完整案例正文、完整 embedding 输入文本或向量数组。
# Requirements Document

## Introduction

`cbr-retrieval-recommendation` 为门店、督导和后台使用者提供混合式案例推理（Hybrid CBR）检索推荐能力。用户输入新问题后,检索推荐服务首先生成问题摘要或标准化查询，校验查询和过滤条件，再消费 `case-vector-indexing` 返回的问题语义 Top-K 向量候选，依次完成候选详情补齐、结构化局部相似度计算、远程 reranker 语义精排、业务参数分计算、分值加权聚合、推荐结果组装和可解释响应。

本规格依赖 `a3-case-management` 的案例标识、基础字段、状态和过滤字段，依赖 `llm-case-enrichment` 的推荐文案生成能力，依赖 `case-vector-indexing` 的候选向量搜索原语和索引状态。它不负责案例创建、LLM 派生结果持久化、embedding 生成或写入、pgvector 索引维护、反馈记录或前端页面。

## Boundary Context

- **In scope**: 查询输入摘要/标准化、基础过滤条件校验（当存在过滤条件时）、向量候选消费、候选详情补齐、结构化局部相似度、业务参数分、reranker 候选重排与分值聚合、Top-K 推荐组装、语义相似度、业务分和最终分值、推荐理由降级、案例引用、检索运行状态和可解释响应契约。
- **Out of scope**: A3 案例 CRUD、LLM 摘要和推荐文案持久化、embedding 生成和 pgvector 索引维护、推荐反馈保存、反馈学习排序、自动推送渠道、前端 UI、复杂多轮追问、行业库加权。
- **Adjacent expectations**:
  - 上游向量索引必须只返回基于问题侧语义画像的可检索候选原语。本规格不得直接生成或维护案例 embedding，也不得绕过向量索引直接查询 pgvector。
  - LLM 增强可为查询摘要、候选结构化字段和已排序候选生成推荐文案，但不改变排序。
  - 下游反馈和前端只能消费本规格返回的推荐运行标识、候选标识、分值、解释和引用，不要求本规格保存反馈或展示页面状态。

## Requirements

### Requirement 1: 查询输入与过滤条件

**Objective:** As a 门店用户或督导, I want 输入新问题并指定基础过滤条件, so that 系统只在相关品牌、门店和场景范围内寻找可参考案例。

#### Acceptance Criteria

1.1 When 用户提交相似案例检索请求, the CBR 检索推荐服务 shall 接收当前问题文本、Top-K 参数、可选过滤条件和可选业务权重参数。
1.2 The CBR 检索推荐服务 shall 支持品牌、门店、问题类型、标签、案例状态和创建时间范围等基础过滤条件，并将问题类型、品牌等硬过滤用于去除明显无关案例（当存在过滤条件时）。
1.3 If 当前问题文本为空、Top-K 越界或过滤条件格式无效, then the CBR 检索推荐服务 shall 拒绝检索并返回字段级错误信息。
1.4 When 过滤条件未命中任何可检索案例, the CBR 检索推荐服务 shall 返回空推荐列表和有效查询元数据。
1.5 The CBR 检索推荐服务 shall 在响应中回显规范化后的过滤条件，便于用户和下游流程理解实际检索范围。
1.6 The CBR 检索推荐服务 shall 对用户问题生成摘要或标准化查询文本，并使用该文本调用向量搜索和 reranker。
1.7 If 摘要或标准化查询生成失败（超时、限流、配置缺失或不可解析响应）, then the CBR 检索推荐服务 shall 终止本次检索（fail closed）：不得调用向量搜索，不得使用原始问题文本替代摘要继续检索；shall 在调用向量搜索之前已通过 `create_run`（或等价操作）建立推荐运行记录，并在失败收尾时通过 `fail_run`（或等价操作）写入终态；shall 返回稳定失败状态、`recommendation_run_id` 以及面向用户的可读提示文案（不包含完整问题原文或供应商原始错误）。

### Requirement 2: 向量候选消费

**Objective:** As a CBR 推荐实现者, I want 消费稳定的向量搜索候选, so that 推荐流程可以在候选集内继续补齐、重排和解释。

#### Acceptance Criteria

2.1 When 查询输入通过校验, the CBR 检索推荐服务 shall 调用 `case-vector-indexing` 的向量搜索能力，获取满足过滤条件的候选案例标识、问题语义向量相似度分值和索引元数据。
2.2 The CBR 检索推荐服务 shall 只使用索引状态明确可检索的候选案例，不展示已移除、失败、过期且不可用的向量记录。
2.3 If 向量搜索能力返回空候选列表, then the CBR 检索推荐服务 shall 返回空推荐列表、查询元数据和未命中原因。
2.4 If 向量搜索能力不可用、超时或返回不可解析结果, then the CBR 检索推荐服务 shall 返回稳定失败状态，不编造候选案例。
2.5 The CBR 检索推荐服务 shall 保留向量搜索运行引用和候选索引版本，支持后续排查候选来源。
2.6 When 消费向量搜索结果, the CBR 检索推荐服务 shall 要求批次响应包含稳定的 `search_ref`（或等价运行引用）与 `index_version`（或等价索引版本标识），并要求每条候选包含 `case_id`、`vector_id`、`similarity_score` 与 `index_status`；若缺失或不可解析, then the CBR 检索推荐服务 shall 视为向量搜索返回无效并按稳定失败路径处理，不编造候选。

### Requirement 3: 语义精排、结构化局部相似度与业务评分

**Objective:** As a 门店用户或督导, I want 系统同时考虑语义相似、结构化场景相近和业务参数适配, so that 最相似、最可参考的历史案例优先展示。

#### Acceptance Criteria

3.1 When 向量搜索返回候选案例, the CBR 检索推荐服务 shall 使用远程 reranker 对查询摘要和候选问题画像执行语义精排，生成纯语义相似度分值。
3.2 The CBR 检索推荐服务 shall 基于 `CaseEnrichmentResult.structured_suggestions` 中的问题类型建议、根因分类、适用场景和标签建议计算结构化局部相似度分值；MVP 可将该分值标记为 skipped，但契约必须预留。
3.3 If 候选数量少于请求 Top-K, then the CBR 检索推荐服务 shall 返回实际可用数量并说明候选不足。
3.4 If 重排能力失败但存在可用向量候选, then the CBR 检索推荐服务 shall 返回明确降级状态，并按向量候选原始顺序或已定义业务分降级顺序展示候选。
3.5 The CBR 检索推荐服务 shall 根据请求中的业务权重参数和候选业务字段计算业务参数分，例如相同业态、相近门店等级、相近时间范围或同品牌加权。
3.6 The CBR 检索推荐服务 shall 不使用反馈数据自动调整本次排序，除非后续反馈学习规格另行定义。

### Requirement 4: 分值聚合排序

**Objective:** As a CBR 推荐实现者, I want 将语义分、结构化局部相似度和业务参数分按可配置权重聚合, so that 最终排序既符合语义相关性，也符合业务适配目标。

#### Acceptance Criteria

4.1 When 候选评分完成, the CBR 检索推荐服务 shall 聚合向量相似度、reranker 语义相似度、结构化局部相似度和业务参数分，生成最终排序分。
4.2 The CBR 检索推荐服务 shall 使用配置化默认权重，并允许请求在受控范围内调整业务参数权重。
4.3 The CBR 检索推荐服务 shall 在每个推荐项中保留向量相似度、语义重排分、结构化局部相似度、业务参数分、最终聚合分和权重元数据。
4.4 If 分值聚合失败但存在语义精排结果, then the CBR 检索推荐服务 shall 降级为语义精排顺序，并标记聚合降级原因。
4.5 The CBR 检索推荐服务 shall 保证聚合器只处理向量搜索已返回的候选集，不从全量 casebase 重新检索。
4.6 When 无法得到可信的最终聚合分（例如标记为 `aggregation_unavailable`，或排序来自定义的降级路径而非成功聚合）, then the CBR 检索推荐服务 shall 将该候选的 `final_score` 置为 `0`，并在 `score_breakdown` 中明示「未聚合/默认值」语义；不得将 `0` 伪装为真实聚合得分误导下游。

### Requirement 5: 推荐结果组装

**Objective:** As a 门店用户或督导, I want 查看相似案例、核心解决步骤和可追溯来源, so that 我能快速判断历史案例是否值得参考。

#### Acceptance Criteria

5.1 When 候选排序完成, the CBR 检索推荐服务 shall 返回 Top-K 相似案例推荐项。
5.2 The CBR 检索推荐服务 shall 在每个推荐项中包含案例标识、案例引用信息、问题摘要或问题描述、核心解决步骤、效果摘要或结果信息、过滤字段摘要、各类分值和最终排序位置。
5.3 The CBR 检索推荐服务 shall 保留推荐项与原始案例、向量候选、结构化派生结果、重排结果、业务评分和聚合结果之间的引用关系。
5.4 If 某个候选案例缺少摘要、结构化建议、解决步骤或效果信息, then the CBR 检索推荐服务 shall 返回可用结构化信息并标记缺失字段，而不是移除可用候选。
5.5 The CBR 检索推荐服务 shall 不在推荐响应中写入或更新案例基础字段、向量记录、LLM 派生结果或反馈记录。

### Requirement 6: 推荐解释与降级文案

**Objective:** As a 门店用户或督导, I want 每条推荐附带清晰理由和注意事项, so that 我能理解为什么该案例值得参考以及哪些差异需要谨慎处理。

#### Acceptance Criteria

6.1 When 推荐候选已排序, the CBR 检索推荐服务 shall 为每个推荐项返回推荐理由、可参考解决点、注意事项和来源引用。
6.2 The CBR 检索推荐服务 shall 确保推荐解释引用对应候选案例，不新增未排序候选或改变排序结果。
6.3 If 推荐文案生成失败或部分候选信息不足, then the CBR 检索推荐服务 shall 使用结构化候选信息生成降级解释，并标记解释状态。
6.4 The CBR 检索推荐服务 shall 在响应中区分由排序规则产生的分值和由解释文案产生的自然语言说明。
6.5 The CBR 检索推荐服务 shall 避免输出没有案例引用、没有分值或没有来源字段的黑盒推荐。

### Requirement 7: 检索运行记录、可观测性与边界

**Objective:** As a 平台管理员或下游功能实现者, I want 检索推荐过程可审计、可观测且边界清晰, so that 推荐质量问题可以定位，反馈和前端也能稳定消费结果。

#### Acceptance Criteria

7.1 When 每次检索请求被处理, the CBR 检索推荐服务 shall 生成稳定推荐运行标识，并记录查询哈希、过滤条件、业务权重、候选数量、最终数量、降级状态和错误类型。
7.2 The CBR 检索推荐服务 shall 在响应中返回可供下游反馈记录引用的推荐运行标识和推荐项标识。
7.3 The CBR 检索推荐服务 shall 记录重排 `model_id`、调用状态和耗时，默认重排 model 为 `qwen3-reranker-8b`；api_key/base_url 仅作为运行时配置，不作为持久化字段。持久化的调用状态 `reranker_status` shall 取 `pending`（**默认值**：尚未得到重排外呼最终结果，含从未进入重排阶段的终态路径）、`succeeded`、`failed` 或 `skipped` 之一；`pending` shall 与 `failed` 区分，后者仅表示已发起重排外呼且失败。
7.4 If 外部重排、结构化局部评分、业务评分、分值聚合或解释依赖缺少生产配置、超时、限流或供应商失败, then the CBR 检索推荐服务 shall fail closed 或降级到已定义候选展示路径，并返回稳定状态；摘要或标准化查询生成失败不适用降级检索路径，适用 Requirement `1.7` 的终止策略。
7.5 The CBR 检索推荐服务 shall 避免在日志、错误响应和运行记录中暴露完整问题原文、完整案例正文、向量数组或敏感门店信息。
7.6 When 为推荐项生成或持久化 `recommendation_item_id`, the CBR 检索推荐服务 shall 保证该标识**不等于**字面字符串 `RUN`（该取值保留给下游 `recommendation-feedback` 表示运行级反馈持久化哨兵）。